import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt, QUrl, QMimeData, QPointF
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QDialog, QLabel, QPushButton
from anime_watcher.database import LibraryDatabase
from anime_watcher.download_queue import DownloadJob, DownloadQueue
from anime_watcher.downloader import EpisodeResult
from anime_watcher.import_review import ImportEntry, import_reviewed, suggested_imports
from anime_watcher.library_tools import (backup_directory, backup_library, inspect_backup, restore_library,
                                         remember_catalog, season_completeness, up_next)
from anime_watcher.feature_widgets import FileDropPanel, ImportReviewDialog, PlaylistReviewDialog
from anime_watcher.youtube import preview_youtube_playlist, youtube_playlist_url
import test_download_artwork_ui as artwork_fixture


class ImportFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.base = Path(self.temp.name)
        self.root = self.base / 'library'; self.root.mkdir()
        self.db = LibraryDatabase(self.base / 'library.db'); self.db.set_setting('library_root', str(self.root))

    def tearDown(self):
        self.db.close(); self.temp.cleanup()

    def seed(self, language='Sub', number=1):
        path = self.root / 'Show' / 'Season 01' / f'Show - S01E{number:02d} [{language}].mp4'
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'old video')
        row, _ = self.db.index_download(path, self.root)
        self.db.save_progress(row['id'], 400000, 1200000)
        return self.db.episode(row['id'])

    def incoming(self, number=1, replace=False, language='Sub', extension='.mp4', replace_id=None):
        source = self.base / f'Incoming-{number}{extension}'; source.write_bytes(b'new verified video')
        return ImportEntry(source, 'Show', 1, number, language, replace, replace_id)

    def probe(self, path):
        return (640, 480, 1200000, True) if self.root in Path(path).parents else (1920, 1080, 1200000, True)


