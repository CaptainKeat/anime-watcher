"""WCO catalog identity and verified-file import; browser state lives in wco_browser."""
from __future__ import annotations

import json
import math
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

from .downloader import EpisodeResult
from .media_quality import probe_video_size, quality_label
from .organizer import organize_file, safe_component


def title_key(title: str) -> str:
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", title).casefold()))


def library_title(title: str, series_rows) -> str:
    matches = [str(row["title"]) for row in series_rows
               if title_key(title) in {title_key(str(row["title"])), title_key(str(row["display_title"] or ""))}]
    return matches[0] if len(matches) == 1 else title


def library_status(episode: EpisodeResult, local_rows) -> str:
    matches = [row for row in local_rows if row["season"] == episode.season and str(row["episode"]) == episode.number]
    if any(row["language"] == episode.language and Path(row["path"]).is_file() for row in matches):
        return "In library"
    if any(Path(row["path"]).is_file() for row in matches):
        return "Other version in library"
    return "Not downloaded"


def batch_episodes(episodes, local_rows, skip_existing=True):
    """Plan whole-number WCO slots in playback order, preserving local copies."""
    owned = {(int(row["season"]), int(row["episode"]), row["language"])
             for row in local_rows if Path(row["path"]).is_file()}
    stats = {"in_library":0, "unsupported":0, "duplicates":0}
    seen_slots, seen_urls, candidates = set(), set(), []
    for episode in episodes:
        if (not episode.direct_open or episode.season is None or not episode.number
                or not re.fullmatch(r"[0-9]+", episode.number) or not 0 <= episode.season <= 999
                or not 0 <= int(episode.number) <= 9999):
            stats["unsupported"] += 1
            continue
        slot = (episode.season, int(episode.number), episode.language)
        if slot in seen_slots or episode.url in seen_urls:
            stats["duplicates"] += 1
            continue
        seen_slots.add(slot); seen_urls.add(episode.url)
        if skip_existing and slot in owned:
            stats["in_library"] += 1
            continue
        candidates.append(episode)
    return sorted(candidates, key=lambda e:(e.season,int(e.number),e.language)), stats


def quality_height(choice: str) -> int:
    label = choice.strip().upper()
    match = re.fullmatch(r"(\d{3,4})P", label)
    return int(match[1]) if match else {"FHD":1080,"HD":720,"SD":480}.get(label, 0)


def best_quality(choices: list[str]) -> str | None:
    ranked = []
    for choice in choices:
        rank = quality_height(choice)
        if rank:
            ranked.append((rank, choice))
    return max(ranked)[1] if ranked else None


def playable_media(state: dict) -> bool:
    try:
        return (int(state.get("readyState", 0)) >= 2 and int(state.get("width", 0)) > 0
                and int(state.get("height", 0)) > 0 and math.isfinite(float(state.get("duration", 0)))
                and float(state.get("duration", 0)) > 0 and not state.get("error")
                and str(state.get("src", "")).startswith(("http://", "https://")))
    except (ValueError, TypeError):
        return False


def single_stream_media(state: dict) -> bool:
    """A loaded WCO player explicitly exposes one source and no quality control."""
    url = urlparse(str(state.get("src", "")))
    host = url.hostname or ""
    return (state.get("singleSource") is True and not state.get("choices")
            and not state.get("selected") and not state.get("closeReady")
            and url.scheme in {"http", "https"}
            and (host == "wcostream.com" or host.endswith(".wcostream.com"))
            and url.path == "/getvid"
            and (playable_media(state) or (state.get("mp4Support") == ""
                 and (not state.get("error") or state.get("errorCode") == 4))))


def downloadable_media(state: dict) -> bool:
    if playable_media(state) or single_stream_media(state):
        return True
    # Qt's browser may lack H.264 although the desktop FFmpeg player supports it.
    # Accept only a real selected player source, then verify the saved file before
    # import. Browser playback is not evidence of a successful download.
    url = urlparse(str(state.get("src", "")))
    host = url.hostname or ""
    return (state.get("mp4Support") == "" and url.scheme in {"http", "https"}
            and (host == "wcostream.com" or host.endswith(".wcostream.com"))
            and url.path == "/getvid" and bool(best_quality([str(state.get("selected", ""))]))
            and (not state.get("error") or state.get("errorCode") == 4))


class VideoVerificationError(ValueError):
    """A source returned an invalid video or less than the selected resolution."""


def import_wco_video(path: str | Path, library_root: str | Path, title: str,
                     episode: EpisodeResult, expected_height: int = 0):
    source = Path(path)
    if not episode.number or not episode.number.isdigit():
        raise ValueError("This special episode needs a whole-number library slot before import.")
    season, number = int(episode.season or 1), int(episode.number)
    if not 0 <= season <= 999 or not 0 <= number <= 9999:
        raise ValueError("The episode slot is outside the supported range.")
    width, height = probe_video_size(source)
    if not width or not height:
        raise VideoVerificationError("The download is not a verified video. It remains in Downloads for inspection.")
    if expected_height and height < expected_height:
        raise VideoVerificationError(f"The downloaded video is {height}p, below the selected {expected_height}p. It remains in Downloads.")
    title = safe_component(title)
    if not title:
        raise ValueError("The series title is empty")
    quality = quality_label(width, height)
    destination = Path(library_root) / title / f"Season {season:02d}" / f"{title} - S{season:02d}E{number:02d} [{episode.language}] [{quality}].mp4"
    root = Path(library_root).resolve()
    destination.resolve().relative_to(root)
    result = organize_file(source, root, destination=destination)
    if result.destination and result.status == "moved":
        metadata = {"provider": "wco", "page_url": episode.url, "title": title,
                    "season": season, "episode": number, "language": episode.language,
                    "width": width, "height": height}
        try:
            result.destination.with_name(result.destination.name + ".source.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        except OSError:
            import shutil
            source.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(result.destination), str(source))
            raise
    return result
