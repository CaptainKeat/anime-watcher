"""Local next episodes, source completeness, and per-profile SQLite backups."""
from __future__ import annotations

import json
import sqlite3
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
    if kind not in {'manual', 'automatic', 'before-restore'}:
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