class ReviewedImportTests(ImportFixture):
    def test_replacement_keeps_id_progress_language_and_other_version(self):
        old = self.seed(); dub = self.seed('Dub'); entry = self.incoming(replace=True)
        old_path = Path(old['path']); old_path.with_suffix('.srt').write_text('subtitle')
        old_path.with_name(old_path.name + '.source.json').write_text('{"source":"old"}')
        entry.source.with_name(entry.source.name + '.source.json').write_text('{"source":"new"}')
        with patch('anime_watcher.import_review.verified_media', side_effect=self.probe):
            result = import_reviewed(self.db, self.root, [entry])
        updated = self.db.episode(old['id'])
        self.assertEqual((updated['progress_ms'], updated['completed'], updated['language']), (400000, 0, 'Sub'))
        self.assertEqual(dict(self.db.episode(dub['id'])), dict(dub))
        new_path = Path(updated['path'])
        self.assertIn('[1080p]', new_path.name)
        self.assertFalse(old_path.exists()); self.assertEqual(new_path.read_bytes(), b'new verified video')
        self.assertEqual(new_path.with_suffix('.srt').read_text(), 'subtitle')
        self.assertEqual(json.loads(new_path.with_name(new_path.name + '.source.json').read_text())['source'], 'new')
        self.assertFalse(entry.source.exists()); self.assertEqual(result['replaced'], 1)
        self.assertTrue(any(Path(result['recovery']).rglob('*.mp4')))

    def test_other_container_preserves_subtitles_and_updates_path(self):
        old = self.seed(); source = Path(old['path']); source.with_suffix('.ass').write_text('ass')
        entry = self.incoming(replace=True, extension='.mkv')
        with patch('anime_watcher.import_review.verified_media', side_effect=self.probe):
            import_reviewed(self.db, self.root, [entry])
        updated = Path(self.db.episode(old['id'])['path'])
        self.assertEqual(updated.suffix, '.mkv'); self.assertFalse(source.exists())
        self.assertEqual(updated.with_suffix('.ass').read_text(), 'ass')

    def test_lower_quality_or_wrong_duration_does_not_touch_sources(self):
        old = self.seed(); entry = self.incoming(replace=True)
        for values in [(640, 360, 1200000, True), (1920, 1080, 200000, True), (1920, 1080, 1200000, False)]:
            with patch('anime_watcher.import_review.verified_media', side_effect=[values, (640, 480, 1200000, True)]):
                with self.assertRaises(ValueError): import_reviewed(self.db, self.root, [entry])
            self.assertTrue(entry.source.exists()); self.assertEqual(Path(old['path']).read_bytes(), b'old video')

    def test_companion_collision_fails_before_displacing_original(self):
        old = self.seed(); entry = self.incoming(replace=True, extension='.mkv')
        entry.source.with_name(entry.source.name + '.source.json').write_text('new')
        old_path = Path(old['path']); destination = old_path.with_name(old_path.stem + ' [1080p].mkv')
        destination.with_name(destination.name + '.source.json').write_text('occupied')
        with patch('anime_watcher.import_review.verified_media', side_effect=self.probe):
            with self.assertRaises(FileExistsError): import_reviewed(self.db, self.root, [entry])
        self.assertEqual(Path(old['path']).read_bytes(), b'old video'); self.assertTrue(entry.source.exists())

    def test_sql_failure_rolls_back_entire_batch_and_bundles(self):
        old = self.seed(); entry = self.incoming(replace=True); second = self.incoming(2)
        old_path = Path(old['path']); old_path.with_suffix('.srt').write_text('old subtitles')
        self.db.connection.execute("CREATE TRIGGER fail_import BEFORE INSERT ON episodes BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
        self.db.connection.commit()
        with patch('anime_watcher.import_review.verified_media', side_effect=self.probe):
            with self.assertRaises(sqlite3.IntegrityError): import_reviewed(self.db, self.root, [entry, second])
        self.assertEqual(dict(self.db.episode(old['id'])), dict(old))
        self.assertEqual(old_path.read_bytes(), b'old video'); self.assertEqual(old_path.with_suffix('.srt').read_text(), 'old subtitles')
        self.assertTrue(entry.source.exists()); self.assertTrue(second.source.exists())
        self.assertEqual(len(self.db.all_episodes()), 1)

    def test_copy_failure_preserves_originals_and_does_not_insert_any_row(self):
        entry = self.incoming()
        with patch('anime_watcher.import_review.shutil.copy2', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): import_reviewed(self.db, self.root, [entry])
        self.assertFalse(self.db.all_episodes()); self.assertTrue(entry.source.exists())

    def test_copy_changed_during_verification_aborts_before_commit(self):
        entry = self.incoming()
        def changed(*args):
            entry.source.write_bytes(b'changed'); return 'digest'
        with patch('anime_watcher.import_review._digest', side_effect=changed):
            with self.assertRaises(OSError): import_reviewed(self.db, self.root, [entry])
        self.assertTrue(entry.source.exists()); self.assertFalse(self.db.all_episodes())

    def test_extra_copy_preserves_existing_encode_and_groups_sub_dub(self):
        old = self.seed(); dub = self.incoming(language='Dub')
        import_reviewed(self.db, self.root, [dub])
        copy = self.incoming(); import_reviewed(self.db, self.root, [copy])
        rows = self.db.all_episodes(); self.assertEqual(len(rows), 3)
        self.assertEqual(self.db.series()[0]['episode_count'], 1)
        self.assertEqual(Path(old['path']).read_bytes(), b'old video')
        self.assertEqual(sum(row['language'] == 'Sub' for row in rows), 2)

    def test_ambiguous_versions_need_explicit_replacement(self):
        old = self.seed(); entry = self.incoming(); import_reviewed(self.db, self.root, [entry])
        upgraded = self.incoming(replace=True)
        with self.assertRaises(ValueError): import_reviewed(self.db, self.root, [upgraded])
        upgraded = ImportEntry(upgraded.source, 'Show', 1, 1, 'Sub', True, old['id'])
        with patch('anime_watcher.import_review.verified_media', side_effect=self.probe):
            import_reviewed(self.db, self.root, [upgraded])
        self.assertEqual(len(self.db.all_episodes()), 2)

    def test_selected_old_version_must_match_the_language(self):
        old = self.seed('Dub'); entry = self.incoming(replace=True, replace_id=old['id'])
        with self.assertRaises(ValueError): import_reviewed(self.db, self.root, [entry])
        self.assertTrue(entry.source.exists())

    def test_recycle_failure_keeps_verified_import_and_recoverable_copy(self):
        self.seed(); entry = self.incoming(replace=True)
        with patch('anime_watcher.import_review.verified_media', side_effect=self.probe), patch('anime_watcher.import_review.send_to_recycle_bin', side_effect=OSError('locked')):
            result = import_reviewed(self.db, self.root, [entry], recycle=True)
        self.assertEqual(result['replaced'], 1); self.assertTrue(result['warnings']); self.assertTrue(Path(result['recovery']).is_dir())

    def test_traversal_and_sources_already_in_library_are_rejected(self):
        old = self.seed(); entry = self.incoming()
        bad = ImportEntry(entry.source, '../outside', 1, 1, 'Sub')
        with self.assertRaises(ValueError): import_reviewed(self.db, self.root, [bad])
        with self.assertRaises(ValueError): import_reviewed(self.db, self.root, [ImportEntry(Path(old['path']), 'Show', 1, 2, 'Sub')])

    def test_suggestions_deduplicate_and_sort_numerically(self):
        paths = []
        for number in [14, 1, 2]:
            path = self.base / f'Show - S01E{number:02d} [Sub].mp4'; path.write_bytes(b'fixture'); paths.append(path)
        self.assertEqual([item.episode for item in suggested_imports(paths + paths)], [1, 2, 14])

    def test_install_move_failure_rolls_back_replaced_video_and_new_episode(self):
        from anime_watcher.import_review import _install_copy
        old = self.seed(); entry = self.incoming(replace=True); second = self.incoming(2)
        real_move = _install_copy
        def fail_second(source, destination):
            if 'S01E02' in str(destination) and str(destination).endswith('.mp4'):
                raise OSError('fixture move failure')
            return real_move(source, destination)
        with patch('anime_watcher.import_review.verified_media', side_effect=self.probe), patch('anime_watcher.import_review._install_copy', side_effect=fail_second):
            with self.assertRaises(OSError): import_reviewed(self.db, self.root, [entry, second])
        self.assertEqual(dict(self.db.episode(old['id'])), dict(old)); self.assertEqual(Path(old['path']).read_bytes(), b'old video')
        self.assertTrue(entry.source.exists()); self.assertTrue(second.source.exists())

    def test_library_change_during_copy_prevents_install(self):
        entry = self.incoming()
        def change_root(*args): self.db.set_setting('library_root', str(self.base / 'different'))
        with self.assertRaises(ValueError): import_reviewed(self.db, self.root, [entry], progress=change_root)
        self.assertTrue(entry.source.exists()); self.assertFalse(self.db.all_episodes())

    def test_file_appearing_after_preflight_is_preserved_and_import_is_rolled_back(self):
        from anime_watcher.import_review import _install_copy
        entry = self.incoming()
        def late_file(source, destination):
            destination.write_bytes(b'late arriving file')
            return _install_copy(source, destination)
        with patch('anime_watcher.import_review._install_copy', side_effect=late_file):
            with self.assertRaises(FileExistsError): import_reviewed(self.db, self.root, [entry])
        self.assertTrue(entry.source.exists()); self.assertFalse(self.db.all_episodes())
        self.assertEqual(next(self.root.glob('Show/Season 01/*.mp4')).read_bytes(), b'late arriving file')


class LibraryToolsTests(ImportFixture):
    def test_next_unwatched_uses_preferred_version_and_resume_progress(self):
        first = self.seed(); self.seed('Dub'); second = self.seed(number=2)
        self.db.save_progress(first['id'], 1200000, 1200000)
        self.assertEqual(up_next(self.db)[0]['id'], second['id'])
        self.db.save_progress(second['id'], 1200000, 1200000)
        self.assertEqual(up_next(self.db), [])

    def test_completeness_separates_versions_uses_source_and_handles_unknown_total(self):
        first = self.seed(); self.seed(number=3); self.seed('Dub')
        rows = season_completeness(self.db, first['series_id'])
        sub = next(row for row in rows if row['language'] == 'Sub')
        self.assertEqual((sub['total'], sub['missing'], sub['links']), (None, [2], []))
        links = [EpisodeResult(f'Episode {number}', f'https://www.wco.tv/episode-{number}', True, 1, str(number), 'Sub') for number in [1, 2, 3, 4]]
        remember_catalog(self.db, 'Show', links)
        sub = next(row for row in season_completeness(self.db, first['series_id']) if row['language'] == 'Sub')
        self.assertEqual((sub['have'], sub['total'], sub['missing']), (2, 4, [2, 4]))
        self.assertEqual(len(sub['links']), 2)
        remember_catalog(self.db, 'Show', [EpisodeResult('Dub', 'https://www.wco.tv/dub', True, 1, '1', 'Dub')])
        self.assertEqual(len(next(row for row in season_completeness(self.db, first['series_id']) if row['language'] == 'Sub')['links']), 2)

    def test_backup_restore_round_trip_and_pre_restore_recovery(self):
        old = self.seed(); self.db.set_setting('test_setting', 'before')
        backup = backup_library(self.db, self.base, 'default')
        self.assertEqual(inspect_backup(backup, 'default')['videos'], 1)
        self.db.save_progress(old['id'], 1100000, 1200000); self.db.set_setting('test_setting', 'after')
        recovery = restore_library(self.db, backup, self.base, 'default')
        self.assertEqual(self.db.episode(old['id'])['progress_ms'], 400000); self.assertEqual(self.db.setting('test_setting'), 'before')
        restored = LibraryDatabase(recovery)
        try: self.assertEqual(restored.episode(old['id'])['progress_ms'], 1100000)
        finally: restored.close()
        self.assertEqual(Path(old['path']).read_bytes(), b'old video')

    def test_backup_rejects_other_profile_non_sqlite_and_unexpected_sql_code(self):
        backup = backup_library(self.db, self.base, 'default')
        with self.assertRaises(ValueError): inspect_backup(backup, 'other')
        bad = self.base / 'bad.sqlite'; bad.write_bytes(b'not a database')
        with self.assertRaises(sqlite3.DatabaseError): inspect_backup(bad, 'default')
        connection = sqlite3.connect(backup); connection.execute('CREATE VIEW unexpected AS SELECT * FROM episodes'); connection.close()
        with self.assertRaises(ValueError): restore_library(self.db, backup, self.base, 'default')

    def test_automatic_backup_is_once_daily_and_profiles_are_isolated(self):
        first = backup_library(self.db, self.base, 'default', kind='automatic')
        self.assertIsNone(backup_library(self.db, self.base, 'default', kind='automatic'))
        other = backup_library(self.db, self.base, 'other', kind='automatic')
        self.assertNotEqual(first.parent, other.parent)
        with self.assertRaises(ValueError): backup_directory(self.base, '../outside')

    def test_retention_keeps_seven_daily_backups_and_all_manual_backups(self):
        manual = backup_library(self.db, self.base, 'default')
        for day in range(1, 11):
            with patch('anime_watcher.library_tools.time.strftime', side_effect=lambda fmt, day=day: f'2026-09-{day:02d}' if fmt == '%Y-%m-%d' else f'2026-09-{day:02d}_12-00-00'):
                backup_library(self.db, self.base, 'default', kind='automatic')
        self.assertEqual(len(list(manual.parent.glob('*-automatic-*.sqlite'))), 7); self.assertTrue(manual.exists())

    def test_restore_migration_failure_recovers_current_state(self):
        row = self.seed(); backup = backup_library(self.db, self.base, 'default')
        self.db.save_progress(row['id'], 600000, 1200000)
        with patch.object(self.db, '_migrate', side_effect=sqlite3.DatabaseError('fixture migration error')):
            with self.assertRaises(sqlite3.DatabaseError): restore_library(self.db, backup, self.base, 'default')
        self.assertEqual(self.db.episode(row['id'])['progress_ms'], 600000)

    def test_backup_missing_required_columns_is_rejected_before_restore(self):
        backup = backup_library(self.db, self.base, 'default')
        source = sqlite3.connect(backup); source.execute('ALTER TABLE series DROP COLUMN display_title'); source.close()
        with self.assertRaises(ValueError): restore_library(self.db, backup, self.base, 'default')


class QueueAndPlaylistTests(unittest.TestCase):
    def test_pause_allows_active_finish_and_reordered_waiter_starts_first(self):
        queue = DownloadQueue(limit=1)
        jobs = [DownloadJob(str(number), 'YouTube', str(number), Path('owner.db'), Path('library'), 'Default', Mock(), Mock()) for number in range(3)]
        queue.add_many(jobs); queue.set_paused(True); queue.finish(jobs[0].id, 'Completed', 'done')
        self.assertEqual(queue.active_count, 0); self.assertTrue(queue.reorder(jobs[2].id, jobs[1].id))
        self.assertEqual(queue.display_jobs()[0].id, jobs[2].id)
        queue.set_paused(False); jobs[2].start.assert_called_once(); jobs[1].start.assert_not_called()
        self.assertFalse(queue.reorder(jobs[2].id, jobs[1].id))

    def test_playlist_accepts_only_public_youtube_hosts(self):
        self.assertEqual(youtube_playlist_url('https://www.youtube.com/watch?v=abcdefghijk&list=PLabcdefghijk'), 'https://www.youtube.com/playlist?list=PLabcdefghijk')
        for url in ['https://youtube.com.evil.test/playlist?list=PLabcdefghijk', 'file:///playlist?list=PLabcdefghijk', 'https://user:pass' + chr(64) + 'youtube.com/playlist?list=PLabcdefghijk', 'https://youtube.com/channel/name']:
            with self.assertRaises(ValueError): youtube_playlist_url(url)

    def test_playlist_preview_skips_unavailable_repeated_and_live_entries(self):
        result = dict(_type='playlist', title='Playlist', entries=[dict(id='abcdefghijk', title='First'), None,
                      dict(id='abcdefghijk', title='Again'), dict(id='lmnopqrstuv', title='[Private video]'),
                      dict(id='wxyzABCDEFG', is_live=True), dict(id='12345678901', title='Second'), dict(id='../outside')])
        with patch('yt_dlp.YoutubeDL') as downloader:
            downloader.return_value.__enter__.return_value.extract_info.return_value = result
            preview = preview_youtube_playlist('https://youtube.com/playlist?list=PLabcdefghijk')
            self.assertTrue(downloader.call_args.args[0]['skip_download'])
        self.assertEqual([row['title'] for row in preview['videos']], ['First', 'Second']); self.assertEqual(preview['skipped'], 5)


class WorkflowUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        artwork_fixture.DownloadArtworkTests.setUpClass(); cls.app = artwork_fixture.DownloadArtworkTests.app

    def setUp(self):
        self.fixture = artwork_fixture.DownloadArtworkTests(); self.fixture.setUp(); self.window = self.fixture.window
        self.series_id = self.fixture.seed('Show')

    def tearDown(self):
        self.window.import_job = None; self.fixture.tearDown()

    def test_import_cancel_does_not_move_and_accept_shows_inline_result(self):
        path = Path(self.fixture.temp.name) / 'Show - S01E02 [Sub].mp4'; path.write_bytes(b'fixture')
        self.window.show_import(); page = self.window.stack.currentWidget()
        with patch('anime_watcher.qt_ui.ImportReviewDialog.exec', return_value=0): self.window._organize([path])
        self.assertTrue(path.exists()); self.assertIsNone(self.window.import_job)
        with patch('anime_watcher.qt_ui.ImportReviewDialog.exec', return_value=1): self.window._organize([path])
        self.assertTrue(path.exists()); worker = self.fixture.mocks[-2].call_args.args[0]; worker.run()
        self.assertIsNone(self.window.import_job); self.assertFalse(path.exists())
        self.assertIn('Imported 1', self.window.import_status.text()); self.assertIs(self.window.stack.currentWidget(), page)

    def test_bulk_import_review_changes_selected_rows_only_and_is_numeric(self):
        paths = [Path(self.fixture.temp.name) / f'Other - S01E{number:02d} [Sub].mp4' for number in [14, 1, 2]]
        for path in paths: path.write_bytes(b'fixture')
        dialog = ImportReviewDialog(suggested_imports(paths), self.window.db.series(), parent=self.window)
        dialog.table.selectAll(); dialog.series.setCurrentText('Show'); dialog.season.setValue(2); dialog.first.setValue(1); dialog.language.setCurrentText('Dub'); dialog.apply_bulk()
        self.assertEqual([(row.title, row.season, row.episode, row.language) for row in dialog.reviewed_entries()], [('Show', 2, n, 'Dub') for n in [1, 2, 3]])
        dialog.deleteLater()

    def test_playlist_queues_in_order_same_series_and_stays_on_find(self):
        page = self.window.stack.currentWidget()
        videos = [dict(title=f'Video {index}', url=f'https://www.youtube.com/watch?v=abcdefghij{index}') for index in range(3)]
        jobs = self.window._queue_youtube_playlist(videos, 'Playlist', 1)
        self.assertEqual([job.retry_data['episode'] for job in jobs], [1, 2, 3])
        self.assertEqual({job.retry_data['title'] for job in jobs}, {'Playlist'})
        self.assertIs(self.window.stack.currentWidget(), page); self.assertEqual(self.window.download_tabs.currentIndex(), 0)
        self.assertEqual(len(self.window._queue_youtube_playlist(videos, 'Playlist', 1)), 0)

    def test_playlist_slot_conflict_is_atomic_and_permission_required(self):
        videos = [dict(title='Video', url='https://www.youtube.com/watch?v=abcdefghijk')]
        with self.assertRaises(ValueError): self.window._queue_youtube_playlist(videos, 'Show', 1, 1)
        self.assertFalse(self.window.download_queue.jobs)
        self.window.db.set_setting('download_permission_confirmed', False)
        with self.assertRaises(ValueError): self.window._queue_youtube_playlist(videos, 'New', 1)

    def test_playlist_review_selects_only_checked_videos_in_source_order(self):
        videos = [dict(title=f'Video {index}', url=f'https://www.youtube.com/watch?v=abcdefghij{index}') for index in range(3)]
        dialog = PlaylistReviewDialog(dict(title='Playlist', videos=videos, skipped=1), [], parent=self.window)
        dialog.table.cellWidget(1, 0).setChecked(False)
        self.assertEqual(dialog.selected_videos(), [videos[0], videos[2]])
        self.assertEqual(dialog.first.value(), 0); self.assertEqual(dialog.quality.currentData(), 'best'); dialog.deleteLater()

    def test_retry_all_keeps_cards_ids_and_only_current_profile(self):
        jobs = self.fixture.queue(3)
        for job in jobs: self.window.download_queue.finish(job.id, 'Failed', 'fixture failure')
        jobs[-1].database = Path(self.fixture.temp.name) / 'other.db'
        ids = set(self.window.download_queue.jobs); self.window._retry_all_failed()
        self.assertEqual(set(self.window.download_queue.jobs), ids)
        self.assertEqual(jobs[-1].status, 'Failed'); self.assertTrue(all(job.status != 'Failed' for job in jobs[:-1]))

    def test_toolbar_pause_and_card_reorder_update_queue(self):
        self.window.download_queue.set_limit(1); jobs = self.fixture.queue(3)
        self.window.stack.currentWidget().findChild(QPushButton, 'pauseDownloadQueue').click()
        self.assertTrue(self.window.download_queue.paused)
        card = self.window._download_rows[jobs[-1].id][0].parentWidget()
        card.reordered.emit(jobs[-1].id, jobs[1].id)
        self.assertEqual(list(self.window.download_queue.jobs)[1], jobs[-1].id)

    def test_home_up_next_plays_correct_slot_and_series_has_completeness(self):
        self.window.show_home(); button = self.window.stack.currentWidget().findChild(QPushButton, 'upNextEpisode')
        with patch.object(self.window, 'play_episode') as play:
            button.click(); play.assert_called_once_with(button.property('episodeId'))
        self.window.show_series(self.series_id)
        self.assertIsNotNone(self.window.stack.currentWidget().findChild(QPushButton, 'seasonCompleteness'))

    def test_home_limits_up_next_to_twelve_and_removes_duplicate_collection(self):
        for number in range(14):
            self.fixture.seed(f'Series {number:02d}')
        episode = self.window.db.episodes(self.series_id)[0]
        self.window.db.save_progress(episode['id'], 100000, 1200000)
        self.window.show_home()
        page = self.window.stack.currentWidget()
        self.assertEqual(len(page.findChildren(QPushButton, 'upNextEpisode')), 12)
        self.assertEqual(len(page.findChildren(QLabel, 'upNextThumbnail')), 12)
        headings = [label.text() for label in page.findChildren(QLabel)]
        self.assertNotIn('Your collection', headings)
        self.assertIn('Continue watching', headings)

    def test_home_thumbnail_cards_preserve_anime_and_youtube_artwork_and_play(self):
        youtube_id = self.fixture.seed('Channel')
        self.window.db.set_series_library_type(youtube_id, 'YouTube')
        self.window.show_home()
        page = self.window.stack.currentWidget()
        sizes = set()
        for button in page.findChildren(QPushButton, 'upNextEpisode'):
            card = button.parentWidget()
            thumbnail = card.findChild(QLabel, 'upNextThumbnail')
            self.assertFalse(thumbnail.pixmap().isNull())
            self.assertEqual(thumbnail.pixmap().toImage().pixelColor(0, 0).name(), '#800080')
            sizes.add((thumbnail.pixmap().width(), thumbnail.pixmap().height()))
            with patch.object(self.window, 'play_episode') as play:
                card.clicked.emit()
                play.assert_called_once_with(button.property('episodeId'))
        self.assertEqual(sizes, {(180, 255), (230, 129)})

    def test_restore_blocked_by_queued_download_and_import(self):
        backup = backup_library(self.window.db, self.window.data_root, self.window.profile_manager.active.id)
        self.window.download_queue.set_paused(True); self.fixture.queue(1)
        with self.assertRaises(ValueError): self.window._restore_library_backup(backup)
        self.window.download_queue.clear_finished(); self.window.import_job = (self.window.db.path, self.window.library_root)
        self.assertTrue(self.window._restore_busy()); self.window.import_job = None

    def test_manual_backup_and_restore_ui_rebuild_current_profile(self):
        row = self.window.db.episodes(self.series_id)[0]
        self.window.db.save_progress(row['id'], 100000, 1200000)
        self.window.show_settings(); self.window.stack.currentWidget().findChild(QPushButton, 'createLibraryBackup').click()
        backup = self.window.backup_combo.currentData(); self.assertTrue(Path(backup).is_file())
        self.window.db.save_progress(row['id'], 600000, 1200000); self.window._restore_library_backup(backup)
        self.assertEqual(self.window.db.episode(row['id'])['progress_ms'], 100000)
        self.assertIn('Restored', self.window.backup_status.text())

    def test_drop_panel_dispatches_local_files(self):
        panel = FileDropPanel(); received = []; panel.files_dropped.connect(received.append)
        mime = QMimeData(); path = Path(self.fixture.temp.name) / 'sample.mp4'; mime.setUrls([QUrl.fromLocalFile(str(path))])
        event = QDropEvent(QPointF(20, 20), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        panel.dropEvent(event); self.assertEqual(received, [[path]]); self.assertTrue(event.isAccepted()); panel.deleteLater()

    def test_import_completion_after_profile_change_only_updates_original_database(self):
        path = Path(self.fixture.temp.name) / 'Show - S01E02 [Sub].mp4'; path.write_bytes(b'fixture')
        self.window.show_import()
        with patch('anime_watcher.qt_ui.ImportReviewDialog.exec', return_value=1): self.window._organize([path])
        worker = self.fixture.mocks[-2].call_args.args[0]
        original = self.window.db; other = LibraryDatabase(Path(self.fixture.temp.name) / 'other.db')
        self.window.db = other
        try:
            worker.run()
            self.assertEqual(len(original.all_episodes()), 2); self.assertFalse(other.all_episodes())
            self.assertIsNone(other.setting('library_tab'))
        finally:
            self.window.db = original; other.close()

    def test_playlist_reply_after_navigation_does_not_open_review(self):
        self.window.youtube_playlist.setText('https://youtube.com/playlist?list=PLabcdefghijk'); self.window._preview_playlist()
        key = self.window.playlist_request; self.window.show_home()
        with patch('anime_watcher.qt_ui.PlaylistReviewDialog') as dialog:
            self.window._playlist_ready(key, dict(title='Playlist', videos=[], skipped=0)); dialog.assert_not_called()
        self.assertIsNone(self.window.playlist_request)

    def test_update_waits_for_import_without_launching_installer(self):
        self.window.import_job = (self.window.db.path, self.window.library_root); self.window.staged_app_update = Mock()
        with patch('anime_watcher.qt_ui.Worker') as worker, patch.object(self.window, '_refresh_app_update_button'):
            self.window._install_staged_app_update(); worker.assert_not_called()
            self.assertEqual(self.window.app_update_phase, 'waiting')
            self.window.import_job = None; self.window._resume_update_after_import(); worker.assert_called_once()


if __name__ == '__main__': unittest.main()
