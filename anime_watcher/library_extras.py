"""Library views, conservative storage review, and user-authored skip ranges."""
from __future__ import annotations

import os
import shutil
from collections import defaultdict
from pathlib import Path

from .media_chapters import MediaChapter
from .organizer import DOWNLOAD_STAGING_DIRECTORY, VIDEO_EXTENSIONS

PORTABLE_DIRECTORY = '.anime-watcher-state'
WATCH_STATES = ('Automatic', 'Plan to watch', 'Watching', 'Completed', 'On hold')


def watch_state(series):
    if series['watch_state'] != 'Automatic':
        return series['watch_state']
    if series['episode_count'] and series['completed_count'] == series['episode_count']:
        return 'Completed'
    return 'Watching' if series['last_watched'] else 'Plan to watch'


def library_view(db, search='', *, category='Anime', favorite=False, state='All', year='All', language='All', quality=0, sort='Title'):
    rows = list(db.series(search, library_type=category))
    dimensions = db.setting('verified_video_heights', {})
    signatures = db.setting('verified_video_signatures', {})
    if not isinstance(dimensions, dict): dimensions = {}
    if not isinstance(signatures, dict): signatures = {}
    def verified(path):
        try:
            stat=Path(path).stat(); signature=signatures.get(path)
            return int(dimensions.get(path,0)) if signature and signature[1:]==[stat.st_size,stat.st_mtime_ns] else 0
        except (OSError,TypeError,ValueError): return 0
    result = []
    for row in rows:
        if favorite and not row['favorite']: continue
        if state != 'All' and watch_state(row) != state: continue
        if year == 'Unknown' and row['release_year']: continue
        if year not in {'All','Unknown'} and str(row['release_year']) != str(year): continue
        if language != 'All' or quality:
            versions = db.episodes(row['id'])
            if not any((language == 'All' or item['language'] == language) and
                       (not quality or verified(item['path']) >= quality) for item in versions):
                continue
        result.append(row)
    if sort == 'Year':
        result.sort(key=lambda row: (-(row['release_year'] or 0), (row['display_title'] or row['title']).casefold()))
    elif sort == 'Recently added': result.sort(key=lambda row: (row['added_at'] or '', row['id']), reverse=True)
    elif sort == 'Last watched': result.sort(key=lambda row: (row['last_watched'] or '', row['id']), reverse=True)
    return result


