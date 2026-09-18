from __future__ import annotations


def marquee_frame(text: str, offset: int, visible_chars: int, gap: str = "          •          ") -> str:
    """Return one fixed-width frame for an overflowing title marquee."""
    if visible_chars < 2 or len(text) <= visible_chars:
        return text
    runway = text + gap
    start = offset % len(runway)
    repeated = runway + runway
    return repeated[start:start + visible_chars]
