import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox
from anime_watcher import __version__
from anime_watcher.qt_ui import AnimeWatcherWindow
from anime_watcher.updater import ReleaseAsset, ReleaseInfo


def release(version="9.0.0"):
    return ReleaseInfo(version, f"v{version}", "Anime Watcher", "", "", "",
                       ReleaseAsset(f"Anime-Watcher-v{version}-Windows.zip", "https://github.com/CaptainKeat/anime-watcher/releases/download/test.zip", 10, "a" * 64))


class AppUpdateUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"APPDATA": self.temp.name}); self.env.start()
        self.patches = [patch.object(AnimeWatcherWindow, name) for name in
                        ("_auto_metadata", "_refresh_release_schedule", "_report_pending_app_update", "_start_worker")]
        self.mocks = [item.start() for item in self.patches]
        self.window = AnimeWatcherWindow()
        self.tray = patch.object(self.window.tray, "showMessage"); self.tray.start()

    def tearDown(self):
        self.window.close(); self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete); self.app.processEvents()
        self.tray.stop()
        for item in reversed(self.patches): item.stop()
        self.env.stop(); self.temp.cleanup()

    def test_auto_discovery_exposes_blue_button_without_opening_settings(self):
        button = self.window.sidebar_update_button
        self.assertTrue(button.isHidden())
        self.window._auto_check_for_app_update()
        worker = self.mocks[-1].call_args.args[0]
        worker.signals.done.emit(release())
        self.assertFalse(button.isHidden())
        self.assertEqual(button.text(), "↓  Update available")
        self.assertIn("9.0.0", button.toolTip())
        current = self.window.stack.currentWidget()
        with patch.object(self.window, "_start_app_update_download") as start:
            button.click(); start.assert_called_once()
        self.assertIs(self.window.stack.currentWidget(), current)

    def test_button_survives_navigation_and_deleted_settings_widgets(self):
        self.window._app_update_check_ready(release(), False)
        button = self.window.sidebar_update_button
        self.window.show_settings(); self.assertFalse(self.window.install_update_button.isHidden())
        self.window.show_schedule()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.window._refresh_app_update_button()
        self.assertFalse(button.isHidden())
        self.assertIs(button.parentWidget(), self.window.sidebar)

    def test_sidebar_click_starts_verified_download_progress_and_allows_failure_retry(self):
        self.window._app_update_check_ready(release(), False)
        with patch("anime_watcher.qt_ui.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes), \
                patch("anime_watcher.qt_ui.application_install_dir", return_value=Path(self.temp.name)):
            self.window.sidebar_update_button.click()
        self.assertTrue(self.window.app_update_download_in_progress)
        worker = self.mocks[-1].call_args.args[0]
        self.assertEqual(worker.function.__name__, "stage_update")
        worker.signals.progress.emit((42, 100))
        self.assertIn("42%", self.window.sidebar_update_button.text())
        self.assertFalse(self.window.sidebar_update_button.isEnabled())
        with patch("anime_watcher.qt_ui.QMessageBox.warning"):
            worker.signals.failed.emit("offline")
        self.assertTrue(self.window.sidebar_update_button.isEnabled())
        self.assertEqual(self.window.sidebar_update_button.text(), "↓  Update available")

    def test_ready_update_remains_visible_if_restart_is_deferred(self):
        self.window._app_update_check_ready(release(), False)
        staged = SimpleNamespace(release=release())
        with patch.object(self.window, "_confirm_staged_app_update") as confirm:
            self.window._app_update_staged(staged)
            self.assertEqual(self.window.sidebar_update_button.text(), "↑  Restart to update")
            self.window.sidebar_update_button.click()
            self.assertEqual(confirm.call_count, 2)
        with patch.object(self.window, "_check_for_app_update") as check:
            self.window._auto_check_for_app_update(); check.assert_not_called()

    def test_current_version_hides_notice_and_check_failure_keeps_known_update(self):
        self.window._app_update_check_ready(release(), False)
        self.window._app_update_check_failed("offline", False)
        self.assertFalse(self.window.sidebar_update_button.isHidden())
        self.window._app_update_check_ready(release(__version__), False)
        self.assertTrue(self.window.sidebar_update_button.isHidden())

    def test_checks_on_each_launch_then_every_six_hours_and_honors_opt_out(self):
        now = time.time()
        self.window.db.set_setting("app_update_last_check", now)
        with patch.object(self.window, "_check_for_app_update") as check:
            self.window._auto_check_for_app_update(); check.assert_called_once_with(manual=False)
            check.reset_mock(); self.window._app_update_checked_this_session = True
            self.window._auto_check_for_app_update(); check.assert_not_called()
            self.window.db.set_setting("app_update_last_check", now - 6 * 3600 - 1)
            self.window._auto_check_for_app_update(); check.assert_called_once()
            check.reset_mock(); self.window.db.set_setting("app_update_auto_check", False)
            self.window._auto_check_for_app_update(); check.assert_not_called()
        self.assertTrue(self.window.app_update_timer.isActive())

    def test_failed_check_retries_after_backoff_without_overlapping_work(self):
        self.window._app_update_check_failed("offline", False)
        with patch.object(self.window, "_check_for_app_update") as check:
            self.window._auto_check_for_app_update(); check.assert_not_called()
            self.window._app_update_retry_at = time.time() - 1
            self.window._auto_check_for_app_update(); check.assert_called_once()
            check.reset_mock(); self.window.app_update_download_in_progress = True
            self.window._auto_check_for_app_update(); check.assert_not_called()


if __name__ == "__main__": unittest.main()
