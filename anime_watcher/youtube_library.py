from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from .organizer import safe_component


def youtube_metadata_path(video: str | Path) -> Path:
    path = Path(video)
    return path.with_name(path.name + ".youtube.json")


def read_youtube_metadata(video: str | Path) -> dict:
    path = youtube_metadata_path(video)
    try:
        if path.stat().st_size > 65536:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def video_title(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"^YouTube\s*-\s*S\d+E00\s*-\s*", "", value, flags=re.I)
    return re.sub(r"\s*\[[A-Za-z0-9_-]{11}\]\s*$", "", value).strip()


def title_slot(value: str) -> tuple[int | None, int | None]:
    value = video_title(value)
    match = re.search(r"\bS(\d{1,3})E(\d{1,4})\b", value, re.I)
    if match:
        return int(match[1]), int(match[2])
    season = re.search(r"\bSeason\s+(\d{1,3})\b", value, re.I)
    episode = re.search(r"\b(?:Episode|Ep\.?|Part)\s*[#:-]?\s*(\d{1,4})\b|#\s*(\d{1,4})\b", value, re.I)
    return (int(season[1]) if season else None, int(episode[1] or episode[2]) if episode else None)


def _title_key(value: str) -> str:
    value = video_title(value)
    value = re.sub(r"\bS\d{1,3}E\d{1,4}\b|\bSeason\s+\d{1,3}\b|\b(?:Episode|Ep\.?|Part)\s*[#:-]?\s*\d{1,4}\b|#\s*\d{1,4}\b", " ", value, flags=re.I)
    return " ".join(re.findall(r"\w+", value.casefold()))


def series_snapshot(series_rows, episode_rows) -> list[dict]:
    groups = {int(row["id"]): {"title": str(row["title"]), "display_title": str(row["display_title"] or ""), "episodes": [], "channel_ids": set()} for row in series_rows}
    for row in episode_rows:
        group = groups.get(int(row["series_id"]))
        if group is None:
            continue
        metadata = read_youtube_metadata(row["path"])
        group["episodes"].append({"path": str(row["path"]), "season": int(row["season"]), "episode": int(row["episode"]), "video_id": str(metadata.get("id") or "")})
        if metadata.get("channel_id"):
            group["channel_ids"].add(str(metadata["channel_id"]))
    return list(groups.values())


def match_youtube_series(metadata: dict, groups: list[dict]) -> dict | None:
    # Older downloads used one full video title/ID per tab. Those are not
    # canonical series matches when a real series tab already exists.
    groups = [group for group in groups if not re.search(r"\[[A-Za-z0-9_-]{11}\]\s*$", group["title"])]
    needle = _title_key(str(metadata.get("title") or ""))
    # Exact normalized titles take priority over a channel with several series.
    exact = [group for group in groups if needle and needle in {_title_key(group["title"]), _title_key(group.get("display_title", ""))}]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None
    # Only consider a whole title at the start, not a loose word such as "Slime".
    prefixes = []
    for group in groups:
        keys = {_title_key(group["title"]), _title_key(group.get("display_title", ""))}
        score = max((len(key) for key in keys if len(key) >= 6 and len(key.split()) >= 2 and needle.startswith(key + " ")), default=0)
        if score:
            prefixes.append((score, group))
    if prefixes:
        best = max(score for score, _ in prefixes)
        matches = [group for score, group in prefixes if score == best]
        return matches[0] if len(matches) == 1 else None
    channel_id = str(metadata.get("channel_id") or "")
    channels = [group for group in groups if channel_id and channel_id in group.get("channel_ids", set())]
    if channels:
        return channels[0] if len(channels) == 1 else None
    channel_key = _title_key(str(metadata.get("channel") or ""))
    names = [group for group in groups if channel_key and channel_key in {_title_key(group["title"]), _title_key(group.get("display_title", ""))}]
    return names[0] if len(names) == 1 else None


def suggested_slot(title: str, episodes, season: int | None = None, episode: int | None = None) -> tuple[int, int]:
    inferred_season, inferred_episode = title_slot(title)
    selected_season = season if season is not None else inferred_season if inferred_season is not None else 1
    selected_episode = episode if episode is not None else inferred_episode
    if selected_episode is None:
        selected_episode = max((int(row["episode"]) for row in episodes if int(row["season"]) == selected_season), default=0) + 1
    if not 0 <= selected_season <= 999 or not 0 <= selected_episode <= 9999:
        raise ValueError("The selected season or episode number is outside the supported range.")
    return selected_season, selected_episode


def youtube_destination(video: Path, library_root: Path, metadata: dict, groups: list[dict],
                        target_title: str | None = None, season: int | None = None, episode: int | None = None) -> Path:
    group = next((row for row in groups if row["title"] == target_title), None) if target_title else match_youtube_series(metadata, groups)
    title = str(metadata.get("title") or video_title(video.stem))
    series_title = target_title or (group["title"] if group else str(metadata.get("channel") or video_title(video.stem)))
    episodes = group["episodes"] if group else []
    number_season, number_episode = suggested_slot(title, episodes, season, episode)
    video_id = str(metadata.get("id") or "")
    existing = next((row for row in episodes if video_id and row.get("video_id") == video_id and Path(row["path"]).is_file()), None)
    if existing:
        return Path(existing["path"])
    if any(row["season"] == number_season and row["episode"] == number_episode for row in episodes):
        raise FileExistsError(f"Season {number_season}, episode {number_episode} already exists in {series_title}. Choose an episode number before retrying.")
    label = safe_component(series_title)
    # The leading marker makes scanning immune to episode-like text in IDs/titles.
    name = f"YouTube - S{number_season:02d}E{number_episode:02d} - {safe_component(video.stem)}{video.suffix.lower()}"
    return library_root / label / f"Season {number_season:02d}" / name
