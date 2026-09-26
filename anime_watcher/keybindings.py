from __future__ import annotations

from collections.abc import Mapping


KEYBINDING_ACTIONS = {
    "play_pause": ("Play / pause", "Space"),
    "seek_back": ("Back 10 seconds", "Left"),
    "seek_forward": ("Forward 10 seconds", "Right"),
    "fullscreen": ("Fullscreen", "F"),
    "next_episode": ("Next episode", "N"),
    "previous_episode": ("Previous episode", "B"),
    "cycle_subtitles": ("Cycle subtitles", "C"),
    "subtitle_delay_down": ("Subtitles 0.1s earlier", ","),
    "subtitle_delay_up": ("Subtitles 0.1s later", "."),
    "picture_in_picture": ("Picture in picture", "P"),
}


def merged_keybindings(saved: object = None) -> dict[str, str]:
    bindings = {action: default for action, (_label, default) in KEYBINDING_ACTIONS.items()}
    if isinstance(saved, Mapping):
        for action, value in saved.items():
            if action in bindings and isinstance(value, str) and value.strip():
                bindings[action] = value.strip()
    return bindings


def duplicate_keybindings(bindings: Mapping[str, str]) -> set[str]:
    normalized = [value.strip().casefold() for value in bindings.values() if value.strip()]
    return {value for value in normalized if normalized.count(value) > 1}
