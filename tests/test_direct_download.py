import io
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from anime_watcher.downloader import download_authorized_file


class Response(io.BytesIO):
    def __init__(self, payload, total=None, filename='Show.S01E01.mp4', url='https://example.com/video.mp4'):
        super().__init__(payload)
        self.url=url
        self.headers={'Content-Length':str(total if total is not None else len(payload)),
                      'Content-Disposition':f'attachment; filename="{filename}"'}

    def geturl(self):
        return self.url


class DirectDownloadTests(unittest.TestCase):
    def test_cancel_keeps_partial_and_does_not_import(self):
        cancel=threading.Event()
        with tempfile.TemporaryDirectory() as tmp,patch('urllib.request.urlopen',return_value=Response(b'x'*2000000)),patch('anime_watcher.downloader.organize_file') as organize:
            with self.assertRaisesRegex(RuntimeError,'cancelled'):
                download_authorized_file('https://example.com/video.mp4',tmp,Path(tmp)/'library',lambda *_:cancel.set(),cancel=cancel)
            self.assertGreater((Path(tmp)/'Show.S01E01.mp4.part').stat().st_size,0)
            organize.assert_not_called()

    def test_truncated_response_is_kept_as_partial(self):
        with tempfile.TemporaryDirectory() as tmp,patch('urllib.request.urlopen',return_value=Response(b'short',total=2000)),patch('anime_watcher.downloader.organize_file') as organize:
            with self.assertRaisesRegex(RuntimeError,'ended early'):
                download_authorized_file('https://example.com/video.mp4',tmp,Path(tmp)/'library')
            self.assertEqual((Path(tmp)/'Show.S01E01.mp4.part').read_bytes(),b'short')
            organize.assert_not_called()

    def test_server_filename_cannot_escape_download_directory(self):
        with tempfile.TemporaryDirectory() as tmp,patch('urllib.request.urlopen',return_value=Response(b'video',filename='../Show.S01E01.mp4')),patch('anime_watcher.downloader.organize_file') as organize:
            folder=Path(tmp)/'download'
            download_authorized_file('https://example.com/video.mp4',folder,Path(tmp)/'library')
            self.assertEqual(organize.call_args.args[0],folder/'Show.S01E01.mp4')
            self.assertFalse((Path(tmp)/'Show.S01E01.mp4').exists())

    def test_credentials_and_non_http_redirects_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'username or password'):
                download_authorized_file('https://user:' + 'secret@' + 'example.com/video.mp4',tmp,Path(tmp)/'library')
            with patch('urllib.request.urlopen',return_value=Response(b'video',url='file:///C:/secret.mp4')):
                with self.assertRaisesRegex(ValueError,'HTTP'):
                    download_authorized_file('https://example.com/video.mp4',tmp,Path(tmp)/'library')


if __name__=='__main__':unittest.main()
