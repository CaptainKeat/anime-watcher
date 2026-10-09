"""Reviewed imports with recoverable media changes and atomic library updates."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .library_actions import episode_bundle_plan, episode_destination, is_within_library, send_to_recycle_bin
from .organizer import DOWNLOAD_STAGING_DIRECTORY, VIDEO_EXTENSIONS, parse_episode, safe_component
from .media_chapters import find_ffprobe
from .media_quality import quality_label
from .ui_common import library_root_from_setting


@dataclass(frozen=True)
class ImportEntry:
    source: Path
    title: str
    season: int
    episode: int
    language: str
    replace: bool = False
    replace_id: int | None = None


def suggested_imports(paths):
    entries = []
    seen = set()
    for value in paths:
        path = Path(value).resolve()
        if path in seen or not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        seen.add(path)
        info = parse_episode(path)
        entries.append(ImportEntry(path, info.title, info.season, info.episode, info.language))
    return sorted(entries, key=lambda item: (item.title.casefold(), item.season, item.episode, item.source.name))


def verified_media(path):
    """Inspect the actual video; filename quality labels are never evidence."""
    probe = find_ffprobe()
    if not probe:
        raise ValueError('FFprobe is required to verify an episode replacement.')
    result = subprocess.run([probe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                            capture_output=True, text=True, timeout=20,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise ValueError('The replacement video could not be verified. Keep it as an additional copy instead.')
    data = json.loads(result.stdout)
    video = next((stream for stream in data.get('streams', []) if stream.get('codec_type') == 'video'
                  and not stream.get('disposition', {}).get('attached_pic')), {})
    width, height = int(video.get('width', 0)), int(video.get('height', 0))
    duration = float(data.get('format', {}).get('duration') or video.get('duration') or 0)
    if width <= 0 or height <= 0 or duration <= 0:
        raise ValueError('The video has no verifiable picture or duration.')
    audio = any(stream.get('codec_type') == 'audio' for stream in data.get('streams', []))
    return width, height, round(duration * 1000), audio


def _digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _install_copy(source, destination):
    """Install on the library volume without ever replacing a late-arriving file."""
    if os.name == 'nt':
        os.rename(source, destination)  # Windows rename refuses an existing target.
    else:
        os.link(source, destination)
        source.unlink()


def import_reviewed(db, root, entries, *, library_type='Anime', recycle=False, progress=None):
    """Keep source files until commit; roll back all installed and displaced bundles."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError('The library folder is unavailable.')
    if library_type not in {'Anime', 'YouTube'} or not entries:
        raise ValueError('Select at least one video to import.')
    plans, claimed, sources, replaced = [], set(), set(), set()
    for entry in entries:
        source = Path(entry.source).resolve()
        if source in sources or not source.is_file() or source.suffix.lower() not in VIDEO_EXTENSIONS:
            raise ValueError('A selected video is missing or was selected twice.')
        if is_within_library(source, root):
            raise ValueError('Use Move to series or Manage versions for files already in this library.')
        sources.add(source)
        if not entry.title.strip() or safe_component(entry.title) != entry.title.strip():
            raise ValueError('Enter a series name without reserved filename characters.')
        title = entry.title.strip()
        series = db.series_for_title(title)
        if series:
            title = series['title']
        destination = episode_destination(root, title, entry.season, entry.episode, entry.language, source.suffix)
        old = None; old_identity = None
        duration = 0
        if entry.replace:
            matches = [row for row in db.episodes(series['id']) if (row['season'], row['episode'], row['language']) ==
                       (entry.season, entry.episode, entry.language)] if series else []
            if entry.replace_id is not None:
                matches = [row for row in matches if row['id'] == entry.replace_id]
            if len(matches) != 1:
                raise ValueError(f'{title} S{entry.season:02d}E{entry.episode:02d} {entry.language}: choose one existing version to replace, or Keep copy.')
            old = matches[0]
            old_path = Path(old['path'])
            if old['id'] in replaced or not old_path.is_file() or not is_within_library(old_path, root):
                raise ValueError('The existing episode is unavailable or selected for replacement twice.')
            replaced.add(old['id'])
            old_stat = old_path.stat(); old_identity = (old_stat.st_size, old_stat.st_mtime_ns)
            new_width, new_height, duration, new_audio = verified_media(source)
            old_width, old_height, old_duration, old_audio = verified_media(old_path)
            if new_width * new_height <= old_width * old_height:
                raise ValueError(f'{source.name}: replacement must have a higher verified resolution. Choose Keep copy to retain another encode.')
            if not 0.8 <= duration / old_duration <= 1.25:
                raise ValueError(f'{source.name}: durations differ substantially; check the episode before replacing it.')
            if old_audio and not new_audio:
                raise ValueError(f'{source.name}: the existing episode has audio but this replacement does not.')
            stem = re.sub(r'\s*\[(?:\d{3,4}p|Source)\]', '', old_path.stem, flags=re.I)
            destination = old_path.with_name(f'{stem} [{quality_label(new_width, new_height)}]{source.suffix}')
        else:
            base, number = destination, 2
            while destination.exists() or str(destination).casefold() in claimed:
                destination = base.with_name(f'{base.stem} ({number}){base.suffix}')
                number += 1
        old_bundle = episode_bundle_plan(Path(old['path']), Path(old['path'])) if old else []
        old_sources = {path.resolve() for path, _ in old_bundle}
        incoming = episode_bundle_plan(source, destination)
        # Preserve existing subtitles when the replacement has no corresponding subtitle.
        new_names = {target.name.casefold() for _, target in incoming}
        retained = []
        if old:
            for old_file, new_file in episode_bundle_plan(Path(old['path']), destination)[1:]:
                if old_file.suffix.lower() in {'.srt', '.vtt', '.ass', '.ssa'} and new_file.name.casefold() not in new_names:
                    retained.append((old_file, new_file))
        for _, target in incoming + retained:
            key = str(target.resolve()).casefold()
            if not is_within_library(target, root) or key in claimed or (target.exists() and target.resolve() not in old_sources):
                raise FileExistsError(f'Import destination or companion already exists: {target.name}')
            claimed.add(key)
        plans.append((entry, title, destination, old, duration, incoming, retained, old_bundle, old_identity))

    staging = root / DOWNLOAD_STAGING_DIRECTORY / 'imports' / uuid4().hex
    staging.mkdir(parents=True)
    installed, displaced, copied, source_receipts = [], [], [], []
    committed = False
    try:
        # Copy and verify everything before displacing any existing video.
        for index, (_, _, _, _, _, incoming, retained, _, _) in enumerate(plans):
            for item, (source, target) in enumerate(incoming + retained):
                if progress:
                    progress(index, len(plans), f'Verifying copy {index + 1} of {len(plans)}…')
                stat = source.stat()
                temporary = staging / 'new' / str(index) / str(item) / target.name
                temporary.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, temporary)
                digest = _digest(temporary)
                after = source.stat()
                if (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or digest != _digest(source):
                    raise OSError(f'The source changed or the copy failed verification: {source.name}')
                copied.append((temporary, target))
                if (source, target) in incoming:
                    source_receipts.append((source, after.st_size, after.st_mtime_ns, digest))
        with db.connection:
            db.connection.execute('BEGIN IMMEDIATE')
            configured = library_root_from_setting(db.setting('library_root', str(root)))
            if configured is None or configured.resolve() != root:
                raise ValueError('The library folder changed during the import; originals were retained.')
            for _, _, _, old, _, _, _, _, identity in plans:
                if old:
                    current = db.episode(old['id']); stat = Path(old['path']).stat()
                    if not current or current['path'] != old['path'] or (stat.st_size, stat.st_mtime_ns) != identity:
                        raise ValueError('An existing episode changed during verification. Review the import again.')
            for index, (_, _, _, _, _, _, _, bundle, _) in enumerate(plans):
                for old, _ in bundle:
                    backup = staging / 'old' / str(index) / old.name
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(old), str(backup)); displaced.append((old, backup))
            for temporary, target in copied:
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    raise FileExistsError(f'A file appeared at the destination: {target.name}')
                _install_copy(temporary, target); installed.append(target)
            for entry, title, destination, old, duration, *_ in plans:
                db.connection.execute('INSERT OR IGNORE INTO series(title,library_type) VALUES(?,?)', (title, library_type))
                sid = db.connection.execute('SELECT id FROM series WHERE title=? COLLATE NOCASE', (title,)).fetchone()['id']
                if old:
                    db.connection.execute('UPDATE episodes SET path=?,duration_ms=? WHERE id=?', (str(destination), duration, old['id']))
                else:
                    db.connection.execute('INSERT INTO episodes(series_id,season,episode,title,path,language) VALUES(?,?,?,?,?,?)',
                                          (sid, entry.season, entry.episode, f'Episode {entry.episode}', str(destination), entry.language))
                if library_type == 'YouTube':
                    db.connection.execute("UPDATE series SET library_type='YouTube' WHERE id=?", (sid,))
        committed = True
    finally:
        if not committed:
            for target in reversed(installed):
                target.unlink(missing_ok=True)
            for old, backup in reversed(displaced):
                old.parent.mkdir(parents=True, exist_ok=True)
                try:
                    _install_copy(backup, old)
                except OSError as exc:
                    raise OSError(f'Original copy retained at {backup}; could not restore its previous path: {exc}') from exc
    # A committed import is never undone just because cleanup fails.
    warnings = []
    for source, size, modified, digest in source_receipts:
        try:
            stat = source.stat()
            if (stat.st_size, stat.st_mtime_ns) != (size, modified) or _digest(source) != digest:
                warnings.append(f'Source changed; retained {source.name}')
            else:
                source.unlink()
        except OSError:
            warnings.append(f'Original retained: {source.name}')
    if recycle:
        for _, backup in displaced:
            try:
                send_to_recycle_bin(backup, root)
            except OSError:
                warnings.append(f'Old copy retained: {backup}')
    recovery = staging / 'old'
    return {'imported': len(plans), 'replaced': len(replaced), 'warnings': warnings,
            'recovery': str(recovery) if recovery.exists() and any(recovery.rglob('*')) else None}
