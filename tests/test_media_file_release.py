import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer, QUrl
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication, QMessageBox

from anime_watcher.qt_player import QtMediaPlayer
from anime_watcher.qt_ui import AnimeWatcherWindow


class MediaFileReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_stop_releases_loaded_playing_and_paused_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "media.wav"
            with wave.open(str(path), "wb") as media:
                media.setnchannels(1)
                media.setsampwidth(2)
                media.setframerate(8000)
                media.writeframes(b"\0\0" * 8000 * 10)
            player = QtMediaPlayer()
            player.audio_output.setMuted(True)
            try:
                for state in ("loaded", "playing", "paused"):
                    with self.subTest(state=state):
                        loop = QEventLoop()
                        player.backend.mediaStatusChanged.connect(loop.quit)
                        player.backend.setSource(QUrl.fromLocalFile(str(path)))
                        QTimer.singleShot(3000, loop.quit)
                        loop.exec()
                        player.backend.mediaStatusChanged.disconnect(loop.quit)
                        self.assertNotEqual(player.backend.mediaStatus(), QMediaPlayer.MediaStatus.InvalidMedia)
                        self.assertTrue(player.backend.source().isLocalFile())
                        if state != "loaded":
                            player.backend.play()
                            if state == "paused":
                                player.backend.pause()
                        player.stop()
                        self.assertTrue(player.backend.source().isEmpty())
                        moved = path.with_name("released.wav")
                        # Windows denies this move if the media backend still holds the file.
                        path.rename(moved)
                        moved.rename(path)
            finally:
                player.release()


class EpisodeDeletionTests(unittest.TestCase):
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
        self.root = Path(self.temp.name) / "library"
        self.window.library_root = self.root
        self.path = self.root / "Example" / "Season 01" / "Example - S01E01.mp4"
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"test video")
        other = self.path.with_name("Example - S01E02.mp4")
        other.write_bytes(b"another video")
        with patch("anime_watcher.database.probe_embedded_language", return_value="Unknown"):
            self.window.db.scan_library(self.root)
        self.row = self.window.db.all_episodes()[0]
        self.window.current_episode_id = int(self.row["id"])
        self.window.current_video_path = self.row["path"]
        self.window.known_duration_ms = 120000

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.schedule.stop()
        self.metadata.stop()
        self.env.stop()
        self.temp.cleanup()

    def test_confirmed_delete_saves_progress_and_unloads_before_recycling(self):
        def recycle(path, root):
            self.assertIsNone(self.window.current_episode_id)
            self.assertIsNone(self.window.current_video_path)
            self.assertTrue(self.window.player.backend.source().isEmpty())
            self.assertEqual(self.window.db.episode(self.row["id"])["progress_ms"], 12000)
            Path(path).unlink()

        with patch("anime_watcher.qt_ui.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes), \
                patch("anime_watcher.qt_ui.send_to_recycle_bin", side_effect=recycle) as delete, \
                patch.object(self.window.player, "time", return_value=12000), \
                patch.object(self.window.player, "stop", wraps=self.window.player.stop) as stop, \
                patch("anime_watcher.qt_ui.QMessageBox.critical") as error:
            self.window._delete_episode(self.row["id"])
        stop.assert_called_once()
        delete.assert_called_once()
        error.assert_not_called()
        self.assertFalse(self.path.exists())
        self.assertIsNone(self.window.db.episode(self.row["id"]))
        self.assertEqual(len(self.window.db.all_episodes()), 1)

    def test_cancelled_delete_keeps_playback_and_file(self):
        with patch("anime_watcher.qt_ui.QMessageBox.question", return_value=QMessageBox.StandardButton.No), \
                patch("anime_watcher.qt_ui.send_to_recycle_bin") as delete, \
                patch.object(self.window.player, "stop") as stop:
            self.window._delete_episode(self.row["id"])
        stop.assert_not_called()
        delete.assert_not_called()
        self.assertEqual(self.window.current_episode_id, self.row["id"])
        self.assertTrue(self.path.exists())

    def test_recycle_failure_retains_file_record_and_saved_progress(self):
        with patch("anime_watcher.qt_ui.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes), \
                patch("anime_watcher.qt_ui.send_to_recycle_bin", side_effect=PermissionError("Other process is using the file")), \
                patch.object(self.window.player, "time", return_value=12000), \
                patch("anime_watcher.qt_ui.QMessageBox.critical") as error:
            self.window._delete_episode(self.row["id"])
        error.assert_called_once()
        self.assertTrue(self.path.exists())
        self.assertEqual(self.window.db.episode(self.row["id"])["progress_ms"], 12000)
        self.assertIsNone(self.window.current_episode_id)

    def test_returning_to_library_saves_progress_and_unloads(self):
        with patch.object(self.window.player, "time", return_value=12000), \
                patch.object(self.window.player, "stop", wraps=self.window.player.stop) as stop:
            self.window.show_library()
        stop.assert_called_once()
        self.assertIsNone(self.window.current_episode_id)
        self.assertTrue(self.window.player.backend.source().isEmpty())
        self.assertEqual(self.window.db.episode(self.row["id"])["progress_ms"], 12000)


if __name__ == "__main__":
    unittest.main()
