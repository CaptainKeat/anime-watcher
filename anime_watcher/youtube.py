from __future__ import annotations

import re
import json
import shutil
import threading
import urllib.parse
from pathlib import Path
from typing import Callable
from uuid import uuid4

from .organizer import VIDEO_EXTENSIONS, MoveResult, organize_file
from .preview import find_ffmpeg
from .youtube_library import read_youtube_metadata, youtube_destination, youtube_metadata_path


QUALITIES = {"best": None, "1080p": 1080, "720p": 720, "480p": 480}


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

    def report(received=0, total=0, stage="Connecting to YouTube…"):
        check_cancel()
        if progress:
            progress(int(received or 0), int(total or 0), stage)

    def hook(data):
        info = data.get("info_dict") or {}
        if metadata_callback and info.get("title") and info.get("title") != metadata.get("title"):
            metadata["title"] = str(info["title"])
            metadata_callback({"title": str(info["title"])})
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
                        metadata.update({key: str(info.get(key) or "") for key in ("id", "title", "channel_id", "channel")})
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
    destination = youtube_destination(video, Path(library_root), metadata, library_series or [], target_title, season, episode)
    # A previously imported ID is already present even if YouTube now offers
    # different bytes/quality. Keep its existing slot and watched progress.
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
            # A failed metadata move must not leave a newly imported file whose
            # channel identity was lost. Retain the complete attempt for retry.
            if result.destination != video and not video.exists():
                shutil.move(str(result.destination), str(video))
            raise
    # Only remove an empty successful attempt directory. Failed/duplicate files remain available.
    try:
        job_dir.rmdir()
    except OSError:
        pass
    return result
