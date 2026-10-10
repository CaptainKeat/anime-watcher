"""Opt-in LAN companion. Only paired sessions can access the active library."""
from __future__ import annotations

from contextlib import contextmanager
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import math
import mimetypes
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from .media_chapters import find_ffprobe
from .preview import find_ffmpeg
from .subtitles import find_sidecar_subtitles
from .ui_common import resource_path


class PhoneError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def byte_range(value, size):
    """A single RFC byte range, including suffix/open-ended requests."""
    if not value:
        return 0, size - 1, False
    match = re.fullmatch(r'bytes=(\d*)-(\d*)', value)
    if not match or not any(match.groups()) or size <= 0:
        raise PhoneError('Unsatisfiable byte range.', 416)
    left, right = match.groups()
    start = int(left) if left else max(0, size - int(right))
    end = min(size - 1, int(right)) if left and right else size - 1
    if start >= size or end < start or (not left and int(right) == 0):
        raise PhoneError('Unsatisfiable byte range.', 416)
    return start, end, True


def inspect_media(path):
    probe = find_ffprobe()
    if not probe:
        raise PhoneError('The media tools are missing. Reinstall the current Windows release.', 503)
    result = subprocess.run([probe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                            capture_output=True, text=True, timeout=20,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise PhoneError('This video could not be read. Check the drive connection.', 422)
    data = json.loads(result.stdout)
    streams = data.get('streams', [])
    video = next((row for row in streams if row.get('codec_type') == 'video' and not row.get('disposition', {}).get('attached_pic')), None)
    if not video:
        raise PhoneError('This file has no playable video.', 422)
    duration = float(data.get('format', {}).get('duration') or video.get('duration') or 0)
    if not math.isfinite(duration) or duration <= 0:
        raise PhoneError('This video has no readable duration.', 422)
    return {'duration': duration, 'video': video,
            'audio': [row for row in streams if row.get('codec_type') == 'audio'],
            'subtitles': [row for row in streams if row.get('codec_type') == 'subtitle'],
            'sidecars': find_sidecar_subtitles(path),
            'fonts': [row for row in streams if row.get('codec_type') == 'attachment'
                      and row.get('codec_name') in {'ttf', 'otf'} and int(row.get('extradata_size', 0)) <= 10*1024**2][:16]}


def playback_plan(path, info, audio_index=0, subtitle='off', compatible=False):
    video = info['video']; codec = video.get('codec_name')
    audio = info['audio']
    if audio_index < 0 or audio_index >= max(1, len(audio)):
        raise PhoneError('Choose an available audio track.')
    selected_audio = audio[audio_index] if audio else None
    safe_video = (codec == 'h264' and video.get('pix_fmt') == 'yuv420p' and int(video.get('level', 0)) <= 52)
    safe_video = safe_video or (codec == 'hevc' and video.get('pix_fmt') in {'yuv420p', 'yuv420p10le'}
                                and video.get('codec_tag_string') == 'hvc1')
    burn = None
    if subtitle != 'off':
        match = re.fullmatch(r'(sidecar|embedded):(\d+)', subtitle)
        if not match:
            raise PhoneError('Choose an available subtitle track.')
        kind, index = match.group(1), int(match.group(2))
        collection = info['sidecars'] if kind == 'sidecar' else info['subtitles']
        if index >= len(collection):
            raise PhoneError('Choose an available subtitle track.')
        if kind == 'embedded' and collection[index].get('codec_name') not in {'ass', 'ssa', 'subrip', 'webvtt', 'mov_text'}:
            raise PhoneError('This image-based subtitle track is not supported by Phone access yet. Choose a text track.', 422)
        burn = (kind, index)
    direct = (not compatible and not burn and audio_index == 0 and path.suffix.lower() in {'.mp4', '.m4v', '.mov'}
              and safe_video and (not selected_audio or selected_audio.get('codec_name') == 'aac'))
    return {'mode': 'direct' if direct else 'hls', 'copy_video': safe_video and not compatible and not burn,
            'audio': selected_audio, 'burn': burn}


class PhoneServer:
    def __init__(self, database, library_root, data_root, *, addresses=('127.0.0.1',), port=8766, host='0.0.0.0'):
        self.database = Path(database)
        self.library_root = Path(library_root).resolve()
        self.addresses = tuple(dict.fromkeys(('127.0.0.1', *addresses)))
        self.lock = threading.RLock()
        self.sessions = {}
        self.pair_attempts = {}
        self.streams = {}
        self.last_connection = 0
        self.stopping = threading.Event()
        self.refresh_pairing()
        cache = Path(data_root) / 'phone-streams'; cache.mkdir(parents=True, exist_ok=True)
        self.cache = tempfile.TemporaryDirectory(prefix='phone-', dir=cache, ignore_cleanup_errors=True)
        self.http = _Server((host, port), _Handler)
        self.http.companion = self
        self.port = self.http.server_port
        self.thread = threading.Thread(target=self.http.serve_forever, kwargs={'poll_interval': .2}, daemon=True)
        self.thread.start()
        self.janitor = threading.Thread(target=self._maintain, daemon=True); self.janitor.start()

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def refresh_pairing(self):
        with self.lock:
            self.pair_key = secrets.token_urlsafe(24)
            self.pair_code = f'{secrets.randbelow(100000000):08d}'
            self.pair_expires = time.monotonic() + 600

    def url(self, address):
        return f'http://{address}:{self.port}/#pair={self.pair_key}'

    def pair(self, key, peer='local'):
        with self.lock:
            now = time.monotonic()
            self.pair_attempts = {ip: attempts for ip, attempts in self.pair_attempts.items() if attempts[-1] > now-60}
            attempts = self.pair_attempts.get(peer, [])
            if len(attempts) >= 5: raise PhoneError('Too many pairing attempts. Wait one minute and try the current code.', 429)
            key = str(key).replace(' ', '')
            if not key.isascii(): raise PhoneError('Use the pairing code shown on the Ally.', 403)
            if now > self.pair_expires or not (secrets.compare_digest(key, self.pair_key) or secrets.compare_digest(key, self.pair_code)):
                if len(self.pair_attempts) < 256 or peer in self.pair_attempts:
                    self.pair_attempts[peer] = [*attempts, now]
                raise PhoneError('Pairing code expired or incorrect. Refresh the QR code in Settings.', 403)
            self._expire_sessions()
            if len(self.sessions) >= 4:
                raise PhoneError('Four devices are already paired. Stop and restart Phone access to clear them.', 429)
            sid = secrets.token_urlsafe(32)
            self.sessions[sid] = {'csrf': secrets.token_urlsafe(24), 'expires': time.monotonic() + 86400}
            self.last_connection = time.time()
            return sid, self.sessions[sid]['csrf']

    def _expire_sessions(self):
        for sid in list(self.sessions):
            if self.sessions[sid]['expires'] < time.monotonic():
                del self.sessions[sid]

    def session(self, cookie):
        jar = SimpleCookie()
        try:
            jar.load(cookie or '')
            sid = jar['aw_phone'].value if 'aw_phone' in jar else ''
        except Exception:
            sid = ''
        with self.lock:
            self._expire_sessions()
            if sid not in self.sessions:
                raise PhoneError('Scan the pairing QR code in Anime Watcher Settings.', 401)
            self.last_connection = time.time()
            return sid, self.sessions[sid]

    def episode(self, episode_id):
        with self.db() as db:
            row = db.execute('SELECT * FROM episodes WHERE id=?', (int(episode_id),)).fetchone()
        if not row:
            raise PhoneError('This video is no longer in the library.', 404)
        path = Path(row['path']).resolve()
        if not path.is_relative_to(self.library_root) or not path.is_file():
            raise PhoneError('Video unavailable. Check the external drive and refresh Library.', 404)
        return row, path

    def catalog(self):
        with self.db() as db:
            series = [dict(row) for row in db.execute('''SELECT s.id,COALESCE(s.display_title,s.title) title,
                s.synopsis,s.release_year year,s.library_type,COUNT(DISTINCT e.season*10000+e.episode) episode_count
                FROM series s JOIN episodes e ON e.series_id=s.id GROUP BY s.id ORDER BY title COLLATE NOCASE''')]
        return series

    def episodes(self, series_id):
        with self.db() as db:
            return [dict(row) for row in db.execute('''SELECT id,season,episode,title,language,progress_ms,duration_ms,completed
                FROM episodes WHERE series_id=? ORDER BY season,episode,language,path''', (int(series_id),))]

    def artwork(self, series_id):
        with self.db() as db:
            row = db.execute('SELECT poster_path FROM series WHERE id=?', (int(series_id),)).fetchone()
        path = Path(row['poster_path']) if row and row['poster_path'] else None
        if not path or not path.is_file() or path.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
            raise PhoneError('Artwork unavailable.', 404)
        return path

    def media_info(self, episode_id):
        row, path = self.episode(episode_id)
        info = inspect_media(path)
        def label(track, index):
            tags = track.get('tags', {})
            return tags.get('title') or tags.get('language') or f'Track {index + 1}'
        return {'duration': info['duration'], 'position': min(row['progress_ms'] / 1000, info['duration']),
                'audio': [{'id': index, 'label': label(track, index)} for index, track in enumerate(info['audio'])],
                'subtitles': ([{'id': f'embedded:{index}', 'label': label(track, index)} for index, track in enumerate(info['subtitles'])]
                              + [{'id': f'sidecar:{index}', 'label': path.name} for index, path in enumerate(info['sidecars'])])}

    def play(self, sid, payload):
        generation = int(payload.get('generation', 0))
        with self.lock:
            session = self.sessions[sid]
            if generation < session.get('generation', 0): raise PhoneError('Playback request superseded.', 409)
            session['generation'] = generation
        episode_id = int(payload['episode'])
        row, path = self.episode(episode_id)
        info = inspect_media(path)
        offset = float(payload.get('offset', row['progress_ms'] / 1000))
        if not math.isfinite(offset) or not 0 <= offset < info['duration']:
            offset = 0
        plan = playback_plan(path, info, int(payload.get('audio', 0)), str(payload.get('subtitle', 'off')),
                             bool(payload.get('compatible', False)))
        with self.lock:
            if self.stopping.is_set(): raise PhoneError('Phone access has stopped.', 503)
            if sid not in self.sessions or generation != session['generation']: raise PhoneError('Playback request superseded.', 409)
            self.stop_playback(sid)
            if len(self.streams) >= 2:
                raise PhoneError('Two phones are already playing. Stop one before starting another.', 429)
            stream_id = secrets.token_hex(16)
            folder = Path(self.cache.name) / stream_id; folder.mkdir()
            record = {'owner': sid, 'episode': episode_id, 'path': path, 'duration': info['duration'],
                      'offset': offset, 'mode': plan['mode'], 'folder': folder, 'process': None,
                      'last_used': time.monotonic(), 'error': '', 'stat': (path.stat().st_size, path.stat().st_mtime_ns)}
            if plan['mode'] == 'hls':
                try:
                    self._start_hls(record, info, plan)
                except Exception:
                    shutil.rmtree(folder, ignore_errors=True)
                    raise
            self.streams[stream_id] = record
        suffix = 'video' if plan['mode'] == 'direct' else 'index.m3u8'
        return {'id': stream_id, 'url': f'/media/{stream_id}/{suffix}', 'mode': plan['mode'],
                'offset': offset, 'duration': info['duration'],
                'label': 'Original quality' if plan['mode'] == 'direct' else 'Original video · compatible audio' if plan['copy_video'] else 'Compatible stream · up to 1080p'}

    def _start_hls(self, record, info, plan):
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            raise PhoneError('The media tools are missing. Reinstall the current Windows release.', 503)
        folder = record['folder']; path = record['path']
        # Safe filter paths are generated inside the private cache, never interpolated from user paths.
        filters = []
        if plan['burn']:
            kind, index = plan['burn']
            if kind == 'sidecar':
                subtitle = info['sidecars'][index]
                copied = folder / ('captions' + subtitle.suffix.lower()); shutil.copy2(subtitle, copied)
            else:
                copied = folder / 'captions.ass'
                result = subprocess.run([ffmpeg, '-v', 'error', '-nostdin', '-y', '-i', str(path),
                                         '-map', f'0:s:{index}', '-c:s', 'ass', str(copied)],
                    capture_output=True, timeout=20, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if result.returncode: raise PhoneError('This subtitle track could not be prepared.', 422)
            fonts_out = folder / 'fonts'; fonts_out.mkdir()
            fonts = [*path.parent.glob('*.ttf'), *path.parent.glob('*.otf')]
            for directory in (path.parent / 'Fonts', path.parent / 'fonts'):
                if directory.is_dir(): fonts.extend(directory.iterdir())
            for number, font in enumerate(dict.fromkeys(fonts)):
                if number < 100 and font.is_file() and font.suffix.lower() in {'.ttf', '.otf', '.ttc'} and font.stat().st_size < 10*1024**2:
                    shutil.copy2(font, fonts_out / f'font-{number}{font.suffix.lower()}')
            if info.get('fonts'):
                dump = []
                for number, font in enumerate(info['fonts']):
                    dump += [f"-dump_attachment:{font['index']}", str(fonts_out / f"embedded-{number}.{font['codec_name']}")]
                subprocess.run([ffmpeg, '-v', 'error', '-nostdin', '-y', *dump, '-i', str(path),
                                '-t', '0', '-f', 'null', '-'], capture_output=True, timeout=20,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            filters.append(f"subtitles=filename='{copied.name}':fontsdir=fonts")
        if not plan['copy_video']:
            filters.append("scale=w='min(1920,iw)':h='min(1080,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2")
        command = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-threads', '2']
        # Read subtitle timestamps from the original timeline before cutting output at the resume position.
        command += ['-ss', str(record['offset'])]
        command += ['-readrate', '2', '-i', str(path), '-map', f"0:{info['video']['index']}"]
        if plan['audio']:
            command += ['-map', f"0:{plan['audio']['index']}"]
        if plan['burn']:
            # Input seeking keeps startup fast; restore the original time for subtitle lookup.
            filters = [f"setpts=PTS+{record['offset']}/TB", *filters, 'setpts=PTS-STARTPTS']
        if filters:
            command += ['-vf', ','.join(filters)]
        if plan['copy_video']:
            command += ['-c:v', 'copy']
            if info['video'].get('codec_name') == 'hevc': command += ['-tag:v', 'hvc1']
        else:
            command += ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p',
                        '-threads', '2', '-force_key_frames', 'expr:gte(t,n_forced*2)']
        command += ['-c:a', 'aac', '-b:a', '192k', '-ac', '2', '-sn', '-f', 'hls', '-hls_time', '4',
                    '-hls_playlist_type', 'event', '-hls_segment_type', 'fmp4', '-hls_flags', 'temp_file+independent_segments',
                    '-hls_segment_filename', 'segment-%06d.m4s', 'index.m3u8']
        log = (folder / 'ffmpeg.log').open('wb')
        try:
            record['process'] = subprocess.Popen(command, cwd=folder, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        finally:
            log.close()

    def stream(self, sid, stream_id):
        with self.lock:
            record = self.streams.get(stream_id)
            if not record or record['owner'] != sid:
                raise PhoneError('Playback expired. Open the episode again.', 404)
            record['last_used'] = time.monotonic()
            try:
                stat = record['path'].stat()
                if (stat.st_size, stat.st_mtime_ns) != record['stat']:
                    raise OSError('Video changed')
            except OSError:
                raise PhoneError('The video changed or the drive was disconnected. Refresh Library.', 409)
            process = record['process']
            if process and process.poll() not in {None, 0}:
                record['error'] = 'Compatibility streaming failed. Try another subtitle/audio track or restart the episode.'
            return record

    def status(self, sid, stream_id):
        record = self.stream(sid, stream_id)
        ready = record['mode'] == 'direct' or (record['folder'] / 'index.m3u8').is_file()
        return {'ready': ready, 'error': record['error']}

    def progress(self, sid, payload):
        record = self.stream(sid, str(payload['stream']))
        position = float(payload['position'])
        if not math.isfinite(position) or not 0 <= position <= record['duration'] + 2:
            raise PhoneError('Invalid playback position.')
        progress = min(round(position * 1000), round(record['duration'] * 1000))
        duration = round(record['duration'] * 1000)
        completed = int(progress / duration >= .9 or duration - progress < 120000)
        with self.db() as db:
            db.execute("UPDATE episodes SET progress_ms=?,duration_ms=?,completed=?,last_watched=datetime('now','localtime') WHERE id=?",
                       (progress, duration, completed, record['episode']))
            db.commit()

    def stop_playback(self, sid):
        with self.lock:
            for stream_id, record in list(self.streams.items()):
                if record['owner'] == sid:
                    self._remove_stream(stream_id)

    def _remove_stream(self, stream_id):
        record = self.streams.pop(stream_id)
        process = record['process']
        if process and process.poll() is None:
            try: process.terminate()
            except OSError: pass
            try: process.wait(timeout=3)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=3)
        shutil.rmtree(record['folder'], ignore_errors=True)

    def _maintain(self):
        while not self.stopping.wait(5):
            with self.lock:
                self._expire_sessions()
                for stream_id, record in list(self.streams.items()):
                    if record['owner'] not in self.sessions or time.monotonic() - record['last_used'] > 120:
                        self._remove_stream(stream_id)
                    else:
                        size = 0
                        for path in record['folder'].glob('*'):
                            try:
                                if path.is_file(): size += path.stat().st_size
                            except OSError: pass  # FFmpeg atomically renames temporary segments.
                        if size > 1024**3:
                            record['error'] = 'Streaming cache is full. Restart playback from your current position.'
                            process = record['process']
                            if process and process.poll() is None:
                                try: process.terminate()
                                except OSError: pass

    def stop(self):
        self.stopping.set()
        self.http.shutdown(); self.http.server_close()
        with self.http.requests_lock:
            for connection in list(self.http.connections):
                try: connection.shutdown(socket.SHUT_RDWR)
                except OSError: pass
        self.thread.join(timeout=3); self.janitor.join(timeout=3)
        with self.lock:
            for stream_id in list(self.streams): self._remove_stream(stream_id)
            self.sessions.clear()
        self.cache.cleanup()


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 16
    def __init__(self, *args):
        self.slots = threading.BoundedSemaphore(16)
        self.requests_lock = threading.Lock()
        self.connections = set()
        super().__init__(*args)
    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request); return
        with self.requests_lock: self.connections.add(request)
        try: super().process_request(request, address)
        except Exception:
            with self.requests_lock: self.connections.discard(request)
            self.slots.release()
            raise
    def process_request_thread(self, request, address):
        try: super().process_request_thread(request, address)
        finally:
            with self.requests_lock: self.connections.discard(request)
            self.slots.release()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *_args):
        pass  # Pairing tokens, filenames, and browser requests stay out of logs.
    def setup(self):
        super().setup(); self.connection.settimeout(20)
    def _headers(self, status, kind, length, extra=()):
        self.responded = True
        self.send_response(status)
        for key, value in [('Content-Type', kind), ('Content-Length', str(length)), ('Cache-Control', 'no-store'),
                           ('X-Content-Type-Options', 'nosniff'), ('Referrer-Policy', 'no-referrer'),
                           ('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"), *extra]:
            self.send_header(key, value)
        self.end_headers()
    def _json(self, status, data, extra=()):
        value = json.dumps(data, ensure_ascii=False).encode()
        self._headers(status, 'application/json; charset=utf-8', len(value), extra)
        if self.command != 'HEAD': self.wfile.write(value)
    def _file(self, path, kind=None):
        with path.open('rb') as handle:
            size = path.stat().st_size
            try: start, end, partial = byte_range(self.headers.get('Range'), size)
            except PhoneError:
                self._headers(416, 'text/plain', 0, [('Content-Range', f'bytes */{size}')]); return
            headers = [('Accept-Ranges', 'bytes')]
            if partial: headers.append(('Content-Range', f'bytes {start}-{end}/{size}'))
            self._headers(206 if partial else 200, kind or mimetypes.guess_type(path.name)[0] or 'application/octet-stream', max(0, end-start+1), headers)
            if self.command == 'HEAD': return
            handle.seek(start); remaining = end-start+1
            while remaining > 0 and not self.server.companion.stopping.is_set():
                chunk = handle.read(min(256*1024, remaining))
                if not chunk: break
                self.wfile.write(chunk); remaining -= len(chunk)
    def _check_host(self):
        app = self.server.companion
        if app.stopping.is_set(): raise PhoneError('Phone access has stopped.', 503)
        peer = ipaddress.ip_address(self.client_address[0])
        if not (peer.is_private or peer.is_loopback):
            raise PhoneError('Phone access is available only on your local network.', 403)
        host = self.headers.get('Host', '')
        if host not in {f'{address}:{app.port}' for address in app.addresses}:
            raise PhoneError('Use the address shown in Anime Watcher Settings.', 403)
        if self.command == 'POST':
            origin = self.headers.get('Origin')
            if origin and origin != f'http://{host}': raise PhoneError('Invalid request origin.', 403)
            if self.headers.get('Sec-Fetch-Site') == 'cross-site': raise PhoneError('Invalid request origin.', 403)
    def _body(self):
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            raise PhoneError('Send a JSON request.', 415)
        length = int(self.headers.get('Content-Length', 0))
        if not 0 < length <= 8192: raise PhoneError('Invalid request size.', 413)
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict): raise PhoneError('Invalid request.')
        return data
    def do_GET(self): self._dispatch()
    def do_HEAD(self): self._dispatch()
    def do_POST(self): self._dispatch()
    def _dispatch(self):
        self.responded = False
        try:
            self._check_host()
            app = self.server.companion
            route = urlsplit(self.path).path
            assets = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css', '/manifest.webmanifest': 'manifest.webmanifest', '/icon.svg': 'icon.svg', '/icon.png': 'icon.png'}
            if self.command in {'GET', 'HEAD'} and route in assets:
                return self._file(resource_path('assets', 'phone', assets[route]))
            if self.command == 'POST' and route == '/api/pair':
                sid, csrf = app.pair(self._body().get('key', ''), self.client_address[0])
                return self._json(200, {'csrf': csrf}, [('Set-Cookie', f'aw_phone={sid}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400')])
            sid, session = app.session(self.headers.get('Cookie'))
            if self.command == 'POST':
                if not secrets.compare_digest(self.headers.get('X-Phone-CSRF', ''), session['csrf']):
                    raise PhoneError('Invalid request token. Reload the page.', 403)
                data = self._body()
                if route == '/api/play': return self._json(200, app.play(sid, data))
                if route == '/api/progress': app.progress(sid, data); return self._json(200, {'saved': True})
                if route == '/api/stop':
                    with app.lock:
                        session['generation'] = max(session.get('generation', 0), int(data.get('generation', 0)))
                        app.stop_playback(sid)
                    return self._json(200, {'stopped': True})
                raise PhoneError('Unknown action.', 404)
            if route == '/api/session': return self._json(200, {'csrf': session['csrf'], 'generation': session.get('generation', 0)})
            if route == '/api/library': return self._json(200, app.catalog())
            match = re.fullmatch(r'/api/series/(\d+)', route)
            if match: return self._json(200, app.episodes(int(match.group(1))))
            match = re.fullmatch(r'/api/info/(\d+)', route)
            if match: return self._json(200, app.media_info(int(match.group(1))))
            match = re.fullmatch(r'/api/status/([a-f0-9]{32})', route)
            if match: return self._json(200, app.status(sid, match.group(1)))
            match = re.fullmatch(r'/art/(\d+)', route)
            if match: return self._file(app.artwork(int(match.group(1))))
            match = re.fullmatch(r'/media/([a-f0-9]{32})/(video|index.m3u8|init.mp4|segment-\d{6}.m4s)', route)
            if match:
                record = app.stream(sid, match.group(1)); filename = match.group(2)
                if record['mode'] == 'direct' and filename == 'video': return self._file(record['path'], 'video/mp4')
                path = record['folder'] / filename
                if path.is_file():
                    return self._file(path, 'application/vnd.apple.mpegurl' if filename.endswith('.m3u8') else 'video/mp4')
                raise PhoneError('The stream is preparing. Please wait.', 503)
            raise PhoneError('Not found.', 404)
        except PhoneError as exc:
            self.close_connection = True
            if not self.responded: self._json(exc.status, {'error': str(exc)})
        except (BrokenPipeError, ConnectionResetError, TimeoutError, socket.timeout):
            self.close_connection = True
        except (ValueError, KeyError, TypeError, OSError, sqlite3.Error, subprocess.SubprocessError):
            self.close_connection = True
            if not self.responded: self._json(400, {'error': 'The request could not be completed. Check the drive connection and try again.'})
