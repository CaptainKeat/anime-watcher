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
        self.window.db.set_setting("library_root", str(self.window.library_root))
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
        self.assertTrue(self.window.youtube_download_button.isEnabled())
        job = next(iter(self.window.download_queue.jobs.values()))
        runtime = self.window.youtube_jobs[job.id]
        self.window.show_home()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        worker.signals.progress.emit((8 * 1048576, 16 * 1048576, "Downloading…"))
        self.window.show_downloads()
        self.assertEqual(self.window._download_rows[job.id][2].value(), 500)
        self.assertIn("8.0", self.window._download_rows[job.id][1].text())
        self.assertEqual(self.window.youtube_quality.currentData(), "720p")
        self.window.download_queue.cancel(job.id)
        self.assertTrue(runtime["cancel"].is_set())
        self.assertFalse(self.window._download_rows[job.id][3].isEnabled())
        worker.signals.failed.emit("Download cancelled.")
        self.assertNotIn(job.id, self.window.youtube_jobs)
        self.assertTrue(self.window.youtube_download_button.isEnabled())
        self.assertEqual(job.status, "Cancelled")

    def test_completion_indexes_current_download_and_handles_page_navigation(self):
        worker = self.start_download()
        self.window.show_home()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        with patch.object(self.window, "_index_download_owner") as index:
            worker.signals.done.emit(SimpleNamespace(status="moved", destination=Path("video.mp4")))
        index.assert_called_once_with(next(iter(self.window.download_queue.jobs.values())), Path("video.mp4"))
        self.window.show_downloads()
        job = next(iter(self.window.download_queue.jobs.values()))
        self.assertEqual(self.window._download_rows[job.id][2].value(), 1000)
        self.assertEqual(job.status, "Completed")

    def test_completed_old_profile_job_does_not_scan_new_profile(self):
        worker = self.start_download()
        next(iter(self.window.download_queue.jobs.values())).database = Path(self.temp.name) / "other-profile.db"
        with patch.object(self.window, "_scan") as scan:
            worker.signals.done.emit(SimpleNamespace(status="moved", destination=Path("video.mp4")))
        scan.assert_not_called()

    def test_close_requests_cancellation(self):
        self.start_download()
        cancel = next(iter(self.window.youtube_jobs.values()))["cancel"]
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

    def add_video(self, video_id):
        self.window.youtube_url.setText(f"https://youtu.be/{video_id}")
        self.window.youtube_rights.setChecked(True)
        return self.window._start_youtube_download()

    def test_add_more_videos_keeps_find_videos_and_animates_with_one_active(self):
        self.window.download_queue.limit = 1
        page = self.window.stack.currentWidget()
        with patch.object(self.window, "_start_worker") as start:
            jobs = [self.add_video(video_id) for video_id in ('BaW_jenozKc', 'YE7VzlLtp-4', 'aqz-KE-bpKQ')]
        self.assertEqual(start.call_count, 1)
        self.assertEqual([job.status for job in jobs], ['Connecting', 'Queued', 'Queued'])
        self.assertEqual(self.window.download_queue.remaining_count, 3)
        self.assertEqual(self.window.download_tabs.currentIndex(), 0)
        self.assertIs(self.window.stack.currentWidget(), page)
        self.assertIsNotNone(self.window._download_flyout)
        self.assertTrue(self.window.youtube_download_button.isEnabled())
        self.assertTrue(self.window.youtube_url.isEnabled())
        self.assertEqual(self.window.youtube_url.text(), '')
        self.assertIn('(3)', self.window.download_tabs.tabText(1))

    def test_duplicate_url_reuses_job_even_with_different_tracking_parameters(self):
        with patch.object(self.window, '_start_worker') as start:
            first = self.add_video('BaW_jenozKc')
            self.window.youtube_url.setText('https://www.youtube.com/watch?v=BaW_jenozKc&list=PLignored')
            second = self.window._start_youtube_download()
        self.assertIs(first, second)
        self.assertEqual(len(self.window.download_queue.jobs), 1)
        self.assertEqual(start.call_count, 1)

    def test_cancel_queued_video_does_not_start_it_and_next_keeps_its_options(self):
        self.window.download_queue.limit = 1
        with patch.object(self.window, '_start_worker') as start:
            first = self.add_video('BaW_jenozKc'); worker = start.call_args.args[0]
            second = self.add_video('YE7VzlLtp-4')
            self.window.youtube_series.setEditText('Selected Series')
            self.window.youtube_quality.setCurrentIndex(2)
            self.window.youtube_season.setValue(2); self.window.youtube_episode.setValue(9)
            third = self.add_video('aqz-KE-bpKQ')
            self.window.youtube_series.setEditText('Different Series')
            self.window.youtube_quality.setCurrentIndex(0)
            self.window.download_queue.cancel(second.id)
            self.assertEqual(second.status, 'Cancelled')
            self.assertEqual(start.call_count, 1)
            worker.signals.failed.emit('Server unavailable')
            next_worker = start.call_args.args[0]
        self.assertEqual(start.call_count, 2)
        self.assertEqual(third.status, 'Connecting')
        self.assertEqual(next_worker.args[0], third.url)
        self.assertEqual(next_worker.args[3], '720p')
        self.assertEqual(next_worker.function.keywords['target_title'], 'Selected Series')
        self.assertEqual(next_worker.function.keywords['episode'], 9)

    def test_concurrent_progress_metadata_and_cancel_stay_with_each_video(self):
        self.window.download_queue.limit = 2
        with patch.object(self.window, '_start_worker') as start:
            first = self.add_video('BaW_jenozKc'); first_worker = start.call_args.args[0]
            second = self.add_video('YE7VzlLtp-4'); second_worker = start.call_args.args[0]
        first_worker.signals.progress.emit((10, 100, 'Downloading…'))
        second_worker.signals.progress.emit((70, 200, 'Downloading…'))
        first_worker.signals.metadata.emit({'title': 'First video'})
        second_worker.signals.metadata.emit({'title': 'Second video'})
        self.window.download_queue.cancel(first.id)
        first_worker.signals.progress.emit((90, 100, 'Downloading…'))
        first_worker.signals.failed.emit('Download cancelled')
        self.assertEqual(first.status, 'Cancelled'); self.assertEqual(first.received, 10)
        self.assertEqual((second.title, second.received, second.total), ('Second video', 70, 200))
        self.assertFalse(self.window.youtube_jobs[second.id]['cancel'].is_set())
        self.assertEqual(second.status, 'Downloading')

    def test_retry_keeps_card_id_and_ignores_previous_attempt_callbacks(self):
        with patch.object(self.window, '_start_worker') as start:
            job = self.add_video('BaW_jenozKc'); old = start.call_args.args[0]
            old.signals.failed.emit('Network error')
            card = self.window._download_rows[job.id][0].parentWidget()
            self.window._download_rows[job.id][3].click()
            new = start.call_args.args[0]
        self.assertEqual(start.call_count, 2)
        self.assertIsNot(old, new)
        self.assertEqual(len(self.window.download_queue.jobs), 1)
        self.assertIs(self.window._download_rows[job.id][0].parentWidget(), card)
        old.signals.progress.emit((50, 100, 'Downloading…'))
        old.signals.failed.emit('Old failure')
        self.assertEqual(job.status, 'Connecting'); self.assertEqual(job.received, 0)
        new.signals.progress.emit((20, 100, 'Downloading…'))
        self.assertEqual(job.received, 20)
        self.assertEqual(self.window.download_queue.failed_count, 0)

    def test_queued_worker_reads_fresh_library_snapshot_after_first_import(self):
        self.window.download_queue.limit = 1
        with patch.object(self.window, '_start_worker') as start:
            first = self.add_video('BaW_jenozKc'); worker = start.call_args.args[0]
            second = self.add_video('YE7VzlLtp-4')
            target = self.window.library_root / 'Selected Series' / 'Season 01' / 'YouTube - S01E01 - First video.mp4'
            target.parent.mkdir(parents=True); target.write_bytes(b'video fixture')
            worker.signals.done.emit(SimpleNamespace(status='moved', destination=target))
            snapshot = start.call_args.args[0].function.keywords['library_series']
        self.assertEqual(first.status, 'Completed'); self.assertEqual(second.status, 'Connecting')
        self.assertEqual(snapshot[0]['title'], 'Selected Series')
        self.assertEqual(snapshot[0]['episodes'][0]['episode'], 1)

    def test_queued_video_uses_original_profile_after_switch(self):
        from anime_watcher.database import LibraryDatabase
        self.window.download_queue.limit = 1
        original_root = self.window.library_root
        original_database = self.window.db.path
        with patch.object(self.window, '_start_worker') as start:
            self.add_video('BaW_jenozKc'); worker = start.call_args.args[0]
            second = self.add_video('YE7VzlLtp-4')
            self.window.db.close()
            self.window.db = LibraryDatabase(Path(self.temp.name) / 'other.db')
            self.window.library_root = Path(self.temp.name) / 'other-library'
            self.window.db.set_setting('library_root', str(self.window.library_root))
            worker.signals.failed.emit('Network error')
            next_worker = start.call_args.args[0]
        self.assertEqual(second.database, original_database)
        self.assertEqual(next_worker.args[2], original_root)
        self.assertEqual(second.status, 'Connecting')

    def test_saved_failed_youtube_job_restores_retry_with_original_options(self):
        with patch.object(self.window, '_start_worker') as start:
            job = self.add_video('BaW_jenozKc')
            start.call_args.args[0].signals.failed.emit('Network error')
        self.window._save_download_snapshot()
        self.window.download_queue.jobs.clear()
        self.window._restore_download_history()
        restored = self.window.download_queue.jobs[job.id]
        self.assertEqual(restored.retry_data, job.retry_data)
        with patch.object(self.window, '_start_worker') as start:
            self.window._retry_download(restored)
        self.assertEqual(start.call_count, 1)
        self.assertEqual(restored.status, 'Connecting')

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
