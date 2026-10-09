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
        with patch("anime_watcher.qt_ui.QMessageBox.question", side_effect=AssertionError("No update confirmations")), \
                patch("anime_watcher.qt_ui.application_install_dir", return_value=Path(self.temp.name)):
            self.window.sidebar_update_button.click()
        self.assertTrue(self.window.app_update_download_in_progress)
        worker = self.mocks[-1].call_args.args[0]
        self.assertEqual(worker.function.__name__, "stage_update")
        worker.signals.progress.emit((42, 100))
        self.assertIn("42%", self.window.sidebar_update_button.text())
        self.assertEqual(self.window.sidebar_update_progress.value(), 42)
        self.assertEqual(self.window.sidebar_update_progress.maximum(), 100)
        self.assertFalse(self.window.sidebar_update_button.isEnabled())
        with patch("anime_watcher.qt_ui.QMessageBox.warning"):
            worker.signals.failed.emit("offline")
        self.assertTrue(self.window.sidebar_update_button.isEnabled())
        self.assertEqual(self.window.sidebar_update_button.text(), "↓  Update available")

    def test_verified_update_installs_automatically_and_closes_only_after_helper_ready(self):
        self.window._app_update_check_ready(release(), False)
        staged = SimpleNamespace(release=release())
        with patch("anime_watcher.qt_ui.QMessageBox.question", side_effect=AssertionError("No confirmations")), \
                patch.object(self.window, "close") as close:
            self.window._app_update_staged(staged)
            installer = self.mocks[-1].call_args.args[0]
            self.assertEqual(installer.function.__name__, "launch_staged_update")
            self.assertEqual(installer.args, (staged, __version__))
            self.assertFalse(self.window.sidebar_update_button.isEnabled())
            self.assertEqual(self.window.sidebar_update_progress.maximum(), 0)
            close.assert_not_called()
            installer.signals.done.emit(Path(self.temp.name) / 'backup')
            close.assert_called_once()
        with patch.object(self.window, "_check_for_app_update") as check:
            self.window._auto_check_for_app_update(); check.assert_not_called()

    def test_install_failure_stays_open_and_retries_same_staged_package(self):
        self.window._app_update_check_ready(release(), False)
        staged = SimpleNamespace(release=release())
        with patch.object(self.window, "close") as close, \
                patch("anime_watcher.qt_ui.QMessageBox.warning", side_effect=AssertionError("No failure popup")):
            self.window._app_update_staged(staged)
            installer = self.mocks[-1].call_args.args[0]
            installer.signals.failed.emit("Helper did not become ready")
            close.assert_not_called()
            self.assertTrue(self.window.sidebar_update_button.isEnabled())
            self.assertIn("Helper did not become ready", self.window.sidebar_update_status.text())
            self.window.sidebar_update_button.click()
            retried = self.mocks[-1].call_args.args[0]
            self.assertIs(retried.args[0], staged)
            self.assertEqual(retried.function.__name__, "launch_staged_update")

    def test_full_download_to_install_flow_has_no_dialogs_or_duplicate_work(self):
        self.window._app_update_check_ready(release(), True)
        with patch("anime_watcher.qt_ui.application_install_dir", return_value=Path(self.temp.name)), \
                patch.object(self.window, "close") as close, \
                patch("anime_watcher.qt_ui.QMessageBox.question", side_effect=AssertionError("No confirmations")):
            self.window.sidebar_update_button.click()
            download = self.mocks[-1].call_args.args[0]
            calls = self.mocks[-1].call_count
            self.window._start_app_update_download()
            self.assertEqual(self.mocks[-1].call_count, calls)
            download.signals.progress.emit((100, 100))
            self.assertEqual(self.window.app_update_phase, "verifying")
            self.assertEqual(self.window.sidebar_update_progress.maximum(), 0)
            download.signals.done.emit(SimpleNamespace(release=release()))
            installer = self.mocks[-1].call_args.args[0]
            self.assertEqual(self.window.app_update_phase, "installing")
            self.window._start_app_update_download()
            self.assertEqual(self.mocks[-1].call_count, calls + 1)
            close.assert_not_called()
            installer.signals.done.emit(None)
            close.assert_called_once()

    def test_progress_and_errors_survive_settings_navigation(self):
        self.window._app_update_check_ready(release(), False)
        with patch("anime_watcher.qt_ui.application_install_dir", return_value=Path(self.temp.name)):
            self.window.sidebar_update_button.click()
        download = self.mocks[-1].call_args.args[0]
        download.signals.progress.emit((42, 100))
        self.window.show_settings()
        self.assertEqual(self.window.app_update_progress.value(), 42)
        self.window.show_home()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        download.signals.progress.emit((100, 100))
        self.window.show_settings()
        self.assertEqual(self.window.app_update_progress.maximum(), 0)
        self.assertIn("Verifying", self.window.app_update_status.text())
        with patch("anime_watcher.qt_ui.QMessageBox.warning", side_effect=AssertionError("No popup")):
            download.signals.failed.emit("Digest mismatch")
        self.window.show_home()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.window.show_settings()
        self.assertIn("Digest mismatch", self.window.app_update_status.text())
        self.assertTrue(self.window.install_update_button.isEnabled())
        self.assertTrue(self.window.app_update_progress.isHidden())

    def test_manual_checks_and_check_errors_are_inline(self):
        with patch("anime_watcher.qt_ui.QMessageBox.information", side_effect=AssertionError("No check popup")), \
                patch("anime_watcher.qt_ui.QMessageBox.warning", side_effect=AssertionError("No check popup")):
            self.window._app_update_check_ready(release(__version__), True)
            self.assertIn("up to date", self.window.sidebar_update_status.text())
            self.window._app_update_check_ready(release(), True)
            self.assertFalse(self.window.sidebar_update_button.isHidden())
            self.window._app_update_check_failed("offline", True)
            self.assertIn("offline", self.window.sidebar_update_status.text())
            self.assertTrue(self.window.sidebar_update_button.isEnabled())

    def test_delayed_check_cannot_overwrite_an_in_progress_update(self):
        self.window._app_update_check_ready(release(), False)
        self.window.app_update_download_in_progress = True
        self.window.app_update_phase = "verifying"
        self.window._set_app_update_status("Verifying update…")
        self.window._app_update_check_ready(release(__version__), True)
        self.window._app_update_check_failed("offline", True)
        self.assertEqual(self.window.available_app_update.version, "9.0.0")
        self.assertEqual(self.window.app_update_phase, "verifying")
        self.assertEqual(self.window.app_update_message, "Verifying update…")

    def test_install_success_and_rollback_receipts_do_not_open_dialogs(self):
        for success in (True, False):
            receipt = dict(success=success, version="9.0.0", error="Fixture rollback")
            with patch("anime_watcher.qt_ui.read_update_receipt", return_value=receipt), \
                    patch("anime_watcher.qt_ui.mark_update_receipt_reported") as reported, \
                    patch("anime_watcher.qt_ui.QMessageBox.information", side_effect=AssertionError("No receipt popup")), \
                    patch("anime_watcher.qt_ui.QMessageBox.warning", side_effect=AssertionError("No receipt popup")):
                self.patches[2].stop()
                try:
                    self.window._report_pending_app_update()
                finally:
                    self.mocks[2] = self.patches[2].start()
                reported.assert_called_once_with(receipt)
                self.assertIn("successfully" if success else "rolled back", self.window.sidebar_update_status.text())

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
