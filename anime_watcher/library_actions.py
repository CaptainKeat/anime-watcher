from __future__ import annotations

import ctypes
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from .organizer import VIDEO_EXTENSIONS, safe_component, matching_subtitle_files
from .youtube_library import read_youtube_metadata, youtube_metadata_path


LANGUAGES = {"Sub", "Dub", "Unknown"}


def episode_bundle_plan(source: Path, destination: Path) -> list[tuple[Path, Path]]:
    plans = [(source, destination)]
    for companion in matching_subtitle_files(source):
        plans.append((companion, destination.with_name(destination.stem + companion.name[len(source.stem):])))
    for old, new in ((youtube_metadata_path(source), youtube_metadata_path(destination)),
                     (source.with_name(source.name + ".source.json"), destination.with_name(destination.name + ".source.json"))):
        if old.is_file():
            plans.append((old, new))
    return plans


def move_episode_bundle(source: str | Path, destination: str | Path, library_root: str | Path) -> Path:
    """Move video, subtitles, and YouTube provenance together; roll back failures."""
    source, destination = Path(source), Path(destination)
    if not source.is_file():
        raise FileNotFoundError("The episode file no longer exists")
    if not is_within_library(source, library_root) or not is_within_library(destination, library_root):
        raise ValueError("The episode move must stay inside the configured library")
    if source.resolve() == destination.resolve():
        return source
    plans = episode_bundle_plan(source, destination)
    for _, target in plans:
        if target.exists():
            raise FileExistsError(f"A file already exists at:\n{target}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    moved = []
    try:
        for old, new in plans:
            shutil.move(str(old), str(new))
            moved.append((old, new))
    except Exception:
        for old, new in reversed(moved):
            old.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(new), str(old))
        raise
    for folder in (source.parent, source.parent.parent):
        if not is_within_library(folder, library_root) or folder.resolve() == Path(library_root).resolve():
            continue
        try:
            folder.rmdir()
        except OSError:
            pass
    return destination


def move_library_episode(db, library_root: str | Path, episode_id: int, title: str,
                         season: int, episode: int) -> int:
    row = db.episode(episode_id)
    if row is None:
        raise ValueError("The episode is no longer in your library")
    if not title.strip() or not 0 <= season <= 999 or not 0 <= episode <= 9999:
        raise ValueError("Enter a series name and valid season/episode numbers.")
    title = safe_component(title)
    source = Path(row["path"])
    current_series = db.get_series(int(row["series_id"]))
    if current_series["title"].casefold() == title.casefold() and int(row["season"]) == season and int(row["episode"]) == episode:
        return int(row["series_id"])
    occupied = db.connection.execute(
        "SELECT e.id FROM episodes e JOIN series s ON s.id=e.series_id WHERE s.title=? COLLATE NOCASE AND e.season=? AND e.episode=? AND e.id<>?",
        (title, season, episode, episode_id),
    ).fetchone()
    if occupied:
        raise FileExistsError(f"Season {season}, episode {episode} already exists in {title}. Choose a different slot.")
    # Keep the video title/ID when moving YouTube videos; ordinary episodes use
    # the established series/season/episode convention.
    if source.name.startswith("YouTube - ") or read_youtube_metadata(source):
        tail = re.sub(r"^YouTube\s*-\s*S\d+E\d+\s*-\s*", "", source.stem, flags=re.I)
        destination = Path(library_root) / title / f"Season {season:02d}" / f"YouTube - S{season:02d}E{episode:02d} - {tail}{source.suffix}"
    else:
        destination = episode_destination(library_root, title, season, episode, str(row["language"]), source.suffix)
    moved = move_episode_bundle(source, destination, library_root)
    try:
        return db.relocate_episode(episode_id, moved, title, season, episode, str(row["language"]))
    except Exception:
        if moved != source:
            move_episode_bundle(moved, source, library_root)
        raise


def is_within_library(path: str | Path, library_root: str | Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(library_root).resolve())
        return True
    except (OSError, ValueError):
        return False


