from __future__ import annotations

import json
import os
import subprocess
from functools import lru_cache
from pathlib import Path

from .media_chapters import find_ffprobe


def quality_label(width: int, height: int) -> str:
    width, height = max(0, int(width)), max(0, int(height))
    for label, minimum_width, minimum_height in (
        ("2160p", 3840, 2160),
        ("1440p", 2560, 1440),
        ("1080p", 1920, 1080),
        ("720p", 1280, 720),
        ("480p", 850, 480),
        ("360p", 630, 350),
    ):
        if width >= minimum_width or height >= minimum_height:
            return label
    return f"{height}p" if height else "Source"


@lru_cache(maxsize=512)
def _probe_video_size_cached(path: str, size: int, modified_ns: int) -> tuple[int, int]:
    del size, modified_ns
    ffprobe = find_ffprobe()
    if not ffprobe:
        return (0, 0)
    command = [
        ffprobe,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json",
        path,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=8.0,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            return (0, 0)
        streams = json.loads(result.stdout or "{}").get("streams") or []
        first = streams[0] if streams else {}
        return (int(first.get("width") or 0), int(first.get("height") or 0))
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, TypeError, ValueError):
        return (0, 0)


def probe_video_size(path: str | Path) -> tuple[int, int]:
    source = Path(path)
    try:
        stat = source.stat()
    except OSError:
        return (0, 0)
    return _probe_video_size_cached(str(source.resolve()), stat.st_size, stat.st_mtime_ns)


def probe_quality_sources(sources: list[tuple[int, str]]) -> list[dict]:
    """Probe real local episode copies and sort them from highest to lowest quality."""
    options: list[dict] = []
    for episode_id, path in sources:
        width, height = probe_video_size(path)
        options.append({
            "episode_id": int(episode_id),
            "path": str(path),
            "width": width,
            "height": height,
            "label": quality_label(width, height),
        })
    options.sort(
        key=lambda option: (
            int(option["width"]) * int(option["height"]),
            int(option["height"]),
            str(option["path"]).casefold(),
        ),
        reverse=True,
    )
    return options
