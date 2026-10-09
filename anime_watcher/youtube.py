from __future__ import annotations

import re
import json
import hashlib
import shutil
import threading
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable
from uuid import uuid4

from .organizer import VIDEO_EXTENSIONS, MoveResult, organize_file
from .preview import find_ffmpeg
from .youtube_library import read_youtube_metadata, youtube_destination, youtube_metadata_path


QUALITIES = {"best": None, "1080p": 1080, "720p": 720, "480p": 480}
_IMPORT_LOCK = threading.Lock()


def _thumbnail_address(url):
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if (parsed.scheme != "https" or parsed.username or parsed.password or
            parsed.port not in {None, 443} or not (host == "ytimg.com" or host.endswith(".ytimg.com"))):
        raise ValueError("Unsupported YouTube thumbnail address")
    return url


class _ThumbnailRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        _thumbnail_address(newurl)
        return super().redirect_request(request, fp, code, message, headers, newurl)


def fetch_youtube_thumbnail(url: str, cache_dir: str | Path) -> str:
    """Cache optional video artwork independently of the video transfer."""
    _thumbnail_address(url)
    directory = Path(cache_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (hashlib.sha256(url.encode()).hexdigest() + ".img")
    if target.is_file():
        return str(target)
    temporary = directory / (target.name + "." + uuid4().hex + ".download")
    request = urllib.request.Request(url, headers={"User-Agent": "AnimeWatcher/1.0"})
    try:
        with urllib.request.build_opener(_ThumbnailRedirect()).open(request, timeout=15) as response:
            _thumbnail_address(response.geturl())
            if not response.headers.get_content_type().startswith("image/"):
                raise ValueError("YouTube thumbnail did not return an image")
            data = response.read(5 * 1024 * 1024 + 1)
            if not data or len(data) > 5 * 1024 * 1024:
                raise ValueError("YouTube thumbnail is empty or too large")
            temporary.write_bytes(data)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return str(target)


class DownloadCancelled(Exception):
    pass


def youtube_video_url(value: str) -> str:
    """Accept one video, discarding playlist and tracking parameters."""
    parsed = urllib.parse.urlparse(value.strip())
    if parsed.scheme not in {"https", "http"} or parsed.username or parsed.password:
        raise ValueError("Paste a complete YouTube video or Shorts link.")
    host = (parsed.hostname or "").lower()
    if host == "youtu.be":
        video_id = parsed.path.strip("/")
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        if parsed.path == "/watch":
            video_id = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
        else:
            match = re.fullmatch(r"/(?:shorts|embed|live)/([\w-]+)/*", parsed.path)
            video_id = match.group(1) if match else ""
    else:
        video_id = ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("Use a single YouTube video or Shorts link, rather than a channel or playlist.")
    return f"https://www.youtube.com/watch?v={video_id}"


def _format_selector(quality: str, ffmpeg: str | None) -> str:
    if quality not in QUALITIES:
        raise ValueError("Choose Best available, 1080p, 720p, or 480p.")
    height = QUALITIES[quality]
    limit = f"[height<={height}]" if height else ""
    # Prefer MP4 video and M4A audio for Qt playback, with other formats as a fallback.
    combined = f"b[ext=mp4]{limit}/b{limit}"
    if not ffmpeg:
        return combined
    return f"bv*[ext=mp4]{limit}+ba[ext=m4a]/bv*{limit}+ba/{combined}"


def youtube_playlist_url(value: str) -> str:
    parsed = urllib.parse.urlparse(value.strip())
    host = (parsed.hostname or '').lower()
    playlist = urllib.parse.parse_qs(parsed.query).get('list', [''])[0]
    if (parsed.scheme not in {'https', 'http'} or parsed.username or parsed.password or parsed.port not in {None, 80, 443}
            or host not in {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be'}
            or not re.fullmatch(r'[A-Za-z0-9_-]{10,150}', playlist)):
        raise ValueError('Paste a public YouTube playlist link containing list=…')
    return 'https://www.youtube.com/playlist?list=' + playlist


def preview_youtube_playlist(value: str):
    """List public entries without downloading videos or following arbitrary URLs."""
    from yt_dlp import YoutubeDL
    url = youtube_playlist_url(value)
    options = dict(extract_flat='in_playlist', skip_download=True, ignoreerrors=True, quiet=True,
                   logger=_QuietLogger(), socket_timeout=15, retries=1, extractor_retries=1,
                   playlistend=500)
    with YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=False)
    if not info or info.get('_type') not in {'playlist', 'multi_video'}:
        raise ValueError('No readable public playlist was found.')
    videos, seen, skipped = [], set(), 0
    for entry in info.get('entries') or []:
        if not entry or entry.get('availability') in {'private', 'premium_only', 'subscriber_only', 'needs_auth'} or _reject_live(entry):
            skipped += 1; continue
        identifier = str(entry.get('id') or '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}', identifier) or identifier in seen:
            skipped += 1; continue
        if str(entry.get('title') or '') in {'[Private video]', '[Deleted video]'}:
            skipped += 1; continue
        seen.add(identifier)
        videos.append(dict(title=str(entry.get('title') or identifier), url=f'https://www.youtube.com/watch?v={identifier}'))
    if not videos:
        raise ValueError('This playlist has no available videos.')
    return dict(title=str(info.get('title') or 'YouTube playlist'), videos=videos, skipped=skipped,
                limited=len(info.get('entries') or []) >= 500)


def _reject_live(info, *, incomplete=False):
    if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming"}:
        return "This video is live or upcoming. Download it after the broadcast finishes."
    return None


class _QuietLogger:
    def debug(self, message):
        pass

    info = debug
    warning = debug
    error = debug


def download_youtube_video(
    url: str,
    download_dir: str | Path,
    library_root: str | Path,
    quality: str = "best",
    cancel: threading.Event | None = None,
    progress: Callable[[int, int, str], None] | None = None,
    *,
    library_series: list[dict] | None = None,
    target_title: str | None = None,
    season: int | None = None,
    episode: int | None = None,
    metadata_callback: Callable[[dict], None] | None = None,
):
    url = youtube_video_url(url)
    cancel = cancel if cancel is not None else threading.Event()

    def check_cancel():
        if cancel.is_set():
            raise DownloadCancelled("Download cancelled. Partial files are kept in Downloads.")

    check_cancel()
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("YouTube support is missing. Install the app's requirements and rebuild it.") from exc

    ffmpeg = find_ffmpeg()
    selector = _format_selector(quality, ffmpeg)
    # Each attempt has its own directory, preserving failures and preventing collisions.
    job_dir = Path(download_dir).resolve() / f"youtube-{uuid4().hex}"
    job_dir.mkdir(parents=True, exist_ok=False)
    downloaded: list[Path] = []
    metadata = {}

    def record_metadata(info):
        values = {key: str(info[key]) for key in
                  ("id", "title", "channel_id", "channel", "thumbnail", "upload_date", "description")
                  if info.get(key)}
        changed = any(metadata.get(key) != value for key, value in values.items())
        metadata.update(values)
        if changed and metadata_callback:
            metadata_callback(dict(metadata))

    def report(received=0, total=0, stage="Connecting to YouTube…"):
        check_cancel()
        if progress:
            progress(int(received or 0), int(total or 0), stage)

    def hook(data):
        info = data.get("info_dict") or {}
        record_metadata(info)
        if data.get("status") == "downloading":
            report(data.get("downloaded_bytes"), data.get("total_bytes") or data.get("total_bytes_estimate"), "Downloading…")
        else:
            report(stage="Preparing video…")

    def post_hook(data):
        check_cancel()
        report(stage="Preparing video…")

    options = {
        "format": selector,
        "outtmpl": str(job_dir / "%(title).150B [%(id)s].%(ext)s"),
        "windowsfilenames": True,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "logger": _QuietLogger(),
        "socket_timeout": 20,
        "retries": 3,
        "fragment_retries": 3,
        "overwrites": False,
        "cachedir": False,
        "match_filter": _reject_live,
        "progress_hooks": [hook],
        "postprocessor_hooks": [post_hook],
        "merge_output_format": "mp4/mkv",
    }
    if ffmpeg:
        options["ffmpeg_location"] = ffmpeg
    # Current yt-dlp needs a JS runtime; use an existing Deno or Node installation.
    runtimes = {}
    for name in ("deno", "node"):
        executable = shutil.which(name)
        if executable:
            runtimes[name] = {"path": executable}
    if runtimes:
        options["js_runtimes"] = runtimes

    report(stage="Connecting to YouTube…" if ffmpeg else "Connecting… (combined video/audio; FFmpeg is unavailable)")
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            # Record the final path AFTER merging, never an intermediate audio/video stream.
            class FinalPath(yt_dlp.postprocessor.PostProcessor):
                def run(self, info):
                    check_cancel()
                    if info.get("filepath"):
                        downloaded.append(Path(info["filepath"]))
                        record_metadata(info)
                        metadata["url"] = url
                    return [], info

            downloader.add_post_processor(FinalPath(), when="after_move")
            downloader.extract_info(url, download=True)
    except Exception as exc:
        check_cancel()
        raise RuntimeError(f"YouTube download failed: {exc}") from exc

    check_cancel()
    if len(downloaded) != 1:
        raise RuntimeError("YouTube did not return one completed video. It may be live or unavailable.")
    video = downloaded[0].resolve()
    if not video.is_relative_to(job_dir) or video.suffix.lower() not in VIDEO_EXTENSIONS or not video.is_file() or not video.stat().st_size:
        raise RuntimeError("YouTube did not produce a complete supported video file.")
    report(stage="Adding to your library…")
    # Transfers can overlap, but slot allocation and bundle moves must agree
    # on files already imported by another video, even before GUI indexing.
    with _IMPORT_LOCK:
        check_cancel()
        destination = youtube_destination(video, Path(library_root), metadata, library_series or [], target_title, season, episode)
        if destination.is_file() and metadata.get("id") and read_youtube_metadata(destination).get("id") == metadata["id"]:
            return MoveResult(video, destination, "duplicate", "This YouTube video is already in your library")
        source_metadata = youtube_metadata_path(video)
        source_metadata.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        result = organize_file(video, library_root, destination=destination)
        if result.destination is None:
            raise RuntimeError("The downloaded video could not be added to your library.")
        if result.status != "duplicate":
            try:
                shutil.move(str(source_metadata), str(youtube_metadata_path(result.destination)))
            except Exception:
                # Retain the complete attempt if its channel identity cannot move.
                if result.destination != video and not video.exists():
                    shutil.move(str(result.destination), str(video))
                raise
    # Only remove an empty successful attempt directory. Failed/duplicate files remain available.
    try:
        job_dir.rmdir()
    except OSError:
        pass
    return result
