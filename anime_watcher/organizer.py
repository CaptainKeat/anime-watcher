from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".webm", ".m4v", ".mov", ".ts"}
INVALID_WINDOWS_CHARS = re.compile(r'[<>:"/\\|?*]')


@dataclass(frozen=True)
class EpisodeInfo:
    title: str
    season: int
    episode: int
    language: str
    extension: str


@dataclass(frozen=True)
class MoveResult:
    source: Path
    destination: Path | None
    status: str
    message: str = ""


def _clean_title(value: str) -> str:
    value = re.sub(r"^\s*\[[^]]+\]\s*", "", value)
    value = re.sub(r"\.(?:mkv|mp4|avi|webm|m4v|mov|ts)$", "", value, flags=re.I)
    value = re.sub(r"\s*\((?:480|720|1080|1440|2160)p[^)]*\)\s*(?:v\d+)?\s*$", "", value, flags=re.I)
    value = re.sub(r"\s*\[(?:English\s*)?(?:Sub(?:bed)?|Dub(?:bed)?)\]\s*$", "", value, flags=re.I)
    value = value.replace("_", " ").replace(".", " ")
    return re.sub(r"\s+", " ", value).strip(" -_")


def parse_episode(path: str | Path) -> EpisodeInfo:
    source = Path(path)
    raw = source.stem
    language = "Unknown"
    combined = f"{source.parent.name} {raw}"
    if re.search(r"\b(?:english\s*)?dub(?:bed)?\b", combined, re.I):
        language = "Dub"
    elif re.search(r"\b(?:english\s*)?sub(?:bed)?\b", combined, re.I):
        language = "Sub"

    cleaned = _clean_title(raw)
    patterns = [
        re.compile(r"^(?P<title>.+?)\s+S(?P<season>\d{1,2})\s*[-_. ]+\s*(?:E|EP)?(?P<episode>\d{1,3})\b", re.I),
        re.compile(r"^(?P<title>.+?)\s+S(?P<season>\d{1,2})E(?P<episode>\d{1,3})\b", re.I),
        re.compile(r"^(?P<title>.+?)\s+Season\s*(?P<season>\d{1,2})\s*[,._ -]*Episode\s*(?P<episode>\d{1,3})\b", re.I),
        re.compile(r"^(?P<title>.+?)\s*[-, ]+\s*(?:EP|Episode)\s*(?P<episode>\d{1,3})\b", re.I),
        re.compile(r"^(?P<title>.+?)\s+-\s+(?P<episode>\d{1,3})\b", re.I),
    ]
    match = next((pattern.search(cleaned) for pattern in patterns if pattern.search(cleaned)), None)
    if match:
        title = _clean_title(match.group("title"))
        season = int(match.groupdict().get("season") or 1)
        episode = int(match.group("episode"))
    else:
        title = _clean_title(source.parent.name if source.parent.name.lower().startswith("season ") else cleaned)
        season_match = re.search(r"Season\s*(\d+)", str(source.parent), re.I)
        episode_match = re.search(r"(?:EP|Episode|E)\s*(\d{1,3})", cleaned, re.I)
        season = int(season_match.group(1)) if season_match else 1
        episode = int(episode_match.group(1)) if episode_match else 0

    title = re.sub(r"\s*\[(?:English\s*)?(?:Sub(?:bed)?|Dub(?:bed)?)\]\s*", "", title, flags=re.I).strip()
    return EpisodeInfo(title or "Unsorted", season, episode, language, source.suffix.lower())


def safe_component(value: str) -> str:
    value = INVALID_WINDOWS_CHARS.sub("-", value).rstrip(" .")
    return re.sub(r"\s+", " ", value).strip() or "Unsorted"


def destination_for(path: str | Path, library_root: str | Path) -> Path:
    source = Path(path)
    info = parse_episode(source)
    title = safe_component(info.title)
    language = f" [{info.language}]" if info.language != "Unknown" else ""
    episode_label = f"S{info.season:02d}E{info.episode:02d}" if info.episode else f"S{info.season:02d}E00"
    filename = f"{title} - {episode_label}{language}{source.suffix.lower()}"
    return Path(library_root) / title / f"Season {info.season:02d}" / filename


def _same_file(left: Path, right: Path) -> bool:
    if not left.exists() or not right.exists() or left.stat().st_size != right.stat().st_size:
        return False
    def digest(path: Path) -> str:
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    return digest(left) == digest(right)


def organize_file(path: str | Path, library_root: str | Path, dry_run: bool = False) -> MoveResult:
    source = Path(path)
    if not source.exists() or source.suffix.lower() not in VIDEO_EXTENSIONS:
        return MoveResult(source, None, "ignored", "Not a supported video file")
    destination = destination_for(source, library_root)
    try:
        if source.resolve() == destination.resolve():
            return MoveResult(source, destination, "unchanged")
    except FileNotFoundError:
        pass
    if destination.exists():
        if _same_file(source, destination):
            return MoveResult(source, destination, "duplicate", "Identical destination already exists")
        stem, suffix, index = destination.stem, destination.suffix, 2
        while destination.exists():
            destination = destination.with_name(f"{stem} ({index}){suffix}")
            index += 1
    if dry_run:
        return MoveResult(source, destination, "planned")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    return MoveResult(source, destination, "moved")


def organize_files(paths: Iterable[str | Path], library_root: str | Path, dry_run: bool = False) -> list[MoveResult]:
    return [organize_file(path, library_root, dry_run=dry_run) for path in paths]


def scan_video_files(root: str | Path) -> list[Path]:
    base = Path(root)
    if not base.exists():
        return []
    return sorted(path for path in base.rglob("*") if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS)
