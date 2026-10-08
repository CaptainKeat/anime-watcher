import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QSpinBox

from anime_watcher.qt_ui import AnimeWatcherWindow


class YouTubeUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"APPDATA": self.temp.name})
        self.env.start()
        self.metadata = patch.object(AnimeWatcherWindow, "_auto_metadata")
        self.schedule = patch.object(AnimeWatcherWindow, "_refresh_release_schedule")
        self.metadata.start()
        self.schedule.start()
        self.window = AnimeWatcherWindow()
        self.window.library_root = Path(self.temp.name) / "library"
        self.window.show_downloads()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.schedule.stop()
        self.metadata.stop()
        self.env.stop()
        self.temp.cleanup()

    def start_download(self):
        self.window.youtube_url.setText("https://youtu.be/BaW_jenozKc?list=ignored")
        self.window.youtube_rights.setChecked(True)
        self.window.youtube_quality.setCurrentIndex(2)
        with patch.object(self.window, "_start_worker") as start:
            self.window._start_youtube_download()
        self.assertEqual(start.call_count, 1)
        return start.call_args.args[0]

    def test_permission_and_invalid_url_do_not_start_a_worker(self):
        with patch("anime_watcher.qt_ui.QMessageBox.warning") as warning, patch.object(self.window, "_start_worker") as start:
            self.window._start_youtube_download()
            self.window.youtube_rights.setChecked(True)
            self.window.youtube_url.setText("https://youtube.com/playlist?list=PLtest")
            self.window._start_youtube_download()
        self.assertEqual(warning.call_count, 2)
        start.assert_not_called()

    def test_progress_survives_page_deletion_and_cancellation_restores_controls(self):
        worker = self.start_download()
        self.assertFalse(self.window.youtube_download_button.isEnabled())
        self.window.show_home()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        worker.signals.progress.emit((8 * 1048576, 16 * 1048576, "Downloading…"))
        self.window.show_downloads()
        self.assertEqual(self.window.youtube_progress.value(), 500)
        self.assertIn("8.0 MB", self.window.youtube_label.text())
        self.assertEqual(self.window.youtube_quality.currentData(), "720p")
        self.window._cancel_youtube_download()
        self.assertTrue(self.window.youtube_job["cancel"].is_set())
        self.assertFalse(self.window.youtube_cancel_button.isEnabled())
        worker.signals.failed.emit("Download cancelled.")
        self.assertIsNone(self.window.youtube_job)
        self.assertTrue(self.window.youtube_download_button.isEnabled())
        self.assertEqual(self.window.youtube_label.text(), "Download cancelled.")

    def test_completion_scans_current_library_and_handles_page_navigation(self):
        worker = self.start_download()
        self.window.show_home()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        with patch.object(self.window, "_scan") as scan:
            worker.signals.done.emit(SimpleNamespace(status="moved", destination=Path("video.mp4")))
        scan.assert_called_once_with(False)
        self.window.show_downloads()
        self.assertEqual(self.window.youtube_progress.value(), 1000)
        self.assertIn("Added:", self.window.youtube_label.text())

    def test_completed_old_profile_job_does_not_scan_new_profile(self):
        worker = self.start_download()
        self.window.youtube_job["database"] = Path(self.temp.name) / "other-profile.db"
        with patch.object(self.window, "_scan") as scan:
            worker.signals.done.emit(SimpleNamespace(status="moved", destination=Path("video.mp4")))
        scan.assert_not_called()

    def test_close_requests_cancellation(self):
        self.start_download()
        cancel = self.window.youtube_job["cancel"]
        self.window.close()
        self.assertTrue(cancel.is_set())

    def test_selected_series_and_slot_are_passed_to_download_worker(self):
        self.window.youtube_series.setEditText("My new series")
        self.window.youtube_season.setValue(2)
        self.window.youtube_episode.setValue(10)
        worker = self.start_download()
        self.assertEqual(worker.function.keywords["target_title"], "My new series")
        self.assertEqual(worker.function.keywords["season"], 2)
        self.assertEqual(worker.function.keywords["episode"], 10)

    def test_move_dialog_suggests_episode_and_preserves_progress(self):
        root = self.window.library_root
        previous = root / "Example Show" / "Season 01" / "Example Show - S01E09.mp4"
        source = root / "Example Show： Episode 10 [Picf46N3668]" / "Season 01" / "YouTube - S01E00 - Example Show： Episode 10 [Picf46N3668].mp4"
        for path in (previous, source):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"video")
        with patch("anime_watcher.database.probe_embedded_language", return_value="Unknown"):
            self.window.db.scan_library(root)
        row = next(row for row in self.window.db.all_episodes() if row["path"] == str(source))
        self.window.db.save_progress(row["id"], 300000, 1200000)

        def choose(dialog):
            target = dialog.findChild(QComboBox)
            target.setCurrentIndex(target.findData("Example Show"))
            spins = dialog.findChildren(QSpinBox)
            self.assertEqual([spin.value() for spin in spins], [1, 10])
            return QDialog.DialogCode.Accepted

        with patch.object(QDialog, "exec", choose), patch("anime_watcher.qt_ui.QMessageBox.critical") as error:
            self.window._move_episode(row["id"])
        error.assert_not_called()
        moved = self.window.db.episode(row["id"])
        self.assertEqual(moved["episode"], 10)
        self.assertEqual(moved["series_title"], "Example Show")
        self.assertEqual(moved["progress_ms"], 300000)
        self.assertFalse(source.exists())


if __name__ == "__main__":
    unittest.main()
