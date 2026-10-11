from __future__ import annotations

import re
import json
import hashlib
import http.cookiejar
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
BROWSER_SESSIONS = {'firefox', 'chrome', 'edge'}
_AUTH_COOKIE_NAMES = {'SID', 'LOGIN_INFO', 'SAPISID', '__Secure-1PSID', '__Secure-3PSID', '__Secure-1PAPISID', '__Secure-3PAPISID'}


def _youtube_cookies(cookies):
    selected = [cookie for cookie in cookies if
                (cookie.domain.lstrip('.').lower() == 'youtube.com' or
                 cookie.domain.lstrip('.').lower().endswith('.youtube.com')) and not cookie.is_expired()]
    if not any(cookie.name in _AUTH_COOKIE_NAMES for cookie in selected):
        raise ValueError('No signed-in YouTube session found. Sign in to YouTube in that browser, or import a fresh YouTube cookies.txt file.')
    return selected


def parse_youtube_cookies(text):
    """Read an explicitly imported Netscape file without logging cookie values."""
    if not isinstance(text, str) or len(text.encode('utf-8')) > 2 * 1024 * 1024 or '\x00' in text:
        raise ValueError('Choose a YouTube cookies.txt file smaller than 2 MB.')
    lines = text.lstrip('\ufeff').splitlines()
    if not lines or lines[0].strip() not in {'# Netscape HTTP Cookie File', '# HTTP Cookie File'}:
        raise ValueError('Choose a Netscape-format YouTube cookies.txt file, rather than a JSON export.')
    cookies = []
    try:
        for line in lines[1:]:
            http_only = line.startswith('#HttpOnly_')
            if http_only: line = line[len('#HttpOnly_'):]
            elif not line or line.startswith('#'): continue
            domain, subdomains, path, secure, expires, name, value = line.split('\t')
            if subdomains not in {'TRUE', 'FALSE'} or secure not in {'TRUE', 'FALSE'} or not path.startswith('/') or not name:
                raise ValueError()
            expiry = int(expires or '0') or None
            cookies.append(http.cookiejar.Cookie(0, name, value, None, False, domain, subdomains == 'TRUE',
                domain.startswith('.'), path, True, secure == 'TRUE', expiry, expiry is None, None, None,
                {'HttpOnly': None} if http_only else {}))
    except (TypeError, ValueError):
        raise ValueError('The cookies.txt file has an invalid entry. Export a fresh YouTube session.') from None
    return _youtube_cookies(cookies)


def youtube_cookie_text(text):
    return _youtube_cookie_text(parse_youtube_cookies(text))


def _youtube_cookie_text(cookies):
    lines = ['# Netscape HTTP Cookie File']
    for cookie in cookies:
        domain = ('#HttpOnly_' if cookie.has_nonstandard_attr('HttpOnly') else '') + cookie.domain
        lines.append('\t'.join((domain, 'TRUE' if cookie.domain_specified else 'FALSE', cookie.path,
                               'TRUE' if cookie.secure else 'FALSE', str(cookie.expires or 0), cookie.name, cookie.value)))
    return '\n'.join(lines) + '\n'


def browser_youtube_cookie_text(source):
    """Read only YouTube cookies for an explicitly connected browser session."""
    if source not in BROWSER_SESSIONS:
        raise ValueError('Choose Chrome, Edge, or Firefox to connect a browser session.')
    from yt_dlp.cookies import extract_cookies_from_browser
    try:
        cookies = _youtube_cookies(extract_cookies_from_browser(source, logger=_QuietLogger()))
    except Exception:
        raise ValueError('Could not read this browser session. Sign in to YouTube, fully close the browser, then Connect / Refresh session.') from None
    return _youtube_cookie_text(cookies)


def _apply_youtube_session(downloader, session):
    if not session: return
    source = session.get('source')
    if source == 'imported':
        cookies = parse_youtube_cookies(session.get('cookies', ''))
    elif source in BROWSER_SESSIONS:
        from yt_dlp.cookies import extract_cookies_from_browser
        try:
            cookies = _youtube_cookies(extract_cookies_from_browser(source, logger=_QuietLogger()))
        except Exception:
            raise ValueError('Could not read a signed-in YouTube session from this browser. Close the browser and retry, or use Import YouTube cookies in sign-in settings.') from None
    else:
        raise ValueError('Choose a supported YouTube session source in sign-in settings.')
    for cookie in cookies: downloader.cookiejar.set_cookie(cookie)


def youtube_error_message(error, signed_in=False):
    message = str(error)
    lower = message.lower()
    if 'drm' in lower and ('protected' in lower or 'only images' in lower):
        return 'This YouTube video is DRM protected. The app cannot download its video streams. Signing in or retrying will not remove that protection.'
    if 'confirm your age' in lower or 'age-restricted' in lower or 'age restricted' in lower:
        return ('YouTube requires age verification for this video. Confirm your age on YouTube, refresh the session in YouTube sign-in settings, then Retry.' if signed_in else
                'Sign in required: YouTube needs an age-verified account for this video. Open YouTube sign-in settings, choose your session, then Retry.')
    if 'sign in' in lower or 'login required' in lower or 'authentication' in lower and 'cookie' in lower:
        return ('YouTube did not accept this session. Sign in on YouTube, refresh your session in YouTube sign-in settings, then Retry.' if signed_in else
                'Sign in required: choose your signed-in session in YouTube sign-in settings, then Retry.')
    return message[:600]


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


def preview_youtube_playlist(value: str, *, session=None):
    """List public entries without downloading videos or following arbitrary URLs."""
    from yt_dlp import YoutubeDL
    url = youtube_playlist_url(value)
    options = dict(extract_flat='in_playlist', skip_download=True, ignoreerrors=True, quiet=True,
                   logger=_QuietLogger(), socket_timeout=15, retries=1, extractor_retries=1,
                   playlistend=500)
    with YoutubeDL(options) as downloader:
        _apply_youtube_session(downloader, session)
        try:
            info = downloader.extract_info(url, download=False)
        except Exception as exc:
            raise RuntimeError(youtube_error_message(exc, bool(session))) from None
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
    def debug(self, message, *args, **kwargs):
        pass

    info = debug
    warning = debug
    error = debug


class _DownloadLogger(_QuietLogger):
    def __init__(self):
        self.only_protected_streams = False

    def warning(self, message, *args, **kwargs):
        # Retain only a diagnostic flag, never the raw message or credentials.
        lower = str(message).lower()
        if 'drm protected' in lower and 'only images' in lower:
            self.only_protected_streams = True


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
    session: dict | None = None,
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

    logger = _DownloadLogger()
    options = {
        "format": selector,
        "outtmpl": str(job_dir / "%(title).150B [%(id)s].%(ext)s"),
        "windowsfilenames": True,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "logger": logger,
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
            _apply_youtube_session(downloader, session)
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
        if logger.only_protected_streams:
            raise RuntimeError(youtube_error_message('This video is DRM protected.')) from None
        raise RuntimeError(youtube_error_message(exc, bool(session))) from None

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
