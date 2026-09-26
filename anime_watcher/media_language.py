from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


ENGLISH_CODES = {"en", "eng", "english"}
JAPANESE_CODES = {"ja", "jp", "jpn", "japanese"}


def _stream_language(stream: dict) -> str:
    tags = stream.get("tags") or {}
    language = str(tags.get("language") or "").strip().lower()
    description = " ".join(
        str(tags.get(key) or "") for key in ("title", "handler_name")
    ).lower()
    if language in ENGLISH_CODES or "english" in description:
        return "English"
    if language in JAPANESE_CODES or "japanese" in description:
        return "Japanese"
    return "Unknown"


def classify_streams(streams: list[dict]) -> str:
    """Classify an anime file from embedded stream metadata.

    English audio is treated as Dub. Japanese audio, or English subtitles with
    no English audio, is treated as Sub. Files without useful tags remain
    Unknown so the caller can use sibling-version inference or manual review.
    """
    audio_languages: list[str] = []
    subtitle_languages: list[str] = []
    for stream in streams:
        stream_type = str(stream.get("codec_type") or "").lower()
        tags = stream.get("tags") or {}
        handler = str(tags.get("handler_name") or "").lower()
        language = _stream_language(stream)
        if stream_type == "audio":
            audio_languages.append(language)
        elif stream_type == "subtitle" or "subtitle" in handler:
            subtitle_languages.append(language)

    if "English" in audio_languages:
        return "Dub"
    if "Japanese" in audio_languages:
        return "Sub"
    if "English" in subtitle_languages:
        return "Sub"
    return "Unknown"


def probe_embedded_language(path: str | Path, timeout: float = 8.0) -> str:
    """Inspect stream tags with ffprobe without decoding or uploading audio."""
    ffprobe = shutil.which("ffprobe")
    source = Path(path)
    if not ffprobe or not source.is_file():
        return "Unknown"
    command = [
        ffprobe,
        "-v", "error",
        "-show_entries", "stream=codec_type:stream_tags=language,title,handler_name",
        "-of", "json",
        str(source),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            return "Unknown"
        payload = json.loads(result.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return "Unknown"
    streams = payload.get("streams")
    return classify_streams(streams if isinstance(streams, list) else [])
