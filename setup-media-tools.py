"""Fetch the pinned upstream portable FFmpeg tools used by Windows releases."""
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
URL = 'https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-8.1.2-essentials_build.zip'
SHA256 = 'db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec'


def main():
    staging = ROOT / '.test-tmp'; staging.mkdir(exist_ok=True)
    archive = staging / 'ffmpeg-8.1.2-essentials.zip'
    if not archive.exists() or hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest() != SHA256:
        request = urllib.request.Request(URL, headers={'User-Agent': 'AnimeWatcher-build'})
        with urllib.request.urlopen(request, timeout=60) as response, archive.open('wb') as output:
            while chunk := response.read(1024 * 1024): output.write(chunk)
    if hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest() != SHA256:
        raise ValueError('The media-tools archive failed SHA-256 verification.')
    destination = ROOT / 'third_party' / 'ffmpeg'; (destination / 'bin').mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as package:
        for relative in ('bin/ffmpeg.exe', 'bin/ffprobe.exe', 'LICENSE', 'README.txt'):
            matches = [name for name in package.namelist() if name.endswith('/' + relative)]
            if len(matches) != 1: raise ValueError('Unexpected media-tools archive layout.')
            (destination / relative).write_bytes(package.read(matches[0]))
    manifest = {'version': '8.1.2-essentials', 'url': URL, 'archive_sha256': SHA256, 'license': 'GPL-3.0-or-later',
                'source_information': 'README.txt contains the exact upstream FFmpeg commit and external-library versions.',
                'files': {name: hashlib.file_digest((destination / 'bin' / name).open('rb'), 'sha256').hexdigest()
                          for name in ('ffmpeg.exe', 'ffprobe.exe')}}
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print('Verified and prepared FFmpeg 8.1.2 portable media tools.')


if __name__ == '__main__': main()
