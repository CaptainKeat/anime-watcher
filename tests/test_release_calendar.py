import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QTabWidget

from anime_watcher.anilist import calendar_schedule
from anime_watcher.database import LibraryDatabase
from anime_watcher.qt_ui import AnimeWatcherWindow
from anime_watcher.release_calendar import adjacent_month, calendar_range, local_timestamp


class CalendarDataTests(unittest.TestCase):
    def test_api_pagination_keeps_midnight_and_deduplicates_ids(self):
        row = {"mediaId": 12, "episode": 2, "airingAt": 1000}
        with patch("anime_watcher.anilist._graphql", side_effect=[
            {"Page": {"pageInfo": {"hasNextPage": True}, "airingSchedules": [row]}},
            {"Page": {"pageInfo": {"hasNextPage": False}, "airingSchedules": []}},
        ]) as api:
            self.assertEqual(calendar_schedule([12, 12, 0], 1000, 2000), [row])
        self.assertEqual(api.call_args_list[0].args[1], {"ids": [12], "start": 999, "end": 2000, "page": 1})
        self.assertEqual(api.call_args_list[1].args[1]["page"], 2)

    def test_empty_library_does_not_request_anilist(self):
        with patch("anime_watcher.anilist._graphql") as api:
            self.assertEqual(calendar_schedule([], 1, 2), [])
        api.assert_not_called()

    def test_failed_later_page_does_not_return_partial_calendar(self):
        with patch("anime_watcher.anilist._graphql", side_effect=[
            {"Page": {"pageInfo": {"hasNextPage": True}, "airingSchedules": [{"mediaId": 12}]}},
            RuntimeError("offline"),
        ]):
            with self.assertRaisesRegex(RuntimeError, "offline"):
                calendar_schedule([12], 1, 2)

    def test_year_leap_month_and_local_midnight_boundaries(self):
        self.assertEqual(adjacent_month(date(2026, 12, 20), 1), date(2027, 1, 1))
        self.assertEqual(adjacent_month(date(2026, 1, 1), -1), date(2025, 12, 1))
        start, end = calendar_range(date(2024, 2, 1))
        self.assertEqual(start.weekday(), 0)
        self.assertEqual((end - start).days, 42)
        self.assertTrue(start <= date(2024, 2, 29) < end)
        day = date(2026, 11, 1)
        self.assertEqual(datetime.fromtimestamp(local_timestamp(day)), datetime(2026, 11, 1))

    def test_cache_replacement_scope_rescheduling_empty_response_and_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = LibraryDatabase(Path(tmp) / "library.db")
            self.addCleanup(db.close)
            db.connection.execute("INSERT INTO series(title,anilist_id,next_airing_episode,next_airing_at) VALUES('Show',12,1,1000)")
            db.connection.execute("INSERT INTO series(title,anilist_id) VALUES('Other',13)")
            db.connection.commit()
            self.assertEqual(len(db.calendar_events(1000, 2000)), 1)
            db.cache_calendar([12, 13], 1000, 3000, [
                {"mediaId": 12, "episode": 1, "airingAt": 1000},
                {"mediaId": 12, "episode": 2, "airingAt": 2100},
                {"mediaId": 13, "episode": 1, "airingAt": 1100},
            ])
            db.cache_calendar([12], 1000, 2000, [{"mediaId": 12, "episode": 1, "airingAt": 1200}])
            self.assertEqual([e["airing_at"] for e in db.calendar_events(1000, 3000)], [1100, 1200, 2100])
            with self.assertRaises(KeyError): db.cache_calendar([12], 1000, 2000, [{"mediaId": 12}])
            self.assertEqual(len(db.calendar_events(1000, 3000)), 3)
            db.cache_calendar([12], 1000, 2000, [])
            self.assertEqual([e["airing_at"] for e in db.calendar_events(1000, 3000)], [1100, 2100])
            # Re-linking a series never displays the old show's cached schedule.
            db.connection.execute("UPDATE series SET anilist_id=14,next_airing_episode=NULL,next_airing_at=NULL WHERE anilist_id=12")
            db.connection.commit()
            self.assertEqual([e["title"] for e in db.calendar_events(1000, 3000)], ["Other"])
            db.close()


class CalendarUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"APPDATA": self.temp.name}); self.env.start()
        self.patches = [patch.object(AnimeWatcherWindow, name) for name in
                        ("_auto_metadata", "_refresh_release_schedule", "_auto_check_for_app_update", "_report_pending_app_update", "_start_worker")]
        self.mocks = [item.start() for item in self.patches]
        self.window = AnimeWatcherWindow()
        self.window.db.set_setting("calendar_scope", "library")
        self.window.db.set_setting("calendar_view", "month")
        self.window.db.connection.execute("INSERT INTO series(title,anilist_id) VALUES('First show',12)")
        self.window.db.connection.execute("INSERT INTO series(title,anilist_id) VALUES('Second show',13)")
        self.window.db.connection.commit()
        self.window.show_schedule()

    def tearDown(self):
        self.window.close(); self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete); self.app.processEvents()
        for item in reversed(self.patches): item.stop()
        self.env.stop(); self.temp.cleanup()

    def complete_refresh(self, rows):
        worker = self.mocks[-1].call_args.args[0]
        worker.signals.done.emit(rows)

    def test_calendar_navigation_filter_date_agenda_and_series_action(self):
        calendar = self.window._release_calendar
        calendar.month = date(2026, 10, 1); calendar.selected = date(2026, 10, 8)
        at = int(datetime(2026, 10, 8, 23, 30).timestamp())
        self.window._load_calendar_month()
        self.complete_refresh([{"mediaId": 12, "episode": 3, "airingAt": at}, {"mediaId": 13, "episode": 7, "airingAt": at + 60}])
        cell = next(c for c in calendar.cells if c.day == date(2026, 10, 8))
        QTest.mouseClick(cell, Qt.MouseButton.LeftButton)
        self.assertTrue(cell.isChecked())
        self.assertIn("2 episodes", calendar.day_summary.text())
        calendar.filter.setCurrentIndex(calendar.filter.findData(1))
        self.assertEqual(calendar.day_summary.text(), "1 episode scheduled")
        self.assertEqual(len(cell.events), 1)
        self.assertEqual(calendar.days[date(2026, 10, 8)][0]["episode"], 3)
        with patch.object(self.window, "show_series"):
            received = []; calendar.series_requested.connect(received.append)
            button = next(b for b in calendar.findChildren(QPushButton) if b.text().startswith("Open series") and not b.isHidden())
            button.click(); self.assertEqual(received, [1])
        calendar.change_month(1)
        self.assertEqual(calendar.month, date(2026, 11, 1))
        calendar.go_today(); self.assertEqual(calendar.selected, date.today())
        self.assertIn("Schedule", self.window.nav_buttons[6].text())

    def test_offline_keeps_saved_airings_and_retry_is_available(self):
        calendar = self.window._release_calendar
        start, end = calendar.timestamp_range()
        self.complete_refresh([{"mediaId": 12, "episode": 1, "airingAt": start + 3600}])
        self.window._load_calendar_month(force=True)
        self.mocks[-1].call_args.args[0].signals.failed.emit("offline")
        self.assertIn("Showing saved dates", calendar.status.text())
        self.assertEqual(len(calendar.events), 1)
        self.assertTrue(calendar.refresh.isEnabled())

    def test_old_month_response_does_not_replace_visible_month(self):
        calendar = self.window._release_calendar
        old_worker = self.mocks[-1].call_args.args[0]
        start, end = calendar.timestamp_range()
        calendar.change_month(2)
        status = calendar.status.text()
        old_worker.signals.done.emit([{"mediaId": 12, "episode": 1, "airingAt": start + 3600}])
        self.assertEqual(calendar.status.text(), status)
        self.assertEqual(calendar.events, [])
        self.assertEqual(len(self.window.db.calendar_events(start, end)), 1)

    def test_navigation_away_and_profile_change_ignore_stale_callbacks(self):
        old_worker = self.mocks[-1].call_args.args[0]
        original = self.window.db
        new = LibraryDatabase(Path(self.temp.name) / "other.db")
        self.window.db = new
        self.window.show_home()
        old_worker.signals.done.emit([])
        self.assertEqual(original.setting("calendar_last_checked", {}), {})
        self.window.db = original; new.close()

    def test_activity_and_application_updater_remain_separate_and_discoverable(self):
        self.window.db.add_notification("app-update", "Update available", "Version 2", fingerprint="app")
        self.window.db.add_notification("local-dub", "Dub added", "Episode 4", 1, "dub")
        self.window.show_schedule()
        self.assertEqual(self.window.db.unread_notification_count(), 2)
        tabs = self.window.stack.currentWidget().findChild(QTabWidget, "scheduleTabs")
        tabs.setCurrentIndex(1)
        self.assertEqual(self.window.db.unread_notification_count(), 0)
        button = next(b for b in tabs.findChildren(QPushButton) if b.text() == "Open application updates")
        button.click()
        labels = self.window.stack.currentWidget().findChildren(QLabel)
        updates = next(label for label in labels if label.text() == "Application updates")
        profile = next(label for label in labels if label.text() == "Profile")
        self.assertLess(updates.parentWidget().layout().indexOf(updates), profile.parentWidget().layout().indexOf(profile))


if __name__ == "__main__": unittest.main()