@dataclass(frozen=True)
class EpisodeMove:
    episode_id: int
    source: Path
    destination: Path
    season: int
    episode: int
    language: str


def plan_library_episode_moves(db, library_root: str | Path, episode_ids: Iterable[int],
                               title: str, season: int | None = None,
                               start_episode: int | None = None) -> list[EpisodeMove]:
    """Validate the whole batch before moving any video or companion file."""
    if not title.strip():
        raise ValueError("Enter a series name.")
    title = safe_component(title)
    ids = set(map(int, episode_ids))
    if not ids or not title or (season is not None and not 0 <= season <= 999):
        raise ValueError("Select episodes, enter a series name, and choose a valid season.")
    if start_episode is not None and not 0 <= start_episode <= 9999:
        raise ValueError("The first episode number must be between 0 and 9999.")
    rows = [db.episode(eid) for eid in ids]
    if any(row is None for row in rows):
        raise ValueError("An episode is no longer in your library. Refresh the selection.")
    rows.sort(key=lambda row: (row["series_id"], row["season"], row["episode"], row["language"], row["path"]))
    groups = list(dict.fromkeys((row["series_id"], row["season"], row["episode"]) for row in rows))
    numbers = {group: start_episode + index for index, group in enumerate(groups)} if start_episode is not None else {}
    target = db.connection.execute("SELECT id,title FROM series WHERE title=? COLLATE NOCASE", (title,)).fetchone()
    if target:
        title = target["title"]
    occupied = {(row["season"], row["episode"]) for row in db.episodes(target["id"]) if row["id"] not in ids} if target else set()
    slots, destinations, companions, companion_sources, plans = {}, set(), set(), set(), []
    for row in rows:
        source = Path(row["path"])
        if not source.is_file() or not is_within_library(source, library_root):
            raise ValueError(f"Episode is missing or outside the configured library:\n{source}")
        group = (row["series_id"], row["season"], row["episode"])
        new_season = int(row["season"]) if season is None else season
        number = numbers.get(group, int(row["episode"]))
        if not 0 <= new_season <= 999 or not 0 <= number <= 9999:
            raise ValueError("The batch exceeds the supported season or episode numbers. Nothing was moved.")
        slot = (new_season, number)
        unchanged_slot = target is not None and group == (target["id"], new_season, number)
        if (slot in occupied and not unchanged_slot) or (slot in slots and slots[slot] != group):
            raise FileExistsError(f"Season {new_season}, episode {number} already exists in {title}. Nothing was moved.")
        slots[slot] = group
        language = str(row["language"])
        if source.name.startswith("YouTube - ") or read_youtube_metadata(source):
            tail = re.sub(r"^YouTube\s*-\s*S\d+E\d+\s*-\s*", "", source.stem, flags=re.I)
            destination = Path(library_root) / title / f"Season {new_season:02d}" / f"YouTube - S{new_season:02d}E{number:02d} - {tail}{source.suffix}"
        else:
            destination = episode_destination(library_root, title, new_season, number, language, source.suffix)
            quality = re.search(r"\[(\d{3,4}p|Source)\]", source.stem, re.I)
            if quality:
                destination = destination.with_name(f"{destination.stem} [{quality[1]}]{destination.suffix}")
        # Keep selected versions of the same slot, including alternate encodes.
        base = destination
        index = 2
        while str(destination.resolve()).casefold() in destinations:
            destination = base.with_name(f"{base.stem} ({index}){base.suffix}")
            index += 1
        destinations.add(str(destination.resolve()).casefold())
        for old, new in episode_bundle_plan(source, destination):
            if not is_within_library(old, library_root) or not is_within_library(new, library_root):
                raise ValueError("The episode and its companions must stay inside the configured library.")
            key = str(new.resolve()).casefold()
            source_key = str(old.resolve()).casefold()
            if key in companions or source_key in companion_sources or (new.exists() and old.resolve() != new.resolve()):
                raise FileExistsError(f"A file already exists at:\n{new}\nNothing was moved.")
            companions.add(key)
            companion_sources.add(source_key)
        plans.append(EpisodeMove(int(row["id"]), source, destination, new_season, number, language))
    return plans


