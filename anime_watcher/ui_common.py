from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path


def library_root_from_setting(value: object) -> Path | None:
    text = str(value or "").strip()
    return Path(text) if text else None


def resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base.joinpath(*parts)


def format_time(milliseconds: int) -> str:
    seconds = max(0, int(milliseconds) // 1000)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def episode_variant_options(variants) -> dict[str, int]:
    language_counts: dict[str, int] = defaultdict(int)
    for row in variants:
        language_counts[str(row["language"] or "Unknown")] += 1
    language_indexes: dict[str, int] = defaultdict(int)
    options: dict[str, int] = {}
    for row in variants:
        language = str(row["language"] or "Unknown")
        language_indexes[language] += 1
        label = f"{language.upper()} VERSION"
        if language_counts[language] > 1:
            label += f" {language_indexes[language]}"
        options[label] = int(row["id"])
    return options


def episode_language_options(variants, current_episode_id: int | None = None) -> dict[str, int]:
    """Collapse same-language quality copies into one Sub/Dub version choice."""
    options: dict[str, int] = {}
    for row in variants:
        language = str(row["language"] or "Unknown")
        label = f"{language.upper()} VERSION"
        episode_id = int(row["id"])
        if label not in options or episode_id == current_episode_id:
            options[label] = episode_id
    return options


def choose_episode_variant(variants, preferred_language: str = "Sub"):
    priorities: list[str] = []
    for language in (preferred_language, "Sub", "Dub", "Unknown"):
        if language not in priorities:
            priorities.append(language)
    for language in priorities:
        match = next((row for row in variants if str(row["language"] or "Unknown") == language), None)
        if match is not None:
            return match
    return variants[0] if variants else None


def episode_watch_progress(variants) -> dict:
    """Display the furthest saved position of one copy, never add copies together."""
    def position(row):
        return max(0, int(row["progress_ms"] or 0))

    def fraction(row):
        duration = max(0, int(row["duration_ms"] or 0))
        return min(1.0, position(row) / duration) if duration else 0.0

    row = max(variants, key=lambda row: (fraction(row), position(row)))
    progress = position(row)
    duration = max(0, int(row["duration_ms"] or 0))
    completed = any(bool(item["completed"]) and position(item) > 0 for item in variants)
    value = round(fraction(row) * 1000)
    if not progress:
        label = "Not watched"
    elif duration:
        label = f"{round(fraction(row) * 100)}% watched · {format_time(min(progress, duration))} / {format_time(duration)}"
        if completed:
            label += " · Complete"
    else:
        label = f"{format_time(progress)} watched · duration unavailable"
    language = str(row["language"] or "Unknown")
    return dict(value=value, label=label, completed=completed,
                tooltip=f"Furthest saved playback position · {language} version\n{label}",
                episode_id=int(row["id"]))


def language_switch_required(current_language: str, next_language: str) -> bool:
    return current_language != next_language and current_language != "Unknown"
