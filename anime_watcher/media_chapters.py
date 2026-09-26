from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


CHAPTER_PATTERNS = {
    "intro": re.compile(r"\b(?:intro|opening|opening theme|opening credits|op)\b", re.IGNORECASE),
    "outro": re.compile(r"\b(?:outro|ending|ending theme|ending credits|credits|ed)\b", re.IGNORECASE),
    "recap": re.compile(r"\b(?:recap|previously|prologue)\b", re.IGNORECASE),
    "filler": re.compile(r"\b(?:filler|preview|next episode preview)\b", re.IGNORECASE),
}


@dataclass(frozen=True)
class MediaChapter:
    title: str
    kind: str
    start_ms: int
    end_ms: int


@lru_cache(maxsize=1)
def find_ffprobe() -> str | None:
    discovered = shutil.which("ffprobe.exe") or shutil.which("ffprobe")
    if discovered:
        return discovered
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    packages = local_app_data / "Microsoft" / "WinGet" / "Packages"
    if packages.exists():
        matches = sorted(packages.glob("Gyan.FFmpeg_*/*/bin/ffprobe.exe"), reverse=True)
        if matches:
            return str(matches[0])
    return None


def chapter_ranges_from_chapters(chapters: list[dict]) -> list[MediaChapter]:
    """Extract trustworthy named OP/ED/recap/filler chapter ranges."""
    result: list[MediaChapter] = []
    for chapter in chapters:
        tags = chapter.get("tags") or {}
        title = str(tags.get("title") or tags.get("TITLE") or "").strip()
        kind = next((name for name, pattern in CHAPTER_PATTERNS.items() if pattern.search(title)), None)
        if not kind:
            continue
        try:
            start_ms = round(float(chapter["start_time"]) * 1000)
            end_ms = round(float(chapter["end_time"]) * 1000)
        except (KeyError, TypeError, ValueError):
            continue
        length_ms = end_ms - start_ms
        if start_ms >= 0 and 5_000 <= length_ms <= 600_000:
            result.append(MediaChapter(title or kind.title(), kind, start_ms, end_ms))
    return sorted(result, key=lambda item: (item.start_ms, item.end_ms))


def intro_range_from_chapters(chapters: list[dict]) -> tuple[int, int] | None:
    matches = [(item.start_ms, item.end_ms) for item in chapter_ranges_from_chapters(chapters) if item.kind == "intro"]
    return min(matches) if matches else None


def probe_chapter_ranges(path: str | Path, timeout: float = 8.0) -> list[MediaChapter]:
    """Read embedded chapter names without decoding the video."""
    ffprobe = find_ffprobe()
    source = Path(path)
    if not ffprobe or not source.is_file():
        return []
    command = [
        ffprobe, "-v", "error",
        "-show_entries", "chapter=start_time,end_time:chapter_tags=title",
        "-of", "json", str(source),
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            return []
        payload = json.loads(result.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return []
    chapters = payload.get("chapters")
    return chapter_ranges_from_chapters(chapters if isinstance(chapters, list) else [])


def probe_intro_range(path: str | Path, timeout: float = 8.0) -> tuple[int, int] | None:
    matches = [(item.start_ms, item.end_ms) for item in probe_chapter_ranges(path, timeout) if item.kind == "intro"]
    return min(matches) if matches else None
