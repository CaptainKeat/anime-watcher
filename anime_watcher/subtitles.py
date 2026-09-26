from __future__ import annotations

import bisect
import hashlib
import html
import os
import re
import shutil
import subprocess
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .preview import find_ffmpeg


SUBTITLE_EXTENSIONS = {".srt", ".vtt", ".ass", ".ssa"}
WHISPER_MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin?download=true"
WHISPER_MODEL_SHA256 = "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b"


@dataclass(frozen=True)
class SubtitleCue:
    start_ms: int
    end_ms: int
    text: str
    alignment: str = "bottom"


def _clean_text(value: str) -> str:
    value = value.replace(r"\N", "\n").replace(r"\n", "\n")
    value = re.sub(r"\{[^}]*\}", "", value)
    value = re.sub(r"<[^>]+>", "", value)
    return html.unescape(value).strip()


def _timestamp_ms(value: str) -> int:
    normalized = value.strip().replace(",", ".")
    parts = normalized.split(":")
    if len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        raise ValueError("Invalid subtitle timestamp")
    return round((int(hours) * 3600 + int(minutes) * 60 + float(seconds)) * 1000)


def _parse_timed_blocks(text: str) -> list[SubtitleCue]:
    cues: list[SubtitleCue] = []
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for block in re.split(r"\n\s*\n", normalized):
        lines = [line.strip("\ufeff") for line in block.splitlines() if line.strip()]
        timing_index = next((index for index, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue
        timing = lines[timing_index].split("-->", 1)
        try:
            start_ms = _timestamp_ms(timing[0].split()[0])
            end_ms = _timestamp_ms(timing[1].split()[0])
        except (ValueError, IndexError):
            continue
        cue_text = _clean_text("\n".join(lines[timing_index + 1:]))
        if cue_text and end_ms > start_ms:
            cues.append(SubtitleCue(start_ms, end_ms, cue_text))
    return cues


def _parse_ass(text: str) -> list[SubtitleCue]:
    cues: list[SubtitleCue] = []
    fields = ["Layer", "Start", "End", "Style", "Name", "MarginL", "MarginR", "MarginV", "Effect", "Text"]
    in_events = False
    for raw_line in text.replace("\r\n", "\n").splitlines():
        line = raw_line.strip()
        if line.startswith("["):
            in_events = line.casefold() == "[events]"
            continue
        if not in_events:
            continue
        if line.casefold().startswith("format:"):
            fields = [part.strip() for part in line.split(":", 1)[1].split(",")]
            continue
        if not line.casefold().startswith("dialogue:"):
            continue
        values = line.split(":", 1)[1].lstrip().split(",", len(fields) - 1)
        if len(values) != len(fields):
            continue
        row = dict(zip(fields, values))
        try:
            start_ms = _timestamp_ms(row["Start"])
            end_ms = _timestamp_ms(row["End"])
        except (KeyError, ValueError):
            continue
        raw_text = row.get("Text", "")
        alignment_match = re.search(r"\\an([1-9])", raw_text, re.IGNORECASE)
        alignment_number = int(alignment_match.group(1)) if alignment_match else 2
        alignment = "top" if alignment_number in {7, 8, 9} else "center" if alignment_number in {4, 5, 6} else "bottom"
        cue_text = _clean_text(raw_text)
        if cue_text and end_ms > start_ms:
            cues.append(SubtitleCue(start_ms, end_ms, cue_text, alignment))
    return cues


def load_subtitle_file(path: str | Path) -> list[SubtitleCue]:
    source = Path(path)
    text = source.read_text(encoding="utf-8-sig", errors="replace")
    cues = _parse_ass(text) if source.suffix.casefold() in {".ass", ".ssa"} else _parse_timed_blocks(text)
    return sorted(cues, key=lambda cue: (cue.start_ms, cue.end_ms))


def subtitle_text_at(cues: list[SubtitleCue], position_ms: int) -> str:
    active = subtitle_texts_at(cues, position_ms)
    return "\n".join(text for _alignment, text in active)


def subtitle_texts_at(cues: list[SubtitleCue], position_ms: int) -> list[tuple[str, str]]:
    """Return every active cue, preserving basic ASS/SSA screen alignment."""
    if not cues:
        return []
    starts = [cue.start_ms for cue in cues]
    end_index = bisect.bisect_right(starts, int(position_ms))
    active = [cue for cue in cues[:end_index] if cue.start_ms <= position_ms < cue.end_ms]
    return [(cue.alignment, cue.text) for cue in active]


def find_sidecar_subtitles(video_path: str | Path) -> list[Path]:
    video = Path(video_path)
    if not video.parent.exists():
        return []
    prefix = video.stem.casefold()
    matches = [
        candidate for candidate in video.parent.iterdir()
        if candidate.is_file()
        and candidate.suffix.casefold() in SUBTITLE_EXTENSIONS
        and (candidate.stem.casefold() == prefix or candidate.stem.casefold().startswith(prefix + "."))
    ]
    return sorted(matches, key=lambda path: (".en." not in path.name.casefold() and ".eng." not in path.name.casefold(), path.name.casefold()))


def attach_subtitle_file(video_path: str | Path, subtitle_path: str | Path) -> Path:
    video, subtitle = Path(video_path), Path(subtitle_path)
    if subtitle.suffix.casefold() not in SUBTITLE_EXTENSIONS:
        raise ValueError("Supported subtitle formats are SRT, VTT, ASS, and SSA")
    cues = load_subtitle_file(subtitle)
    if not cues:
        raise ValueError("The subtitle file does not contain readable timed captions")
    language_tag = ".en" if re.search(r"(?:^|[._ -])(?:en|eng|english)(?:[._ -]|$)", subtitle.stem, re.I) else ""
    destination = video.with_name(f"{video.stem}{language_tag}{subtitle.suffix.casefold()}")
    if destination.exists() and destination.resolve() != subtitle.resolve():
        index = 2
        while destination.exists():
            destination = video.with_name(f"{video.stem}{language_tag}.{index}{subtitle.suffix.casefold()}")
            index += 1
    if destination.resolve() != subtitle.resolve():
        shutil.copy2(subtitle, destination)
    return destination


def find_whisper_cli(configured: str | Path | None = None) -> Path | None:
    candidates = [
        Path(configured) if configured else None,
        Path(shutil.which("whisper-cli.exe") or shutil.which("whisper-cli") or ""),
        Path.home() / "tools" / "whisper.cpp" / "Release" / "whisper-cli.exe",
    ]
    return next((candidate for candidate in candidates if candidate and candidate.is_file()), None)


def default_whisper_model_path() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return root / "AnimeWatcher" / "models" / "ggml-small.bin"


def download_whisper_model(destination: str | Path, progress: Callable[..., None] | None = None) -> Path:
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".download")
    request = urllib.request.Request(WHISPER_MODEL_URL, headers={"User-Agent": "AnimeWatcher/1.0"})
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as handle:
            total = int(response.headers.get("Content-Length") or 0)
            received = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                if progress:
                    percent = round(received / total * 100) if total else 0
                    progress(percent, "Downloading local Whisper model")
        if digest.hexdigest().casefold() != WHISPER_MODEL_SHA256.casefold():
            raise RuntimeError("Downloaded Whisper model failed its SHA-256 integrity check")
        temporary.replace(target)
        return target
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def generate_english_subtitles(
    video_path: str | Path,
    output_path: str | Path,
    whisper_cli: str | Path,
    model_path: str | Path,
    progress: Callable[..., None] | None = None,
) -> Path:
    video, output = Path(video_path).resolve(), Path(output_path).resolve()
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required to extract the episode audio")
    cli, model = Path(whisper_cli).resolve(), Path(model_path).resolve()
    if not cli.is_file():
        raise RuntimeError("whisper-cli.exe was not found")
    if not model.is_file():
        raise RuntimeError("The local Whisper model has not been downloaded")
    output.parent.mkdir(parents=True, exist_ok=True)
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    # Keep temporary audio beside the requested output. If the app can save the
    # final SRT there, FFmpeg can write there too; this also avoids locked-down
    # system temp folders on managed Windows installations.
    audio = output.with_name(f".{output.stem}.{uuid.uuid4().hex}.whisper.wav")
    try:
        if progress:
            progress(5, "Extracting episode audio")
        extraction = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(video), "-map", "0:a:0", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio)],
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
            creationflags=creation_flags,
        )
        if extraction.returncode != 0 or not audio.is_file():
            detail = extraction.stderr.strip().splitlines()[-1] if extraction.stderr.strip() else "unknown FFmpeg error"
            raise RuntimeError(f"Could not extract audio: {detail}")
        if progress:
            progress(15, "Transcribing and translating locally")
        output_base = output.with_suffix("")
        command = [
            str(cli), "-m", str(model), "-f", str(audio), "-l", "auto", "-tr",
            "-osrt", "-of", str(output_base), "-pp",
        ]
        generated = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=7200,
            check=False,
            cwd=str(cli.parent),
            creationflags=creation_flags,
        )
        produced = Path(f"{output_base}.srt")
        if generated.returncode != 0 or not produced.is_file():
            detail_lines = (generated.stderr or generated.stdout).strip().splitlines()
            detail = detail_lines[-1] if detail_lines else "unknown Whisper error"
            raise RuntimeError(f"Whisper could not generate subtitles: {detail}")
        if produced.resolve() != output.resolve():
            produced.replace(output)
        if progress:
            progress(100, "English subtitles ready")
    finally:
        audio.unlink(missing_ok=True)
    return output
