import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QPushButton
from anime_watcher.database import LibraryDatabase
from anime_watcher.downloader import EpisodeResult
from anime_watcher.download_queue import DownloadJob
from anime_watcher.qt_ui import AnimeWatcherWindow


class DownloadArtworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'APPDATA': self.temp.name})
        self.env.start()
        self.patches = [patch.object(AnimeWatcherWindow, name) for name in ('_auto_metadata', '_refresh_release_schedule', '_auto_check_for_app_update', '_report_pending_app_update', '_start_worker', '_start_wco_job')]
        self.mocks = [item.start() for item in self.patches]
        self.window = AnimeWatcherWindow()
        self.window.library_root = Path(self.temp.name) / 'library'
        self.window.db.set_setting('library_root', str(self.window.library_root))
        self.window.show_downloads()
        self.window.download_permission.setChecked(True)
        self.poster = Path(self.temp.name) / 'poster.png'
        pixmap = QPixmap(180, 255); pixmap.fill(QColor('purple')); pixmap.save(str(self.poster))
        self.data = dict(id=42, title='Example Show', synopsis='Example synopsis', poster_path=str(self.poster), year=2023)

    def tearDown(self):
        self.window.close(); self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete); self.app.processEvents()
        for item in reversed(self.patches): item.stop()
        self.env.stop(); self.temp.cleanup()

    def seed(self, title='Example Show', db=None, root=None, year=2023):
        db = db or self.window.db
        root = root or self.window.library_root
        path = root / title / 'Season 01' / f'{title} - S01E01 [Dub].mp4'
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'fixture')
        row, _ = db.index_download(path, root)
        db.update_metadata(row['series_id'], title, 'Synopsis', str(self.poster), 42, year)
        return int(row['series_id'])

    def queue(self, count=3):
        episodes = [EpisodeResult(f'Episode {n}', f'https://www.wco.tv/ep{n}', True, 1, str(n), 'Dub') for n in range(1, count + 1)]
        self.window._queue_wco_batch('Example Show', episodes, skip_existing=False)
        return list(self.window.download_queue.jobs.values())

    def test_cached_library_art_and_year_are_shared_without_lookup(self):
        self.seed()
        jobs = self.queue()
        for job in jobs:
            thumbnail, year = self.window._download_artwork_rows[job.id]
            self.assertFalse(thumbnail.pixmap().isNull())
            self.assertEqual(year.text(), '2023')
        self.assertFalse(self.window.download_metadata_pending)
        self.assertEqual(len(self.window.download_metadata), 1)

    def test_season_lookup_deduplicates_and_updates_existing_cards_without_navigation(self):
        jobs = self.queue(14)
        self.assertEqual(len(self.window.download_metadata_pending), 1)
        card = self.window._download_rows[jobs[0].id][0].parentWidget()
        thumbnail = self.window._download_artwork_rows[jobs[0].id][0]
        current = self.window.stack.currentWidget()
        key = self.window._download_metadata_key(jobs[0])
        self.window._download_metadata_ready(key, 'Example Show', self.data)
        self.assertIs(self.window._download_rows[jobs[0].id][0].parentWidget(), card)
        self.assertIs(self.window._download_artwork_rows[jobs[0].id][0], thumbnail)
        self.assertFalse(thumbnail.pixmap().isNull())
        self.assertIs(self.window.stack.currentWidget(), current)
        self.assertTrue(all(job.artwork['year'] == 2023 for job in jobs))

    def test_missing_details_never_block_episode_start_and_show_honest_placeholders(self):
        jobs = self.queue()
        self.assertEqual(self.mocks[-1].call_count, 3)
        thumbnail, year = self.window._download_artwork_rows[jobs[0].id]
        self.assertIn('unavailable', thumbnail.text())
        self.assertEqual(year.text(), 'Year unavailable')
        self.window._download_metadata_ready(self.window._download_metadata_key(jobs[0]), 'Example Show', dict(self.data, year=None, poster_path=''))
        self.assertEqual(year.text(), 'Year unavailable')
        self.assertNotEqual(jobs[0].status, 'Failed')

    def test_metadata_is_applied_to_imported_series_and_persisted_in_history(self):
        job = self.queue(1)[0]
        self.window._download_metadata_ready(self.window._download_metadata_key(job), 'Example Show', self.data)
        path = self.window.library_root / 'Example Show' / 'Season 01' / 'Example Show - S01E01 [Dub].mp4'
        path.parent.mkdir(parents=True); path.write_bytes(b'fixture')
        self.window._index_download_owner(job, path)
        series = self.window.db.series()[0]
        self.assertEqual(series['release_year'], 2023)
        self.window.download_queue.finish(job.id, 'Completed', 'Saved', path)
        self.window._save_download_snapshot()
        self.window.download_queue.jobs.clear()
        self.window._restore_download_history()
        restored = self.window.download_queue.jobs[job.id]
        self.assertEqual(restored.artwork, dict(poster_path=str(self.poster), year=2023))
        self.window._download_queue_changed('')
        self.assertEqual(self.window._download_artwork_rows[job.id][1].text(), '2023')

    def test_optional_artwork_database_error_does_not_fail_video_import(self):
        import sqlite3
        job = self.queue(1)[0]
        self.window._download_metadata_ready(self.window._download_metadata_key(job), 'Example Show', self.data)
        path = self.window.library_root / 'Example Show' / 'Season 01' / 'Example Show - S01E01 [Dub].mp4'
        path.parent.mkdir(parents=True); path.write_bytes(b'fixture')
        with patch.object(self.window.db, 'update_metadata', side_effect=sqlite3.OperationalError('locked')):
            self.window._index_download_owner(job, path)
        self.assertEqual(len(self.window.db.all_episodes()), 1)
        self.assertTrue(path.is_file())

    def test_legacy_history_with_only_an_artwork_title_is_not_discarded(self):
        import json
        sid = self.seed()
        row = dict(id='legacy', title='Example Show · Episode 1', source='WCO', profile='Default',
                   page_url='https://www.wco.tv/ep1', status='Completed', detail='Saved',
                   owner_database=str(self.window.db.path), library_root=str(self.window.library_root),
                   retry_data=dict(title='Example Show'), artwork=dict(poster_path=str(self.poster), year=2023))
        (self.window.data_root / 'download-queue.json').write_text(json.dumps(dict(jobs=[row])))
        self.window._restore_download_history()
        self.assertIn('legacy', self.window.download_queue.jobs)
        self.assertEqual(self.window.download_queue.jobs['legacy'].artwork['year'], 2023)

    def test_series_details_year_and_renamed_button_refresh_without_forcing_navigation(self):
        sid = self.seed(year=None)
        self.window.show_series(sid)
        page = self.window.stack.currentWidget()
        self.assertEqual(page.findChild(QLabel, 'seriesReleaseYear').text(), 'Year unavailable')
        button = next(button for button in page.findChildren(QPushButton) if button.text() == 'Grab details and thumbnail')
        with patch.object(self.window, '_refresh_metadata') as refresh:
            button.click(); refresh.assert_called_once_with(sid)
        self.window._metadata_ready(sid, self.data)
        self.assertEqual(self.window.stack.currentWidget().findChild(QLabel, 'seriesReleaseYear').text(), '2023')
        self.window.show_downloads()
        current = self.window.stack.currentWidget()
        self.window._metadata_ready(sid, self.data)
        self.assertIs(self.window.stack.currentWidget(), current)

    def test_result_after_profile_switch_only_updates_original_database(self):
        sid = self.seed(year=None)
        original = self.window.db
        original_path = original.path
        replacement = LibraryDatabase(Path(self.temp.name) / 'other.db')
        replacement.set_setting('library_root', str(Path(self.temp.name) / 'other-library'))
        other_sid = self.seed('Other Show', replacement, Path(self.temp.name) / 'other-library', year=2010)
        self.window.db = replacement
        try:
            self.window._metadata_ready(sid, self.data, original_path, 'Example Show')
            self.assertEqual(original.get_series(sid)['release_year'], 2023)
            self.assertEqual(replacement.get_series(other_sid)['release_year'], 2010)
        finally:
            self.window.db = original
            replacement.close()

    def test_download_artwork_result_after_profile_switch_keeps_years_separate(self):
        sid = self.seed(year=2000)
        job = self.queue(1)[0]
        key = self.window._download_metadata_key(job)
        original = self.window.db
        replacement = LibraryDatabase(Path(self.temp.name) / 'other.db')
        other_root = Path(self.temp.name) / 'other-library'
        replacement.set_setting('library_root', str(other_root))
        other_sid = self.seed('Example Show', replacement, other_root, year=2010)
        self.window.db = replacement
        try:
            self.window._download_metadata_ready(key, 'Example Show', self.data)
            self.assertEqual(original.get_series(sid)['release_year'], 2023)
            self.assertEqual(replacement.get_series(other_sid)['release_year'], 2010)
            self.assertEqual(job.artwork['year'], 2023)
        finally:
            self.window.db = original
            replacement.close()

    def test_background_lookup_failure_keeps_downloads_running(self):
        jobs = self.queue(14)
        self.patches[0].stop()
        try:
            self.window._auto_metadata()
            worker = self.mocks[-2].call_args.args[0]
            self.assertTrue(self.window.metadata_lookup_in_progress)
            worker.signals.failed.emit('Metadata unavailable')
            self.assertFalse(self.window.metadata_lookup_in_progress)
            self.assertEqual(self.window.download_queue.active_count, 3)
            self.assertEqual(self.window.download_queue.queued_count, 11)
            self.assertFalse(any(job.status == 'Failed' for job in jobs))
            self.assertFalse(self.window.download_metadata_pending)
        finally:
            self.mocks[0] = self.patches[0].start()

    def test_backfill_checks_old_metadata_once_even_when_year_is_unavailable(self):
        sid = self.seed(year=None)
        self.window.db.connection.execute('UPDATE series SET metadata_year_checked=0 WHERE id=?', (sid,))
        self.window.db.connection.commit()
        self.patches[0].stop()
        try:
            self.window._auto_metadata()
            worker = self.mocks[-2].call_args.args[0]
            worker.signals.done.emit(dict(self.data, year=None))
            self.assertEqual(self.window.db.get_series(sid)['metadata_year_checked'], 1)
            self.window.metadata_attempted.clear()
            calls = self.mocks[-2].call_count
            self.window._auto_metadata()
            self.assertEqual(self.mocks[-2].call_count, calls)
        finally:
            self.mocks[0] = self.patches[0].start()

    def import_path(self):
        path = self.window.library_root / 'Example Show' / 'Season 01' / 'Example Show - S01E01 [Dub].mp4'
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'fixture')
        return path

    def test_first_import_retries_earlier_failed_lookup_once_and_updates_library(self):
        job = self.queue(1)[0]
        key = self.window._download_metadata_key(job)
        self.window.download_metadata_pending.clear()  # Earlier lookup failed before import.
        path = self.import_path()
        self.window._index_download_owner(job, path)
        self.assertEqual(self.window.download_metadata_pending, {key: 'Example Show'})
        self.window.download_metadata_pending.clear()
        self.window._index_download_owner(job, path)
        self.assertFalse(self.window.download_metadata_pending)
        sid = self.window.db.series()[0]['id']
        self.window.show_series(sid)
        self.window._download_metadata_ready(key, 'Example Show', self.data)
        series = self.window.db.get_series(sid)
        self.assertEqual(series['poster_path'], str(self.poster))
        self.assertEqual(series['synopsis'], 'Example synopsis')
        self.assertEqual(self.window.stack.currentWidget().findChild(QLabel, 'seriesReleaseYear').text(), '2023')

    def test_import_during_lookup_does_not_schedule_duplicate(self):
        job = self.queue(1)[0]
        self.window.download_metadata_pending.clear()
        self.window.download_metadata_inflight = self.window._download_metadata_key(job)
        self.window._index_download_owner(job, self.import_path())
        self.assertFalse(self.window.download_metadata_pending)

    def youtube_job(self):
        job = DownloadJob('YouTube video', 'YouTube', 'https://youtu.be/BaW_jenozKc',
                          self.window.db.path, self.window.library_root, 'Default', lambda: None, lambda: None)
        self.window.download_queue.add(job)
        return job

    def test_youtube_thumbnail_after_import_updates_card_library_and_history(self):
        job = self.youtube_job()
        info = dict(title='Example upload', thumbnail='https://i.ytimg.com/vi/BaW_jenozKc/maxresdefault.jpg',
                    upload_date='20261008', description='Video description')
        self.window._youtube_metadata_update(job, info)
        worker = self.mocks[-2].call_args.args[0]
        count = self.mocks[-2].call_count
        self.window._youtube_metadata_update(job, info)
        self.assertEqual(self.mocks[-2].call_count, count)
        path = self.import_path()
        self.window._index_download_owner(job, path)
        self.window.download_queue.finish(job.id, 'Completed', 'Saved', path)
        worker.signals.done.emit(str(self.poster))
        self.assertEqual(self.window.db.series()[0]['poster_path'], str(self.poster))
        self.assertEqual(self.window.db.series()[0]['synopsis'], 'Video description')
        self.assertEqual(self.window.db.series()[0]['release_year'], 2026)
        thumbnail, year = self.window._download_artwork_rows[job.id]
        self.assertFalse(thumbnail.pixmap().isNull())
        self.assertEqual(thumbnail.width(), 140)
        self.assertEqual(year.text(), 'Uploaded 2026')
        self.window.download_queue.jobs.clear(); self.window._restore_download_history()
        self.assertEqual(self.window.download_queue.jobs[job.id].artwork['poster_path'], str(self.poster))
        self.assertFalse(self.window.download_metadata_pending)

    def test_youtube_thumbnail_before_import_preserves_existing_anime_details(self):
        sid = self.seed()
        job = self.youtube_job()
        info = dict(thumbnail='https://i.ytimg.com/vi/BaW_jenozKc/hqdefault.jpg', upload_date='20261008')
        self.window._youtube_metadata_update(job, info)
        self.mocks[-2].call_args.args[0].signals.done.emit(str(self.poster))
        self.window._index_download_owner(job, self.import_path())
        series = self.window.db.get_series(sid)
        self.assertEqual(series['release_year'], 2023)
        self.assertEqual(series['synopsis'], 'Synopsis')
        self.assertEqual(series['metadata_id'], 42)

    def test_youtube_artwork_failure_or_invalid_image_cannot_fail_video(self):
        job = self.youtube_job()
        info = dict(thumbnail='https://i.ytimg.com/vi/BaW_jenozKc/hqdefault.jpg')
        self.window._youtube_metadata_update(job, info)
        worker = self.mocks[-2].call_args.args[0]
        worker.signals.failed.emit('Thumbnail unavailable')
        invalid = Path(self.temp.name) / 'invalid.img'; invalid.write_text('not an image')
        worker.signals.done.emit(str(invalid))
        self.window._index_download_owner(job, self.import_path())
        self.assertEqual(len(self.window.db.all_episodes()), 1)
        self.assertNotEqual(job.status, 'Failed')
        self.assertFalse(job.artwork.get('poster_path'))

    def test_youtube_thumbnail_result_after_profile_switch_updates_original_library(self):
        job = self.youtube_job()
        self.window._youtube_metadata_update(job, dict(thumbnail='https://i.ytimg.com/vi/BaW_jenozKc/hqdefault.jpg'))
        worker = self.mocks[-2].call_args.args[0]
        path = self.import_path()
        self.window._index_download_owner(job, path)
        self.window.download_queue.finish(job.id, 'Completed', 'Saved', path)
        original = self.window.db
        replacement = LibraryDatabase(Path(self.temp.name) / 'other.db')
        other_root = Path(self.temp.name) / 'other-library'
        replacement.set_setting('library_root', str(other_root))
        self.window.db = replacement; self.window.library_root = other_root
        try:
            worker.signals.done.emit(str(self.poster))
            self.assertEqual(original.series()[0]['poster_path'], str(self.poster))
            self.assertFalse(replacement.series())
        finally:
            self.window.db = original; self.window.library_root = job.root
            replacement.close()


if __name__ == '__main__': unittest.main()
