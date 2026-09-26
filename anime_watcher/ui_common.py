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


def language_switch_required(current_language: str, next_language: str) -> bool:
    return current_language != next_language and current_language != "Unknown"