def file_inventory(root, *, media_only=False):
    root = Path(root)
    if not root.is_dir(): raise FileNotFoundError('Drive disconnected — reconnect your library drive.')
    result = {}
    def fail(error): raise error
    for directory, folders, names in os.walk(root, onerror=fail, followlinks=False):
        base = Path(directory)
        folders[:] = [name for name in folders if not (base / name).is_symlink()
                      and not (getattr((base / name).stat(), 'st_file_attributes', 0) & 0x400)
                      and not (base == root and name in {DOWNLOAD_STAGING_DIRECTORY, PORTABLE_DIRECTORY})]
        for name in names:
            path = base / name
            if media_only and path.suffix.lower() not in VIDEO_EXTENSIONS: continue
            stat = path.stat(follow_symlinks=False)
            if path.is_symlink() or getattr(stat, 'st_file_attributes', 0) & 0x400: continue
            result[path.relative_to(root).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    if not root.is_dir(): raise FileNotFoundError('Drive disconnected during the scan.')
    return result


def storage_review(root, live_paths=()):
    root = Path(root).resolve()
    files = file_inventory(root)
    by_series = defaultdict(int)
    for name, (size, _) in files.items():
        if '/' in name: by_series[name.split('/')[0]] += size
    recovery = root / DOWNLOAD_STAGING_DIRECTORY / 'imports'
    candidates = []
    protected = {Path(path).resolve() for path in live_paths}
    if recovery.is_dir() and not recovery.is_symlink():
        for batch in recovery.iterdir():
            old = batch / 'old'
            if not old.is_dir(): continue
            try:
                _validate_recovery(root, old)
                inventory = file_inventory(old)
                if inventory and not any(old == path or old in path.parents for path in protected):
                    candidates.append(dict(path=str(old), size=sum(size for size, _ in inventory.values()), inventory=inventory))
            except (OSError, ValueError): continue
    usage = shutil.disk_usage(root)
    return dict(root=str(root), used=sum(size for size, _ in files.values()), free=usage.free, capacity=usage.total,
                series=sorted(by_series.items(), key=lambda row: row[1], reverse=True), recovery=candidates,
                recovery_bytes=sum(row['size'] for row in candidates))


def _validate_recovery(root, path):
    root, path = Path(root).resolve(), Path(path)
    relative = path.absolute().relative_to(root)
    if len(relative.parts) != 4 or relative.parts[:2] != (DOWNLOAD_STAGING_DIRECTORY, 'imports') or relative.parts[-1] != 'old':
        raise ValueError('Only reviewed replaced-file recovery folders can be recycled.')
    for part in (path, *path.parents):
        if part.is_symlink() or (part.exists() and getattr(part.stat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('Linked recovery folders cannot be cleaned.')
    for directory, folders, files in os.walk(path, followlinks=False):
        for name in folders + files:
            item = Path(directory) / name
            if item.is_symlink() or getattr(item.stat(follow_symlinks=False), 'st_file_attributes', 0) & 0x400:
                raise ValueError('Recovery contains linked files or folders; cleanup skipped.')


def recycle_reviewed(root, candidates, live_paths=()):
    from .library_actions import send_to_recycle_bin
    root = Path(root).resolve()
    protected = {Path(path).resolve() for path in live_paths}
    # Validate every selected folder before making any changes.
    for row in candidates:
        path = Path(row['path']); _validate_recovery(root, path)
        if file_inventory(path) != row['inventory'] or any(path.resolve() == item or path.resolve() in item.parents for item in protected):
            raise ValueError('Recovery files changed since the review. Scan again before cleaning.')
    done, errors = [], []
    for row in candidates:
        try: send_to_recycle_bin(Path(row['path']), root, recovery_folder=True); done.append(row['path'])
        except (OSError, ValueError) as exc: errors.append(str(exc))
    return dict(recycled=done, errors=errors)


def save_skip_marker(db, episode, kind, start_ms, end_ms, *, season=False):
    if kind not in {'intro', 'outro'} or not 0 <= start_ms < end_ms or end_ms - start_ms > 600_000:
        raise ValueError('Choose a start before the end, with a range of at most 10 minutes.')
    if episode['duration_ms'] and end_ms > episode['duration_ms']:
        raise ValueError('The marker must fit inside this video.')
    key = f"custom_skip:{episode['series_id']}:{episode['season']}:{episode['language']}" if season else f"custom_skip_episode:{episode['id']}"
    saved = db.setting(key, {}); saved = saved if isinstance(saved, dict) else {}
    saved[kind] = [int(start_ms), int(end_ms)]; db.set_setting(key, saved)


def custom_skip_markers(db, episode, duration=0):
    saved = {}
    for key in (f"custom_skip:{episode['series_id']}:{episode['season']}:{episode['language']}", f"custom_skip_episode:{episode['id']}"):
        value = db.setting(key, {})
        if isinstance(value, dict): saved.update(value)
    result = []
    for kind, times in saved.items():
        if kind not in {'intro', 'outro'} or not isinstance(times, list) or len(times) != 2: continue
        try: start, end = map(int, times)
        except (TypeError, ValueError): continue
        limit = duration or episode['duration_ms']
        if 0 <= start < end and end - start <= 600_000 and (not limit or end <= limit):
            result.append(MediaChapter('Custom ' + kind.title(), kind, start, end))
    return result


def download_groups(jobs, database):
    groups = defaultdict(list)
    for job in jobs:
        if job.database != Path(database): continue
        data = job.retry_data
        title = str(data.get('title') or data.get('series') or job.title)
        try: season=int(data.get('season') or 0)
        except (TypeError,ValueError): season=0
        groups[(title, season, str(data.get('language') or ''))].append(job)
    result = []
    for (title, season, language), rows in groups.items():
        complete = sum(row.status == 'Completed' for row in rows)
        failed = sum(row.status in {'Failed', 'Needs attention'} for row in rows)
        pending = [row for row in rows if row.status not in {'Completed', 'Cancelled', 'Failed', 'Needs attention'}]
        active = sum(row.active for row in pending)
        speeds = [row.bytes_per_second for row in pending if row.bytes_per_second > 0]
        # Unknown queued sizes make an honest full-season ETA impossible.
        remaining = sum(max(0, row.total - row.received) for row in pending)
        eta = round(remaining / sum(speeds)) if speeds and pending and all(row.total > 0 for row in pending) else None
        progress = sum(1 if row.status == 'Completed' else min(.99, row.received / row.total) if row.total else 0 for row in rows) / len(rows)
        low = sum(row.status == 'Completed' and 0 < int(row.retry_data.get('verified_height') or 0) < int(row.retry_data.get('preferred_height') or 1080) for row in rows)
        result.append(dict(title=title, season=season, language=language, completed=complete, total=len(rows), active=active,
                           queued=sum(row.status == 'Queued' for row in pending), failed=failed, progress=round(progress*1000), eta=eta, lower_quality=low))
    return result
