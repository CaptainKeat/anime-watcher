import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QPushButton
from anime_watcher.anilist import current_airing_schedule
from anime_watcher.database import LibraryDatabase
from anime_watcher.qt_ui import AnimeWatcherWindow


def airing(media_id=12, episode=1, at=1000, title="Current show", romaji=None, **media):
    return {"mediaId": media_id, "episode": episode, "airingAt": at,
            "media": {"id": media_id, "type": "ANIME", "isAdult": False, "title": {"english": title, "romaji": romaji}, **media}}


class CurrentAiringsDataTests(unittest.TestCase):
    def test_public_query_paginates_filters_and_deduplicates_without_account_or_ids(self):
        pages = [
            {"Page": {"pageInfo": {"hasNextPage": True}, "airingSchedules": [
                airing(), airing(13, isAdult=True), airing(14, type="MANGA"), airing(15, at=2000), airing(16, at=999), airing(17, title=None, romaji="Fallback"),
            ]}},
            {"Page": {"pageInfo": {"hasNextPage": False}, "airingSchedules": [airing(at=1100)]}},
        ]
        with patch("anime_watcher.anilist._graphql", side_effect=pages) as api, patch("anime_watcher.anilist.time.sleep"):
            progress = []; rows = current_airing_schedule(1000, 2000, progress.append)
        self.assertEqual([(row["mediaId"], row["airingAt"]) for row in rows], [(17, 1000), (12, 1100)])
        self.assertEqual(rows[0]["title"], "Fallback")
        self.assertEqual(api.call_args_list[0].args[1], {"start": 999, "end": 2000, "page": 1})
        self.assertEqual(progress, [2, 2])

    def test_failed_public_pagination_never_returns_partial_results(self):
        with patch("anime_watcher.anilist._graphql", side_effect=[
            {"Page": {"pageInfo": {"hasNextPage": True}, "airingSchedules": [airing()]}}, RuntimeError("rate limit"),
        ]), patch("anime_watcher.anilist.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "rate limit"): current_airing_schedule(1000, 2000)

    def test_public_cache_is_separate_atomic_and_relinks_to_existing_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = LibraryDatabase(Path(tmp) / "library.db")
            try:
                db.connection.execute("INSERT INTO series(title,anilist_id) VALUES('Library show',12)"); db.connection.commit()
                db.cache_calendar([12], 1000, 2000, [{"mediaId": 12, "episode": 5, "airingAt": 1500}])
                db.cache_public_calendar(1000, 2000, [{"mediaId": 12, "episode": 1, "airingAt": 1000, "title": "Public title"}])
                db.cache_public_calendar(2000, 3000, [{"mediaId": 13, "episode": 2, "airingAt": 2100, "title": "Other"}])
                self.assertEqual(db.public_calendar_events(1000, 2000)[0]["series_id"], 1)
                self.assertIsNone(db.public_calendar_events(2000, 3000)[0]["series_id"])
                with self.assertRaises(KeyError): db.cache_public_calendar(1000, 2000, [{"mediaId": 12}])
                self.assertEqual(len(db.public_calendar_events(1000, 3000)), 2)
                db.cache_public_calendar(1000, 2000, [])
                self.assertEqual(len(db.public_calendar_events(1000, 3000)), 1)
                self.assertEqual(db.calendar_events(1000, 2000)[0]["episode"], 5)
                self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM series").fetchone()[0], 1)
            finally: db.close()


class CurrentAiringsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"APPDATA": self.temp.name}); self.env.start()
        self.patches = [patch.object(AnimeWatcherWindow, name) for name in
                        ("_auto_metadata", "_refresh_release_schedule", "_auto_check_for_app_update", "_report_pending_app_update", "_start_worker")]
        self.mocks = [item.start() for item in self.patches]
        self.window = AnimeWatcherWindow(); self.window.show_schedule()
        self.calendar = self.window._release_calendar

    def tearDown(self):
        self.window.close(); self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete); self.app.processEvents()
        for item in reversed(self.patches): item.stop()
        self.env.stop(); self.temp.cleanup()

    def finish(self):
        start, _ = self.calendar.timestamp_range()
        rows = [{"mediaId": 12, "episode": 3, "airingAt": start + 3600, "title": "New show"},
                {"mediaId": 13, "episode": 7, "airingAt": start + 7200, "title": "Other show"}]
        self.mocks[-1].call_args.args[0].signals.done.emit(rows)
        return rows

    def test_default_public_week_works_with_empty_library_and_navigation(self):
        self.assertEqual(self.calendar.source.currentData(), "current")
        self.assertEqual(self.calendar.view.currentData(), "week")
        self.assertEqual(self.mocks[-1].call_args.args[0].function, current_airing_schedule)
        self.finish()
        self.assertIn("2 confirmed episodes this week", self.calendar.summary.text())
        self.assertEqual(sum(not cell.isHidden() for cell in self.calendar.cells), 7)
        previous = self.calendar.selected
        self.calendar.change_period(1)
        self.assertEqual(self.calendar.selected, previous + timedelta(days=7))
        self.calendar.go_today(); self.assertEqual(self.calendar.selected, date.today())
        self.assertEqual(len(self.window.db.linked_series()), 0)

    def test_public_day_details_filter_and_safe_anilist_link(self):
        self.finish(); day = self.calendar.cells[0].day
        self.calendar.select_day(day)
        self.assertEqual(self.calendar.day_summary.text(), "2 episodes scheduled")
        self.calendar.filter.setCurrentIndex(self.calendar.filter.findData(12))
        self.assertEqual(self.calendar.day_summary.text(), "1 episode scheduled")
        button = self.calendar.agenda.itemAt(0).widget().findChild(QPushButton)
        with patch("anime_watcher.qt_ui.webbrowser.open") as browser:
            button.click(); browser.assert_called_once_with("https://anilist.co/anime/12")

    def test_switching_scope_ignores_late_public_response_and_preserves_library_mode(self):
        old = self.mocks[-1].call_args.args[0]
        start, _ = self.calendar.timestamp_range()
        self.calendar.source.setCurrentIndex(self.calendar.source.findData("library"))
        before = self.calendar.status.text()
        old.signals.progress.emit((99,))
        old.signals.done.emit([{"mediaId": 12, "episode": 1, "airingAt": start, "title": "Public show"}])
        self.assertEqual(self.calendar.events, [])
        self.assertEqual(self.calendar.status.text(), before)
        self.assertEqual(len(self.window.db.public_calendar_events(start, start + 86400)), 1)
        self.window.show_schedule()
        self.assertEqual(self.window._release_calendar.source.currentData(), "library")

    def test_month_switch_and_offline_refresh_keep_confirmed_data(self):
        self.finish()
        self.calendar.view.setCurrentIndex(self.calendar.view.findData("month"))
        self.assertEqual(sum(not cell.isHidden() for cell in self.calendar.cells), 42)
        worker = self.mocks[-1].call_args.args[0]
        self.assertEqual(worker.function, current_airing_schedule)
        worker.signals.failed.emit("offline")
        self.assertIn("Showing saved dates", self.calendar.status.text())
        self.assertEqual(len(self.calendar.events), 2)

    def test_existing_library_show_opens_series_without_importing_public_shows(self):
        self.window.db.connection.execute("INSERT INTO series(title,anilist_id) VALUES('Existing show',12)"); self.window.db.connection.commit()
        self.finish(); self.calendar.select_day(self.calendar.cells[0].day)
        self.calendar.filter.setCurrentIndex(self.calendar.filter.findData(12))
        button = self.calendar.agenda.itemAt(0).widget().findChild(QPushButton)
        self.assertEqual(button.text(), "Open series  →")
        received = []; self.calendar.series_requested.connect(received.append)
        button.click(); self.assertEqual(received, [1])
        self.assertEqual(self.window.db.connection.execute("SELECT COUNT(*) FROM series").fetchone()[0], 1)

    def test_month_grid_fits_minimum_window_without_overlapping_rows(self):
        self.window.resize(1080, 680); self.window.show(); self.app.processEvents()
        self.calendar.view.setCurrentIndex(self.calendar.view.findData("month")); self.app.processEvents()
        top, following = self.calendar.cells[0], self.calendar.cells[7]
        self.assertLess(top.geometry().bottom(), following.y())
        last = self.calendar.cells[-1]
        self.assertLess(last.mapTo(self.window, last.rect().bottomRight()).y(), self.window.height())


if __name__ == "__main__": unittest.main()
