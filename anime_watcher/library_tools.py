"""Local next episodes, source completeness, and per-profile SQLite backups."""
from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
from collections import defaultdict
from pathlib import Path
from uuid import uuid4

from .ui_common import choose_episode_variant


def up_next(db):
    result = []
    for series in db.series():
        grouped = defaultdict(list)
        for row in db.episodes(series['id']):
            grouped[(row['season'], row['episode'])].append(row)
        for _, versions in sorted(grouped.items()):
            if any(row['completed'] for row in versions):
                continue
            # Resume an already-started variant before switching language.
            started = [row for row in versions if row['progress_ms'] > 0]
            selected = max(started, key=lambda row: row['last_watched'] or '') if started else choose_episode_variant(versions, db.series_language_preference(series['id']))
            result.append(db.episode(selected['id']))
            break
    return result


def catalog_key(title):
    return 'expected_episodes:' + str(title).strip().casefold()


def remember_catalog(db, title, episodes):
    rows = []
    seen = set()
    for item in episodes:
        if item.season is None or item.number is None or item.language not in {'Sub', 'Dub'}:
            continue
        if not str(item.number).isdigit() or not 0 <= int(item.number) <= 9999 or not 0 <= item.season <= 999:
            continue
        number = int(item.number)
        key = (item.season, number, item.language)
        if key not in seen:
            seen.add(key)
            rows.append(dict(title=item.title, url=item.url, season=item.season, number=number, language=item.language))
    if rows:
        # Union preserves the other language when a source lists Sub and Dub separately.
        previous = db.setting(catalog_key(title), {})
        combined = {(row['season'], row['number'], row['language']): row for row in previous.get('episodes', [])} if isinstance(previous, dict) else {}
        combined.update({(row['season'], row['number'], row['language']): row for row in rows})
        db.set_setting(catalog_key(title), {'checked_at': time.time(), 'episodes': list(combined.values())})


def season_completeness(db, series_id):
    series = db.get_series(series_id)
    if not series:
        return []
    cache = db.setting(catalog_key(series['title']), {})
    expected = cache.get('episodes', []) if isinstance(cache, dict) else []
    local = defaultdict(set); source = defaultdict(dict)
    for row in db.episodes(series_id):
        if Path(row['path']).is_file():
            local[(row['season'], row['language'])].add(row['episode'])
    for row in expected:
        source[(row['season'], row['language'])][row['number']] = row
    result = []
    for season, language in sorted(local.keys() | source.keys()):
        have = local[(season, language)]
        confirmed = source[(season, language)]
        if confirmed:
            missing = sorted(set(confirmed) - have)
        else:
            missing = sorted(set(range(1, max(have, default=0) + 1)) - have)
        result.append(dict(season=season, language=language, have=len(have), total=len(confirmed) if confirmed else None,
                           missing=missing, links=[confirmed[number] for number in missing] if confirmed else [],
                           checked_at=cache.get('checked_at') if confirmed else None))
    return result


def backup_directory(data_root, profile_id):
    # Profile IDs come from the registry, but keep path confinement explicit.
    if not profile_id or any(character not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for character in profile_id):
        raise ValueError('Invalid backup profile.')
    return Path(data_root) / 'backups' / profile_id


def backup_library(db, data_root, profile_id, *, kind='manual'):
    if kind not in {'manual', 'automatic', 'before-restore', 'before-transfer'}:
        raise ValueError('Invalid backup kind.')
    directory = backup_directory(data_root, profile_id); directory.mkdir(parents=True, exist_ok=True)
    if kind == 'automatic':
        day = time.strftime('%Y-%m-%d')
        if any(directory.glob(day + '*-automatic-*.sqlite')):
            return None
    path = directory / (time.strftime('%Y-%m-%d_%H-%M-%S') + f'-{kind}-{uuid4().hex[:8]}.sqlite')
    temporary = path.with_suffix('.tmp')
    target = sqlite3.connect(temporary)
    try:
        db.connection.backup(target)
        with target:
            identity = json.dumps({'profile_id': profile_id, 'kind': kind, 'created_at': time.time()})
            target.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)', ('__backup_identity', identity))
        if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('The backup did not pass verification.')
    finally:
        target.close()
    temporary.replace(path)
    if kind == 'automatic':
        for old in sorted(directory.glob('*-automatic-*.sqlite'), reverse=True)[7:]:
            old.unlink()
    return path


def inspect_backup(path, profile_id):
    path = Path(path).resolve()
    if not path.is_file() or path.stat().st_size > 256 * 1024 * 1024:
        raise ValueError('Choose a valid library backup smaller than 256 MB.')
    source = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    try:
        return _inspect_backup_connection(source, profile_id)
    finally:
        source.close()


