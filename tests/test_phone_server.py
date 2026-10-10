import http.client
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from anime_watcher.database import LibraryDatabase
from anime_watcher.phone_server import PhoneError, PhoneServer, byte_range, playback_plan


def media_info(codec='h264', audio='aac', subtitles=False):
    return {'duration': 1200, 'video': {'index': 0, 'codec_name': codec, 'pix_fmt': 'yuv420p', 'level': 41},
            'audio': [{'index': 1, 'codec_name': audio}],
            'subtitles': [{'index': 2, 'codec_name': 'ass'}] if subtitles else [], 'sidecars': []}


class PhoneServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.base = Path(self.temp.name)
        self.root = self.base / 'library'; self.root.mkdir()
        self.path = self.root / 'Show' / 'Season 01' / 'Show - S01E01 [Dub].mp4'
        self.path.parent.mkdir(parents=True); self.path.write_bytes(b'0123456789')
        self.db = LibraryDatabase(self.base / 'library.db'); self.row, _ = self.db.index_download(self.path, self.root)
        self.db.set_setting('secret_setting', 'private-value')
        self.server = PhoneServer(self.db.path, self.root, self.base, port=0, host='127.0.0.1')
        self.cookie = ''; self.csrf = ''

    def tearDown(self):
        self.server.stop(); self.db.close(); self.temp.cleanup()

    def request(self, method, path, data=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.port, timeout=5)
        outgoing = {'Cookie': self.cookie, 'X-Phone-CSRF': self.csrf}
        if data is not None: outgoing['Content-Type'] = 'application/json'
        outgoing.update(headers or {})
        connection.request(method, path, json.dumps(data) if data is not None else None, outgoing)
        response = connection.getresponse(); body = response.read(); response_headers = dict(response.getheaders())
        connection.close(); return response.status, body, response_headers

    def pair(self):
        status, body, headers = self.request('POST', '/api/pair', {'key': self.server.pair_key})
        self.assertEqual(status, 200); self.cookie = headers['Set-Cookie'].split(';')[0]; self.csrf = json.loads(body)['csrf']
        return self.cookie.split('=', 1)[1]

    def play(self, **kwargs):
        with patch('anime_watcher.phone_server.inspect_media', return_value=media_info()):
            status, body, _ = self.request('POST', '/api/play', {'episode': self.row['id'], **kwargs})
        self.assertEqual(status, 200, body); return json.loads(body)

    def test_pairing_required_and_private_paths_and_settings_never_exposed(self):
        self.assertEqual(self.request('GET', '/api/library')[0], 401)
        self.pair(); status, body, _ = self.request('GET', '/api/library'); self.assertEqual(status, 200)
        self.assertNotIn(str(self.base).encode(), body); self.assertNotIn(b'private-value', body)
        self.assertEqual(self.request('GET', f"/api/series/{self.row['series_id']}")[0], 200)

    def test_expired_rotated_pair_codes_and_wrong_profile_cookies_rejected(self):
        old = self.server.pair_key; self.server.refresh_pairing()
        self.assertEqual(self.request('POST', '/api/pair', {'key': old})[0], 403)
        self.server.pair_expires = 0
        self.assertEqual(self.request('POST', '/api/pair', {'key': self.server.pair_key})[0], 403)
        self.cookie = 'aw_phone=unknown'; self.assertEqual(self.request('GET', '/api/session')[0], 401)

    def test_host_origin_and_csrf_protect_library_and_mutations(self):
        self.pair()
        self.assertEqual(self.request('GET', '/api/library', headers={'Host': 'example.com'})[0], 403)
        self.assertEqual(self.request('POST', '/api/stop', {}, {'Origin': 'https://other.example'})[0], 403)
        self.assertEqual(self.request('POST', '/api/stop', {}, {'X-Phone-CSRF': ''})[0], 403)
        self.assertEqual(self.request('POST', '/api/stop', {}, {'Sec-Fetch-Site': 'cross-site'})[0], 403)

    def test_manual_pairing_code_is_expiring_and_failed_attempts_are_limited(self):
        code = self.server.pair_code
        self.assertEqual(self.request('POST', '/api/pair', {'key': code[:4] + ' ' + code[4:]})[0], 200)
        self.server.refresh_pairing()
        for _ in range(5): self.assertEqual(self.request('POST', '/api/pair', {'key': 'wrong'})[0], 403)
        self.assertEqual(self.request('POST', '/api/pair', {'key': self.server.pair_code})[0], 429)

    def test_direct_video_head_open_suffix_and_invalid_ranges(self):
        self.pair(); stream = self.play(offset=30)
        self.assertEqual(stream['mode'], 'direct')
        for value, expected in [('bytes=2-4', b'234'), ('bytes=7-', b'789'), ('bytes=-3', b'789')]:
            status, body, headers = self.request('GET', stream['url'], headers={'Range': value})
            self.assertEqual(status, 206); self.assertEqual(body, expected); self.assertIn('Content-Range', headers)
        self.assertEqual(self.request('HEAD', stream['url'])[1], b'')
        self.assertEqual(self.request('GET', stream['url'], headers={'Range': 'bytes=99-'})[0], 416)

    def test_stream_ownership_progress_and_stop_reuses_single_session_slot(self):
        self.pair(); first = self.play(offset=30, generation=1)
        status, _, _ = self.request('POST', '/api/progress', {'stream': first['id'], 'position': 50})
        self.assertEqual(status, 200); self.assertEqual(self.db.episode(self.row['id'])['progress_ms'], 50000)
        self.assertEqual(self.request('POST', '/api/progress', {'stream': first['id'], 'position': 50000})[0], 400)
        second = self.play(generation=2); self.assertEqual(len(self.server.streams), 1)
        self.assertEqual(self.request('GET', first['url'])[0], 404)
        cookie, csrf = self.cookie, self.csrf; self.pair()
        self.assertEqual(self.request('GET', second['url'])[0], 404)
        self.cookie, self.csrf = cookie, csrf
        self.assertEqual(self.request('POST', '/api/stop', {'generation': 3})[0], 200)
        self.assertFalse(self.server.streams)

    def test_generation_blocks_late_requests_and_missing_changed_or_outside_files(self):
        self.pair(); stream = self.play(generation=3)
        status, body, _ = self.request('GET', '/api/session')
        self.assertEqual(json.loads(body)['generation'], 3)
        with patch('anime_watcher.phone_server.inspect_media', return_value=media_info()):
            self.assertEqual(self.request('POST', '/api/play', {'episode': self.row['id'], 'generation': 2})[0], 409)
        self.path.write_bytes(b'changed')
        self.assertEqual(self.request('GET', stream['url'])[0], 409)
        outside = self.base / 'outside.mp4'; outside.write_bytes(b'private')
        self.db.connection.execute('UPDATE episodes SET path=? WHERE id=?', (str(outside), self.row['id'])); self.db.connection.commit()
        with self.assertRaises(PhoneError): self.server.episode(self.row['id'])

    def test_routes_do_not_allow_traversal_and_frontend_assets_are_local(self):
        self.assertEqual(self.request('GET', '/')[0], 200)
        for path in ['/app.js', '/style.css', '/manifest.webmanifest', '/icon.svg']:
            self.assertEqual(self.request('GET', path)[0], 200)
        self.pair(); self.assertEqual(self.request('GET', '/media/../../library.db')[0], 404)
        self.assertEqual(self.request('GET', '/api/settings')[0], 404)

    def test_byte_ranges_and_codec_choices(self):
        self.assertEqual(byte_range('bytes=-99', 10), (0, 9, True))
        for value in ['bytes=-0', 'bytes=7-2', 'bytes=1-2,4-5', 'bytes=-']:
            with self.assertRaises(PhoneError): byte_range(value, 10)
        self.assertEqual(playback_plan(self.path, media_info())['mode'], 'direct')
        self.assertEqual(playback_plan(self.path.with_suffix('.mkv'), media_info())['mode'], 'hls')
        self.assertTrue(playback_plan(self.path, media_info(audio='opus'))['copy_video'])
        self.assertFalse(playback_plan(self.path, media_info(codec='vp9'))['copy_video'])
        self.assertFalse(playback_plan(self.path, media_info(subtitles=True), subtitle='embedded:0')['copy_video'])
        self.assertEqual(playback_plan(self.path, media_info(), compatible=True)['mode'], 'hls')


if __name__ == '__main__': unittest.main()
