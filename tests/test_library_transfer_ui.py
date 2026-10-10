import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication, QEvent
from tests import test_download_artwork_ui as fixture_module
from anime_watcher.library_tools import prepare_library_transfer


class LibraryTransferUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): fixture_module.DownloadArtworkTests.setUpClass()

    def setUp(self):
        self.fixture = fixture_module.DownloadArtworkTests(); self.fixture.setUp()
        self.window = self.fixture.window; self.fixture.seed()
        self.target = Path(self.fixture.temp.name) / 'portable'
        self.window.show_settings(); self.window._show_library_transfer()
        self.dialog = self.window.library_transfer_dialog

    def tearDown(self):
        self.window.library_transfer_job = None; self.dialog.set_busy(False); self.dialog.close()
        self.fixture.tearDown()

    def worker(self): return self.fixture.mocks[-2].call_args.args[0]

    def test_review_and_transfer_keeps_history_and_updates_folder(self):
        row = self.window.db.all_episodes()[0]; self.window.db.save_progress(row['id'], 400000, 1200000)
        self.dialog.destination.setText(str(self.target)); self.dialog.review.click(); self.worker().run()
        self.assertTrue(self.dialog.start.isEnabled()); self.assertIn('Originals are kept', self.dialog.status.text())
        with patch.object(self.window, '_stop_phone_access') as stop:
            self.dialog.start.click(); stop.assert_called_once()
            self.worker().run()
        self.assertIsNone(self.window.library_transfer_job)
        self.assertEqual(self.window.library_root, self.target)
        self.assertEqual(self.window.library_entry.text(), str(self.target))
        self.assertEqual(self.window.db.episode(row['id'])['progress_ms'], 400000)
        self.assertEqual(self.dialog.overall.value(), 1000)
        self.assertIn('Original files remain', self.dialog.status.text())

    def test_queue_blocks_review_without_starting_worker(self):
        self.fixture.queue(1)
        count = self.fixture.mocks[-2].call_count
        self.dialog.review_requested.emit(str(self.target))
        self.assertEqual(self.fixture.mocks[-2].call_count, count)
        self.assertIn('queued downloads', self.dialog.status.text())

    def test_pause_escape_and_window_close_wait_for_worker(self):
        cancel = threading.Event(); self.window.library_transfer_job = dict(stage='copy', cancel=cancel)
        self.dialog.set_busy(True, copying=True); self.dialog.reject()
        self.assertTrue(cancel.is_set()); self.assertTrue(self.dialog.isVisible())
        self.dialog.close(); self.assertTrue(self.dialog.isVisible())
        before = self.window.library_root
        self.window._refresh_library(); self.assertIsNone(self.window.library_refresh_job)
        self.assertIsNone(self.window._require_library()); self.assertEqual(self.window.library_root, before)

    def test_failed_copy_requires_review_for_resume_and_retains_folder(self):
        old = self.window.library_root
        self.dialog.show_plan(prepare_library_transfer(self.window.db.path, old, self.target))
        self.window.library_transfer_job = dict(stage='copy', cancel=threading.Event()); self.dialog.set_busy(True, copying=True)
        self.window._library_transfer_failed('Transfer paused.')
        self.assertEqual(self.window.library_root, old); self.assertFalse(self.dialog.start.isEnabled())
        self.assertTrue(self.dialog.review.isEnabled()); self.assertIn('resume', self.dialog.status.text())

    def test_editing_destination_invalidates_review(self):
        self.dialog.show_plan(prepare_library_transfer(self.window.db.path, self.window.library_root, self.target))
        self.assertTrue(self.dialog.start.isEnabled())
        self.dialog.destination.setText(str(self.target / 'other'))
        self.assertFalse(self.dialog.start.isEnabled()); self.assertIsNone(self.dialog.plan)