TRANSFER_MARKER = '.anime-watcher-transfer.json'


class TransferPaused(Exception):
    pass


def _transfer_inventory(root):
    """Reject links and unreadable entries rather than silently omitting media."""
    from .organizer import DOWNLOAD_STAGING_DIRECTORY
    result = {}
    def visit(directory):
        with os.scandir(directory) as entries:
            for entry in sorted(entries, key=lambda item: item.name.casefold()):
                if directory == root and entry.name in {TRANSFER_MARKER, TRANSFER_MARKER + '.tmp', DOWNLOAD_STAGING_DIRECTORY}:
                    continue
                stat = entry.stat(follow_symlinks=False)
                if entry.is_symlink() or getattr(stat, 'st_file_attributes', 0) & 0x400:
                    raise ValueError(f'Linked folders or files cannot be transferred: {entry.path}')
                if entry.is_dir(follow_symlinks=False):
                    visit(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    result[Path(entry.path).relative_to(root).as_posix()] = [stat.st_size, stat.st_mtime_ns]
                else:
                    raise ValueError(f'Unsupported file: {entry.path}')
    visit(root)
    return result


def _transfer_no_links(path):
    for part in (path, *path.parents):
        if part.exists() and (part.is_symlink() or getattr(part.stat(follow_symlinks=False), 'st_file_attributes', 0) & 0x400):
            raise ValueError('Choose folders on real drives, without linked folders.')


def _transfer_roots(source, destination):
    source, destination = Path(source), Path(destination)
    if not source.is_absolute() or not destination.is_absolute():
        raise ValueError('Choose absolute library folder paths.')
    # Resolve only after detecting reparse points along both original paths.
    for path in (source, destination):
        _transfer_no_links(path)
    source, destination = source.resolve(), destination.resolve()
    if source == Path(source.anchor) or destination == Path(destination.anchor):
        raise ValueError('Choose a library folder, not an entire drive.')
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError('The source and destination folders must be separate.')
    if not source.is_dir():
        raise ValueError('The current library drive is unavailable.')
    if not destination.parent.is_dir():
        raise ValueError('Choose an existing destination drive or parent folder.')
    return source, destination


def _transfer_owner(database, source, destination):
    return dict(database=str(Path(database).resolve()), source=str(source), destination=str(destination))


def _check_transfer_target(destination, owner, files):
    if not destination.exists():
        return
    if not destination.is_dir():
        raise ValueError('The destination is already a file.')
    marker = destination / TRANSFER_MARKER
    if any(destination.iterdir()):
        if not marker.is_file():
            raise ValueError('Choose an empty folder. Existing unrelated files will not be overwritten.')
        try:
            journal = json.loads(marker.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            raise ValueError('The transfer journal is unreadable. Choose a new empty folder.') from None
        if journal.get('owner') != owner or journal.get('files') != files:
            raise ValueError('This folder belongs to a different or changed transfer. Choose a new empty folder.')
        if set(_transfer_inventory(destination)) - set(files):
            raise ValueError('The destination contains additional files. Choose a new empty folder.')


def prepare_library_transfer(database, source, destination):
    source, destination = _transfer_roots(source, destination)
    files = _transfer_inventory(source)
    if not files:
        raise ValueError('The library folder has no files to transfer.')
    owner = _transfer_owner(database, source, destination)
    _check_transfer_target(destination, owner, files)
    free = shutil.disk_usage(destination.parent).free
    # A resume can already occupy space, including a preallocated partial video.
    present = _transfer_inventory(destination) if destination.exists() else {}
    needed = sum(max(0, size - present.get(name, [0])[0]) for name, (size, _) in files.items())
    if free < needed + 16 * 1024 * 1024:
        raise ValueError('The destination does not have enough free space for this library.')
    connection = sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        row = connection.execute("SELECT value FROM settings WHERE key='library_root'").fetchone()
        if not row or Path(json.loads(row[0])).resolve() != source:
            raise ValueError('The selected library changed. Review the transfer again.')
        episodes = [list(row) for row in connection.execute('SELECT id,path FROM episodes ORDER BY id')]
    finally:
        connection.close()
    missing = sum(Path(path).is_relative_to(source) and not Path(path).is_file() for _, path in episodes)
    return dict(owner=owner, files=files, episodes=episodes, total=sum(size for size, _ in files.values()),
                free=free, missing=missing)


def _transfer_check_cancel(cancel):
    if cancel.is_set():
        raise TransferPaused('Transfer paused. The original library is still selected; choose the same destination to resume.')


def _transfer_hash(path, cancel, progress):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(4 * 1024 * 1024):
            _transfer_check_cancel(cancel)
            digest.update(block)
            progress(len(block))
    return digest.digest()


def _robocopy_file(source, target, cancel, progress, *, force=False):
    """Copy one literal file; no shell, recursion, purge, or source deletion."""
    command = ['robocopy', str(source.parent), str(target.parent), source.name,
               '/J', '/Z', '/R:2', '/W:1', '/COPY:DAT', '/DCOPY:DAT', '/UNICODE', '/NJH', '/NJS', '/NDL']
    if force:
        command.extend(['/IS', '/IT'])
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    chunks = []
    def read_output():
        while block := process.stdout.read1(4096):
            chunks.append(block)
    reader = threading.Thread(target=read_output, daemon=True); reader.start()
    output = bytearray(); consumed = 0
    try:
        while process.poll() is None:
            _transfer_check_cancel(cancel)
            while consumed < len(chunks):
                output.extend(chunks[consumed]); consumed += 1
            # Robocopy /UNICODE writes UTF-16; tolerate odd trailing byte chunks.
            decoded = bytes(output).decode('utf-16-le', errors='ignore')
            percentages = re.findall(r'(\d+(?:[.,]\d+)?)%', decoded)
            if percentages:
                progress(min(1.0, float(percentages[-1].replace(',', '.')) / 100))
            time.sleep(0.1)
        reader.join(timeout=5)
        while consumed < len(chunks):
            output.extend(chunks[consumed]); consumed += 1
        _transfer_check_cancel(cancel)
        if process.returncode >= 8:
            detail = bytes(output).decode('utf-16-le', errors='replace').strip()[-1800:]
            raise OSError(f'Robocopy could not copy {source.name} (code {process.returncode}). {detail}')
        progress(1.0)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)
        reader.join(timeout=5)
        process.stdout.close()


def transfer_library(database, plan, data_root, profile_id, cancel, progress, *, copier=None):
    """Verify every file, then atomically remap paths without reindexing episodes."""
    from .database import LibraryDatabase
    import msvcrt
    import ctypes
    copier = copier or _robocopy_file
    source, destination = _transfer_roots(plan['owner']['source'], plan['owner']['destination'])
    if plan['owner'] != _transfer_owner(database, source, destination):
        raise ValueError('Transfer owner changed.')
    lock_dir = backup_directory(data_root, profile_id).parent / 'transfers'
    lock_dir.mkdir(parents=True, exist_ok=True)
    # Serialize across profiles too: two profiles can share a media drive.
    lock = (lock_dir / 'library-transfer.lock').open('a+b')
    db = None; locked = False
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
    try:
        if lock.tell() == 0:
            lock.write(b'0'); lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1); locked = True
        except OSError:
            raise ValueError('Another library transfer is already running.') from None
        fresh = prepare_library_transfer(database, source, destination)
        if fresh['files'] != plan['files'] or fresh['episodes'] != plan['episodes']:
            raise ValueError('The library changed after review. Review the transfer again.')
        _transfer_check_cancel(cancel)
        db = LibraryDatabase(database)
        backup = backup_library(db, data_root, profile_id, kind='before-transfer')
        destination.mkdir(exist_ok=True)
        marker = destination / TRANSFER_MARKER
        journal = dict(owner=plan['owner'], files=plan['files'], backup=str(backup), state='copying')
        def save_journal():
            temporary = marker.with_suffix('.tmp')
            temporary.write_text(json.dumps(journal, ensure_ascii=False), encoding='utf-8')
            temporary.replace(marker)
        save_journal()
        done = 0; verified_stats = {}; total = plan['total']; started = time.monotonic()
        def emit(phase, name, amount):
            elapsed = max(.001, time.monotonic() - started)
            progress(dict(phase=phase, file=name, completed=done, current=amount, total=total,
                          elapsed=elapsed, index=len(verified_stats) + 1, count=len(plan['files'])))
        for name, (size, modified) in plan['files'].items():
            _transfer_check_cancel(cancel)
            original, target = source / name, destination / name
            _transfer_no_links(original); _transfer_no_links(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            checked = 0
            def hash_progress(amount):
                nonlocal checked
                checked += amount
                emit('Verifying SHA-256', name, min(size, checked // 2))
            matching = False
            if target.is_file() and target.stat().st_size == size:
                emit('Verifying SHA-256', name, 0)
                matching = _transfer_hash(original, cancel, hash_progress) == _transfer_hash(target, cancel, hash_progress)
            if not matching:
                emit('Copying', name, 0)
                copier(original, target, cancel, lambda fraction: emit('Copying', name, int(size * fraction)), force=target.exists())
                checked = 0
                if _transfer_hash(original, cancel, hash_progress) != _transfer_hash(target, cancel, hash_progress):
                    raise ValueError(f'Verification failed for {name}. The original library is still selected.')
            stat = original.stat()
            if [stat.st_size, stat.st_mtime_ns] != [size, modified]:
                raise ValueError(f'The source changed while copying: {name}.')
            stat = target.stat(); verified_stats[name] = [stat.st_size, stat.st_mtime_ns]
            done += size; emit('Verified', name, 0)
        _transfer_check_cancel(cancel)
        if _transfer_inventory(source) != plan['files'] or _transfer_inventory(destination) != verified_stats:
            raise ValueError('Files changed during the transfer. The original library is still selected.')
        db.connection.execute('BEGIN IMMEDIATE')
        try:
            if Path(db.setting('library_root', '')).resolve() != source or [list(row) for row in db.connection.execute('SELECT id,path FROM episodes ORDER BY id')] != plan['episodes']:
                raise ValueError('The library changed during the transfer. The original library is still selected.')
            for episode_id, path in plan['episodes']:
                old = Path(path)
                if old.is_relative_to(source):
                    db.connection.execute('UPDATE episodes SET path=? WHERE id=?', (str(destination / old.relative_to(source)), episode_id))
            for series_id, path in db.connection.execute("SELECT id,poster_path FROM series WHERE poster_path IS NOT NULL").fetchall():
                old = Path(path)
                if old.is_relative_to(source):
                    db.connection.execute('UPDATE series SET poster_path=? WHERE id=?', (str(destination / old.relative_to(source)), series_id))
            db.connection.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)', ('library_root', json.dumps(str(destination))))
            _transfer_check_cancel(cancel)
            db.connection.commit()
        except Exception:
            db.connection.rollback(); raise
        journal['state'] = 'complete'
        warning = ''
        try:
            save_journal()
        except OSError as exc:
            warning = f'Library switched successfully, but the transfer receipt could not be saved: {exc}'
        return dict(source=str(source), destination=str(destination), files=len(plan['files']), total=total, backup=str(backup), warning=warning)
    finally:
        if db is not None:
            db.close()
        if locked:
            lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        lock.close()
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)


def _inspect_backup_connection(source, profile_id):
    source.execute('PRAGMA trusted_schema=OFF')
    tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'series', 'episodes', 'settings', 'airing_calendar', 'public_airing_calendar', 'notifications'} <= tables:
        raise ValueError('This file is not an Anime Watcher library backup.')
    if source.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view')").fetchone():
        raise ValueError('Backups containing unexpected database code cannot be restored.')
    for table, columns in {'series': {'id', 'title', 'display_title', 'synopsis', 'poster_path', 'metadata_id', 'metadata_updated', 'library_type', 'anilist_id', 'anilist_title', 'next_airing_episode', 'next_airing_at', 'release_status', 'release_year', 'metadata_year_checked'},
                           'episodes': {'id', 'series_id', 'season', 'episode', 'title', 'path', 'language', 'duration_ms', 'progress_ms', 'completed', 'last_watched'},
                           'settings': {'key', 'value'}, 'airing_calendar': {'media_id', 'episode', 'airing_at'},
                           'public_airing_calendar': {'media_id', 'episode', 'airing_at', 'title'},
                           'notifications': {'id', 'kind', 'series_id', 'title', 'body', 'fingerprint', 'created_at', 'read'}}.items():
        actual = {row[1] for row in source.execute(f'PRAGMA table_info({table})')}
        if not columns <= actual:
            raise ValueError('This backup has an unsupported library schema.')
    row = source.execute("SELECT value FROM settings WHERE key='__backup_identity'").fetchone()
    identity = json.loads(row[0]) if row else {}
    if not isinstance(identity, dict) or identity.get('profile_id') != profile_id:
        raise ValueError('Choose a backup for the currently selected profile.')
    if not isinstance(identity.get('created_at'), (int, float)) or not 0 < identity['created_at'] < 32503680000:
        raise ValueError('The backup has an invalid creation date.')
    if source.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or source.execute('PRAGMA foreign_key_check').fetchone():
        raise ValueError('The library backup is damaged.')
    return dict(identity, series=source.execute('SELECT count(*) FROM series').fetchone()[0],
                videos=source.execute('SELECT count(*) FROM episodes').fetchone()[0])


def restore_library(db, path, data_root, profile_id):
    inspect_backup(path, profile_id)
    # Validate and restore the same open file, preventing a replacement between steps.
    source = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        source.execute('BEGIN')
        _inspect_backup_connection(source, profile_id)
        recovery = backup_library(db, data_root, profile_id, kind='before-restore')
        try:
            source.backup(db.connection)
            db._migrate()
        except Exception:
            previous = sqlite3.connect(recovery.as_uri() + '?mode=ro', uri=True)
            try:
                previous.backup(db.connection)
            finally:
                previous.close()
            raise
        return recovery
    finally:
        source.close()
