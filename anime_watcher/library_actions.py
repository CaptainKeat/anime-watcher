from __future__ import annotations

import ctypes
import os
import shutil
from pathlib import Path
from typing import Iterable, Mapping

from .organizer import VIDEO_EXTENSIONS, safe_component


LANGUAGES = {"Sub", "Dub", "Unknown"}


def is_within_library(path: str | Path, library_root: str | Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(library_root).resolve())
        return True
    except (OSError, ValueError):
        return False


def episode_destination(library_root: str | Path, title: str, season: int,
                        episode: int, language: str, extension: str) -> Path:
    title = safe_component(title)
    if not 0 <= season <= 999:
        raise ValueError("Season must be between 0 and 999")
    if not 0 <= episode <= 9999:
        raise ValueError("Episode must be between 0 and 9999")
    if language not in LANGUAGES:
        raise ValueError("Language must be Sub, Dub, or Unknown")
    extension = extension.lower()
    if extension not in VIDEO_EXTENSIONS:
        raise ValueError("Unsupported video file type")
    language_tag = f" [{language}]" if language != "Unknown" else ""
    filename = f"{title} - S{season:02d}E{episode:02d}{language_tag}{extension}"
    return Path(library_root) / title / f"Season {season:02d}" / filename


def rename_episode_file(source: str | Path, library_root: str | Path, title: str,
                        season: int, episode: int, language: str) -> Path:
    source = Path(source)
    root = Path(library_root)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError("The episode file no longer exists")
    if not is_within_library(source, root):
        raise ValueError("Episode is outside the configured library")
    destination = episode_destination(root, title, season, episode, language, source.suffix)
    if not is_within_library(destination, root):
        raise ValueError("The renamed episode would leave the configured library")
    if source.resolve() == destination.resolve():
        return source
    if destination.exists():
        raise FileExistsError(f"A file already exists at:\n{destination}")

    old_season = source.parent
    old_series = old_season.parent
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    for folder in (old_season, old_series):
        try:
            folder.rmdir()
        except OSError:
            pass
    return destination


def rename_series_files(episodes: Iterable[Mapping], library_root: str | Path,
                        new_title: str) -> dict[int, tuple[Path, Path]]:
    """Rename every episode in a series, rolling back if any move fails."""
    root = Path(library_root)
    clean_title = safe_component(new_title)
    rows = list(episodes)
    old_series_folders = {Path(row["path"]).parent.parent.resolve() for row in rows}
    target_series_folder = (root / clean_title).resolve()
    if target_series_folder.exists() and target_series_folder not in old_series_folders:
        raise FileExistsError(f"Another anime folder already exists at:\n{target_series_folder}")
    plans: dict[int, tuple[Path, Path]] = {}
    used_destinations: set[Path] = set()
    old_folders: set[Path] = set()

    for row in rows:
        source = Path(row["path"])
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"Episode file no longer exists:\n{source}")
        if not is_within_library(source, root):
            raise ValueError(f"Episode is outside the configured library:\n{source}")
        destination = episode_destination(
            root, clean_title, int(row["season"]), int(row["episode"]), str(row["language"]), source.suffix
        )
        base_destination = destination
        index = 2
        while destination in used_destinations or (destination.exists() and source.resolve() != destination.resolve()):
            destination = base_destination.with_name(f"{base_destination.stem} ({index}){base_destination.suffix}")
            index += 1
        used_destinations.add(destination)
        plans[int(row["id"])] = (source, destination)
        old_folders.update((source.parent, source.parent.parent))

    moved: list[tuple[Path, Path]] = []
    try:
        for source, destination in plans.values():
            if source.resolve() == destination.resolve():
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            moved.append((source, destination))
    except Exception:
        for source, destination in reversed(moved):
            try:
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(destination), str(source))
            except OSError:
                pass
        raise

    for folder in sorted(old_folders, key=lambda item: len(item.parts), reverse=True):
        try:
            folder.rmdir()
        except OSError:
            pass
    return plans


def rollback_series_files(plans: Mapping[int, tuple[Path, Path]]) -> None:
    for source, destination in reversed(list(plans.values())):
        if destination == source or not destination.exists() or source.exists():
            continue
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(destination), str(source))


def send_to_recycle_bin(path: str | Path, library_root: str | Path) -> None:
    target = Path(path)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError("The episode file no longer exists")
    if not is_within_library(target, library_root):
        raise ValueError("Episode is outside the configured library")
    if os.name != "nt":
        raise OSError("Recycle Bin deletion is only available on Windows")

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", ctypes.c_void_p),
            ("wFunc", ctypes.c_uint),
            ("pFrom", ctypes.c_wchar_p),
            ("pTo", ctypes.c_wchar_p),
            ("fFlags", ctypes.c_ushort),
            ("fAnyOperationsAborted", ctypes.c_int),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", ctypes.c_wchar_p),
        ]

    operation = SHFILEOPSTRUCTW()
    operation.wFunc = 3  # FO_DELETE
    operation.pFrom = str(target.resolve()) + "\0\0"
    operation.fFlags = 0x0040 | 0x0010 | 0x0400  # ALLOWUNDO | NOCONFIRMATION | NOERRORUI
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    if result != 0:
        raise OSError(result, "Windows could not move the episode to the Recycle Bin")
    if operation.fAnyOperationsAborted:
        raise OSError("Recycle Bin operation was cancelled")
    for folder in (target.parent, target.parent.parent):
        try:
            folder.rmdir()
        except OSError:
            pass
