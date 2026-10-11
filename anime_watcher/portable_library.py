"""Portable, verified library snapshots with a local working database."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .library_extras import PORTABLE_DIRECTORY


def _digest(path):
    with Path(path).open('rb') as handle: return hashlib.file_digest(handle, 'sha256').hexdigest()


def _safe_id(value):
    if not isinstance(value,str) or not 1 <= len(value) <= 80 or any(char not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for char in value):
        raise ValueError('Invalid portable profile identity.')
    return value


def _state(root):
    root = Path(root)
    if not root.is_absolute(): raise ValueError('Choose a complete library folder path.')
    for part in (root, *root.parents):
        if part.is_symlink() or (part.exists() and getattr(part.stat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('Portable state requires a real folder, without links.')
    root = root.resolve()
    if not root.is_dir(): raise FileNotFoundError('Drive disconnected — your progress remains in the local working copy.')
    state = root / PORTABLE_DIRECTORY
    if state.is_symlink() or (state.exists() and getattr(state.stat(),'st_file_attributes',0)&0x400): raise ValueError('Portable state requires a real folder, without links.')
    return state


def _read_manifest(root):
    path = _state(root) / 'library.json'
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 1024*1024: raise ValueError('This folder does not contain a portable library.')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value,dict) or value.get('format') != 1 or not isinstance(value.get('profiles'), dict): raise ValueError('Unsupported portable library format.')
    _safe_id(value.get('identity'))
    for key,row in value['profiles'].items():
        _safe_id(key)
        if not isinstance(row,dict) or not isinstance(row.get('sha256'),str) or len(row['sha256']) != 64 or any(char not in '0123456789abcdef' for char in row['sha256']):
            raise ValueError('Portable profile metadata is damaged.')
    return value


def new_portable_record(root,profile):
    state=_state(root); profile=_safe_id(profile)
    if (state/'library.json').exists():
        manifest=_read_manifest(root)
        if profile in manifest['profiles']: raise ValueError('This profile already has a portable snapshot. Use Open portable library to load it into a new local copy.')
        identity=manifest['identity']
    else: identity=uuid4().hex
    return dict(identity=identity,profile=profile,root=str(Path(root)),sha256=None)


def portable_profiles(root):
    manifest = _read_manifest(root)
    return manifest['identity'], [(key, str(row.get('name', key))) for key, row in manifest['profiles'].items() if _safe_id(key)]


@contextmanager
def _exclusive(state):
    state.mkdir(exist_ok=True)
    path = state / 'session.lock'
    with path.open('a+b') as handle:
        if path.stat().st_size == 0: handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc: raise ValueError('Another Anime Watcher instance is syncing this portable library.') from exc
        try: yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _json_write(path, value):
    temp = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    temp.write_text(json.dumps(value, indent=2), encoding='utf-8'); temp.replace(path)


def _map_value(value, transform):
    if isinstance(value, str): return transform(value)
    if isinstance(value, list): return [_map_value(item, transform) for item in value]
    if isinstance(value, dict): return {transform(key): _map_value(item, transform) for key, item in value.items()}
    return value


def _relative(value, root):
    try: relative = Path(value).relative_to(root)
    except (ValueError, TypeError): return value
    return 'portable-media/' + relative.as_posix()


def _expanded(value, root):
    if not value.startswith('portable-media/'): return value
    relative = Path(value[len('portable-media/'):])
    if relative.is_absolute() or '..' in relative.parts: raise ValueError('Portable media path escapes the library.')
    return str(root / relative)


def _settings_transform(connection, transform, *, exporting=False):
    for key, raw in connection.execute('SELECT key,value FROM settings').fetchall():
        if exporting and any(word in key.casefold() for word in ('token', 'cookie', 'password', 'authorization', 'anilist_viewer', 'pending_app_update', '__backup_identity', 'download_history')):
            connection.execute('DELETE FROM settings WHERE key=?', (key,)); continue
        try: value = json.loads(raw)
        except json.JSONDecodeError: continue
        connection.execute('UPDATE settings SET value=? WHERE key=?', (json.dumps(_map_value(value, transform)), key))


def sync_portable(database, root, record, name):
    state = _state(root); root = state.parent
    identity, profile = _safe_id(record['identity']), _safe_id(record['profile'])
    state.mkdir(exist_ok=True)
    with _exclusive(state):
        manifest_path = state / 'library.json'
        manifest = _read_manifest(root) if manifest_path.exists() else dict(format=1, identity=identity, profiles={})
        if manifest['identity'] != identity: raise ValueError('A different portable library is attached. Local progress is preserved.')
        previous = manifest['profiles'].get(profile)
        if previous and previous.get('sha256') != record.get('sha256'):
            raise ValueError('Portable progress changed on another app. Open the portable library again to review its saved state; local progress is preserved.')
        directory = state / 'profiles'; directory.mkdir(exist_ok=True)
        if directory.is_symlink() or getattr(directory.stat(), 'st_file_attributes', 0) & 0x400: raise ValueError('Portable profiles cannot use linked folders.')
        temporary = directory / (profile + '.' + uuid4().hex + '.tmp')
        source = sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)
        target = sqlite3.connect(temporary)
        try:
            source.backup(target)
            with target:
                for episode_id, path in target.execute('SELECT id,path FROM episodes').fetchall():
                    relative = _relative(path, root)
                    if relative == path: raise ValueError('Every episode must be inside the selected library before enabling portable mode.')
                    target.execute('UPDATE episodes SET path=? WHERE id=?', (relative, episode_id))
                artwork = state / 'artwork'; artwork.mkdir(exist_ok=True)
                if artwork.is_symlink() or getattr(artwork.stat(), 'st_file_attributes', 0) & 0x400: raise ValueError('Portable artwork cannot use linked folders.')
                for series_id, path in target.execute('SELECT id,poster_path FROM series WHERE poster_path IS NOT NULL').fetchall():
                    image = Path(path)
                    if image.is_file() and not image.is_symlink() and image.suffix.lower() in {'.jpg','.jpeg','.png','.webp'} and image.stat().st_size <= 20*1024*1024:
                        filename = _digest(image) + image.suffix.lower(); copy = artwork / filename
                        if not copy.exists():
                            temp_image = artwork / (filename + '.tmp'); shutil.copyfile(image, temp_image); temp_image.replace(copy)
                        target.execute('UPDATE series SET poster_path=? WHERE id=?', ('portable-artwork/' + filename, series_id))
                    else: target.execute('UPDATE series SET poster_path=NULL WHERE id=?', (series_id,))
                _settings_transform(target, lambda value: _relative(value, root), exporting=True)
                target.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)', ('library_root', json.dumps('portable-media/')))
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise ValueError('Portable snapshot failed verification.')
        except Exception:
            source.close(); target.close()
            try: temporary.unlink(missing_ok=True)
            except OSError: pass
            raise
        finally: source.close(); target.close()
        # Content-addressed snapshots keep the previous manifest usable if power
        # disappears between writing the database and replacing the manifest.
        digest = _digest(temporary); final = directory / (profile + '-' + digest + '.sqlite')
        temporary.replace(final)
        manifest['profiles'][profile] = dict(name=name, sha256=digest, file=final.name)
        _json_write(manifest_path, manifest)
        keep={final.name, previous.get('file') if previous else None}
        for old in directory.glob(profile+'-*.sqlite'):
            if old.name not in keep and not old.is_symlink():
                try: old.unlink()
                except OSError: pass
        return {**record, 'root':str(root), 'sha256':digest}


def load_portable(root, profile, destination, artwork_root):
    profile = _safe_id(profile); state = _state(root); root = state.parent
    with _exclusive(state):
        manifest = _read_manifest(root); row = manifest['profiles'].get(profile)
        if not row: raise ValueError('Portable profile was not found.')
        filename = str(row.get('file', ''))
        if Path(filename).name != filename or not filename.endswith('.sqlite'): raise ValueError('Invalid portable database path.')
        source_path = state / 'profiles' / filename
        if source_path.parent.is_symlink() or getattr(source_path.parent.stat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('Portable profiles cannot use linked folders.')
        if not source_path.is_file() or source_path.is_symlink() or source_path.stat().st_size > 256*1024*1024 or _digest(source_path) != row['sha256']:
            raise ValueError('Portable database does not match its verified snapshot.')
        destination = Path(destination); destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix('.portable.tmp')
        source = sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True); target = sqlite3.connect(temporary)
        try:
            source.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise ValueError('Portable database failed verification.')
            artwork_root = Path(artwork_root); artwork_root.mkdir(parents=True, exist_ok=True)
            with target:
                for episode_id, path in target.execute('SELECT id,path FROM episodes').fetchall():
                    if not path.startswith('portable-media/'): raise ValueError('Portable episode path must be relative.')
                    target.execute('UPDATE episodes SET path=? WHERE id=?', (_expanded(path, root), episode_id))
                for series_id, path in target.execute('SELECT id,poster_path FROM series WHERE poster_path IS NOT NULL').fetchall():
                    filename = path.removeprefix('portable-artwork/')
                    if not path.startswith('portable-artwork/') or Path(filename).name != filename:
                        raise ValueError('Invalid portable artwork path.')
                    image = state / 'artwork' / filename; copy = artwork_root / filename
                    if image.parent.is_symlink() or (image.parent.exists() and getattr(image.parent.stat(),'st_file_attributes',0)&0x400): raise ValueError('Portable artwork cannot use linked folders.')
                    if image.is_file() and not image.is_symlink():
                        shutil.copyfile(image, copy); target.execute('UPDATE series SET poster_path=? WHERE id=?', (str(copy), series_id))
                    else: target.execute('UPDATE series SET poster_path=NULL WHERE id=?', (series_id,))
                _settings_transform(target, lambda value: _expanded(value, root))
                target.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)', ('library_root', json.dumps(str(root))))
        except Exception:
            source.close(); target.close()
            try: temporary.unlink(missing_ok=True)
            except OSError: pass
            raise
        finally: source.close(); target.close()
        if destination.exists(): shutil.copyfile(destination, destination.with_name(destination.name + '.before-portable-' + uuid4().hex[:8]))
        temporary.replace(destination)
        return dict(identity=manifest['identity'], profile=profile, root=str(root), sha256=row['sha256'])


def mounted_drives():
    if os.name != 'nt': return []
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    return [Path(chr(65+index) + ':\\') for index in range(26) if mask & (1 << index)
            and ctypes.windll.kernel32.GetDriveTypeW(chr(65+index) + ':\\') in {2,3}]


def find_portable(record, drives=None):
    original = Path(record['root'])
    candidates = [original]
    relative = Path(*original.parts[1:]) if original.anchor else original
    candidates += [Path(drive) / relative for drive in (mounted_drives() if drives is None else drives)]
    matches=[]
    for path in dict.fromkeys(candidates):
        try:
            if _read_manifest(path)['identity'] == record['identity']:
                if path==original: return path
                matches.append(path)
        except (OSError, ValueError, KeyError):
            if path==original and (path/PORTABLE_DIRECTORY/'library.json').is_file(): raise ValueError('Portable library metadata is unreadable or damaged. Local progress is preserved; inspect the drive before syncing.')
    if len(matches)>1: raise ValueError('Multiple copies of this portable library are connected. Open the intended folder explicitly.')
    return matches[0] if matches else None
