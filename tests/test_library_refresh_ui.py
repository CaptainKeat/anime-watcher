from pathlib import Path
import unittest
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QLabel
from anime_watcher.database import LibraryDatabase
from tests import test_download_artwork_ui as artwork_fixture


class LibraryRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        artwork_fixture.DownloadArtworkTests.setUpClass()

    def setUp(self):
        self.fixture = artwork_fixture.DownloadArtworkTests(); self.fixture.setUp()
        self.window = self.fixture.window
        self.fixture.seed()
        self.window.show_library()

    def tearDown(self):
        self.fixture.tearDown()

    def file(self, title, episode=1):
        path = self.window.library_root / title / 'Season 01' / f'{title} - S01E{episode:02d} [Dub].mp4'
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'fixture')
        return path

    def start(self):
        self.window._library_refresh_button.click()
        return self.fixture.mocks[-2].call_args.args[0]

    def test_refresh_reads_external_moves_additions_deletions_and_preserves_unchanged_progress(self):
        original = self.window.db.all_episodes()[0]
        self.window.db.save_progress(original['id'], 300000, 1200000)
        self.fixture.seed('Old Show')
        old = next(row for row in self.window.db.all_episodes() if row['series_title'] == 'Old Show')
        moved = self.file('Moved Show'); moved.unlink(); Path(old['path']).rename(moved)
        self.file('Added Show')
        worker = self.start(); worker.run()
        self.assertEqual({row['title'] for row in self.window.db.series()}, {'Example Show', 'Moved Show', 'Added Show'})
        self.assertEqual(self.window.db.episode(original['id'])['progress_ms'], 300000)
        self.assertEqual(self.window.db.get_series(original['series_id'])['metadata_id'], 42)
        self.assertIn('3 episodes', self.window._library_refresh_label.text())
        self.assertIn('1 missing', self.window._library_refresh_label.text())
        self.assertTrue(self.window._library_refresh_button.isEnabled())

    def test_refresh_preserves_search_filter_and_current_page(self):
        self.window._library_search.setText('Added')
        self.file('Added Show')
        page = self.window.stack.currentWidget()
        self.start().run()
        self.assertIs(self.window.stack.currentWidget(), page)
        self.assertEqual(self.window._library_search.text(), 'Added')
        self.assertTrue(any(label.text() == 'Added Show' for label in page.findChildren(QLabel)))

    def test_repeat_clicks_do_not_start_more_scans(self):
        before = self.fixture.mocks[-2].call_count
        self.start()
        self.assertFalse(self.window._library_refresh_button.isEnabled())
        self.assertEqual(self.window._library_refresh_button.text(), 'Refreshing…')
        self.window._refresh_library()
        self.assertEqual(self.fixture.mocks[-2].call_count, before + 1)

    def test_unavailable_root_keeps_index_and_reports_inline_failure(self):
        self.window.library_root = Path(self.fixture.temp.name) / 'offline'
        self.window.db.set_setting('library_root', str(self.window.library_root))
        self.window.show_library()
        self.start().run()
        self.assertEqual(len(self.window.db.series()), 1)
        self.assertIn('unavailable', self.window._library_refresh_label.text())
        self.assertTrue(self.window._library_refresh_button.isEnabled())

    def test_scan_permission_error_does_not_prune_library(self):
        def fail_walk(root, *, onerror):
            onerror(PermissionError('Access denied'))
            return []
        with patch('anime_watcher.organizer.os.walk', side_effect=fail_walk):
            self.start().run()
        self.assertEqual(len(self.window.db.all_episodes()), 1)
        self.assertIn('Access denied', self.window._library_refresh_label.text())

    def test_navigating_away_does_not_force_return_on_completion(self):
        worker = self.start()
        self.window.show_home()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        page = self.window.stack.currentWidget()
        worker.run()
        self.assertIs(self.window.stack.currentWidget(), page)
        self.window.show_library()
        self.assertIn('Library refreshed', self.window._library_refresh_label.text())

    def test_changing_library_folder_discards_prepared_scan(self):
        worker = self.start()
        prepared = worker.function(*worker.args)
        self.window.library_root = Path(self.fixture.temp.name) / 'new-library'
        self.window.db.set_setting('library_root', str(self.window.library_root))
        worker.signals.done.emit(prepared)
        self.assertEqual(len(self.window.db.all_episodes()), 1)
        self.assertIsNone(self.window.library_refresh_job)

    def test_refresh_completion_after_profile_switch_stays_with_original_database(self):
        self.file('Added Show')
        worker = self.start()
        original = self.window.db; root = self.window.library_root
        replacement = LibraryDatabase(Path(self.fixture.temp.name) / 'other.db')
        replacement.set_setting('library_root', str(Path(self.fixture.temp.name) / 'other-library'))
        self.window.db = replacement; self.window.library_root = Path(self.fixture.temp.name) / 'other-library'
        self.window.show_library()
        try:
            worker.run()
            self.assertEqual(len(original.series()), 2)
            self.assertFalse(replacement.series())
            self.assertEqual(self.window._library_refresh_label.text(), '')
        finally:
            self.window.db = original; self.window.library_root = root; replacement.close()

    def test_download_indexed_during_background_scan_is_retained(self):
        worker = self.start(); prepared = worker.function(*worker.args)
        path = self.file('Downloaded Show')
        row, _ = self.window.db.index_download(path, self.window.library_root)
        worker.signals.done.emit(prepared)
        self.assertIsNotNone(self.window.db.episode(row['id']))

    def test_drive_disappearing_after_preparation_does_not_clear_index(self):
        worker = self.start(); prepared = worker.function(*worker.args)
        root = self.window.library_root
        root.rename(root.with_name('temporarily-offline'))
        worker.signals.done.emit(prepared)
        self.assertEqual(len(self.window.db.all_episodes()), 1)
        self.assertIn('unavailable', self.window._library_refresh_label.text())


if __name__ == '__main__':
    unittest.main()