def move_library_episodes(db, library_root: str | Path, episode_ids: Iterable[int],
                          title: str, season: int | None = None,
                          start_episode: int | None = None) -> int:
    plans = plan_library_episode_moves(db, library_root, episode_ids, title, season, start_episode)
    # Reuse the canonical destination title, including an existing title's case.
    title = plans[0].destination.relative_to(Path(library_root)).parts[0]
    moved = []
    try:
        for plan in plans:
            move_episode_bundle(plan.source, plan.destination, library_root)
            if plan.source.resolve() != plan.destination.resolve():
                moved.append(plan)
        return db.relocate_episodes(title, plans)
    except Exception as exc:
        failures = []
        for plan in reversed(moved):
            try:
                move_episode_bundle(plan.destination, plan.source, library_root)
            except Exception as rollback_error:
                failures.append(f"{plan.destination}: {rollback_error}")
        if failures:
            raise RuntimeError(f"Move failed: {exc}\nSome files could not be restored:\n" + "\n".join(failures)) from exc
        raise


def plan_episode_version_update(db, library_root: str | Path, episode_id: int,
                                season: int, episode: int, language: str) -> EpisodeMove:
    """Correct one file's episode identity, allowing explicit version grouping."""
    row = db.episode(episode_id)
    if row is None:
        raise ValueError("The episode is no longer in your library.")
    source = Path(row["path"])
    if not source.is_file() or not is_within_library(source, library_root):
        raise ValueError("The episode is missing or outside the configured library.")
    destination = episode_destination(library_root, row["series_title"], season, episode, language, source.suffix)
    quality = re.search(r"\[(\d{3,4}p|Source)\]", source.stem, re.I)
    if quality:
        destination = destination.with_name(f"{destination.stem} [{quality[1]}]{destination.suffix}")
    # Do not discard a custom filename when no identity correction is needed.
    if (int(row["season"]), int(row["episode"]), row["language"]) == (season, episode, language):
        destination = source
    for old, new in episode_bundle_plan(source, destination):
        if not is_within_library(old, library_root) or not is_within_library(new, library_root):
            raise ValueError("The episode and its companions must stay inside the configured library.")
        if new.exists() and old.resolve() != new.resolve():
            raise FileExistsError(f"A version already uses this filename:\n{new}\nNo files will be replaced.")
    return EpisodeMove(episode_id, source, destination, season, episode, language)


def update_episode_version(db, library_root: str | Path, episode_id: int,
                           season: int, episode: int, language: str) -> int:
    plan = plan_episode_version_update(db, library_root, episode_id, season, episode, language)
    title = db.episode(episode_id)["series_title"]
    move_episode_bundle(plan.source, plan.destination, library_root)
    try:
        return db.relocate_episodes(title, [plan])
    except Exception:
        if plan.source.resolve() != plan.destination.resolve():
            move_episode_bundle(plan.destination, plan.source, library_root)
        raise


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

    return move_episode_bundle(source, destination, root)


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
            move_episode_bundle(source, destination, root)
            moved.append((source, destination))
    except Exception:
        for source, destination in reversed(moved):
            try:
                move_episode_bundle(destination, source, root)
            except OSError:
                pass
        raise

    for folder in sorted(old_folders, key=lambda item: len(item.parts), reverse=True):
        try:
            folder.rmdir()
        except OSError:
            pass
    return plans


def rollback_series_files(plans: Mapping[int, tuple[Path, Path]], library_root: str | Path | None = None) -> None:
    for source, destination in reversed(list(plans.values())):
        if destination == source or not destination.exists() or source.exists():
            continue
        root = Path(library_root) if library_root is not None else Path(os.path.commonpath([source, destination]))
        move_episode_bundle(destination, source, root)


def send_to_recycle_bin(path: str | Path, library_root: str | Path, *, recovery_folder=False) -> None:
    target = Path(path)
    if recovery_folder:
        from .library_extras import _validate_recovery
        _validate_recovery(library_root, target)
    if not target.exists() or not (target.is_dir() if recovery_folder else target.is_file()):
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
