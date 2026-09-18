from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import threading
from functools import lru_cache
from pathlib import Path


PREVIEW_BUCKET_MS = 5000


def preview_bucket(milliseconds: int, bucket_ms: int = PREVIEW_BUCKET_MS) -> int:
    """Snap preview requests to a small cache-friendly time bucket."""
    return max(0, int(milliseconds) // bucket_ms * bucket_ms)


@lru_cache(maxsize=1)
def find_ffmpeg() -> str | None:
    discovered = shutil.which("ffmpeg.exe") or shutil.which("ffmpeg")
    if discovered:
        return discovered
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    packages = local_app_data / "Microsoft" / "WinGet" / "Packages"
    if packages.exists():
        matches = sorted(packages.glob("Gyan.FFmpeg_*/*/bin/ffmpeg.exe"), reverse=True)
        if matches:
            return str(matches[0])
    return None


def preview_cache_name(video_path: str | Path, milliseconds: int) -> str:
    path = Path(video_path)
    try:
        stat = path.stat()
        identity = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    except OSError:
        identity = str(path.resolve())
    timestamp = preview_bucket(milliseconds)
    digest = hashlib.sha256(f"{identity}|{timestamp}".encode("utf-8")).hexdigest()[:24]
    return f"{digest}-{timestamp}.jpg"


def preview_cache_path(video_path: str | Path, milliseconds: int, cache_dir: str | Path) -> Path:
    return Path(cache_dir) / preview_cache_name(video_path, milliseconds)


def cached_video_preview(video_path: str | Path, milliseconds: int, cache_dir: str | Path) -> Path | None:
    """Return an already-generated frame without starting FFmpeg."""
    candidate = preview_cache_path(video_path, milliseconds, cache_dir)
    try:
        return candidate if candidate.is_file() and candidate.stat().st_size > 0 else None
    except OSError:
        return None


def nearest_cached_video_preview(
    video_path: str | Path,
    milliseconds: int,
    cache_dir: str | Path,
    *,
    max_distance_ms: int = 15000,
) -> Path | None:
    """Find the closest ready frame so timeline movement never waits on FFmpeg."""
    target = preview_bucket(milliseconds)
    for distance in range(0, max(0, max_distance_ms) + PREVIEW_BUCKET_MS, PREVIEW_BUCKET_MS):
        candidates = (target,) if distance == 0 else (target - distance, target + distance)
        for timestamp in candidates:
            if timestamp < 0:
                continue
            cached = cached_video_preview(video_path, timestamp, cache_dir)
            if cached is not None:
                return cached
    return None


def preview_warmup_targets(duration_ms: int, interval_ms: int = 15000) -> list[int]:
    """Prioritize broad timeline coverage, then fill regular preview intervals."""
    duration = max(0, int(duration_ms))
    if duration <= 0:
        return []
    last = preview_bucket(max(0, duration - 1000))
    anchors = [
        0,
        preview_bucket(duration // 4),
        preview_bucket(duration // 2),
        preview_bucket(duration * 3 // 4),
        last,
    ]
    regular = range(0, last + 1, max(PREVIEW_BUCKET_MS, int(interval_ms)))
    seen: set[int] = set()
    ordered: list[int] = []
    for timestamp in [*anchors, *regular]:
        timestamp = min(last, preview_bucket(timestamp))
        if timestamp not in seen:
            seen.add(timestamp)
            ordered.append(timestamp)
    return ordered


def trim_preview_cache(cache_dir: str | Path, max_files: int = 400) -> None:
    directory = Path(cache_dir)
    try:
        files = sorted(directory.glob("*.jpg"), key=lambda item: item.stat().st_mtime, reverse=True)
    except OSError:
        return
    for stale in files[max_files:]:
        try:
            stale.unlink()
        except OSError:
            pass


def generate_video_preview(
    video_path: str | Path,
    milliseconds: int,
    cache_dir: str | Path,
    *,
    width: int = 320,
    height: int = 180,
) -> Path:
    """Extract one cached preview frame without touching the active VLC player."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("Timeline previews need FFmpeg, but ffmpeg.exe was not found")
    source = Path(video_path)
    if not source.is_file():
        raise FileNotFoundError(f"Video file is missing: {source}")
    directory = Path(cache_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = preview_cache_path(source, milliseconds, directory)
    if target.exists() and target.stat().st_size > 0:
        os.utime(target, None)
        return target

    temporary = directory / f"{target.stem}.{os.getpid()}.{threading.get_ident()}.part.jpg"
    timestamp = preview_bucket(milliseconds) / 1000
    video_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
    )
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    completed = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel", "error",
            "-nostdin",
            "-ss", f"{timestamp:.3f}",
            "-i", str(source),
            "-frames:v", "1",
            "-vf", video_filter,
            "-q:v", "3",
            "-y", str(temporary),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=20,
        creationflags=creation_flags,
    )
    if completed.returncode != 0 or not temporary.exists():
        try:
            temporary.unlink()
        except OSError:
            pass
        detail = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "unknown error"
        raise RuntimeError(f"Could not generate timeline preview: {detail}")
    temporary.replace(target)
    trim_preview_cache(directory)
    return target
