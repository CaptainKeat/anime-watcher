import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QScrollArea
from anime_watcher.qt_ui import AnimeWatcherWindow, ClickableFrame


class LibraryLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {'APPDATA': self.temp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        for name in ('_auto_metadata', '_refresh_release_schedule', '_auto_check_for_app_update', '_report_pending_app_update'):
            patcher = patch.object(AnimeWatcherWindow, name)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.window = AnimeWatcherWindow()
        self.window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self.series = [dict(id=i, title=f'Example {i:02d}', display_title='', poster_path='', episode_count=12, library_type='Anime') for i in range(30)]
        self.series_patch = patch.object(self.window.db, 'series', side_effect=lambda text='', library_type=None: [row for row in self.series if text.casefold() in row['title'].casefold() and (library_type is None or row['library_type'] == library_type)])
        self.series_patch.start()
        self.addCleanup(self.series_patch.stop)
        self.window.show()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def settle(self):
        for _ in range(5):
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.app.processEvents()
        return self.window.stack.currentWidget().findChildren(ClickableFrame)

    def first_row(self, cards):
        return [card for card in cards if card.y() == cards[0].y()]

    def check_resize(self, show_page):
        self.window.resize(1120, 760)
        show_page()
        cards = self.settle()
        narrow_columns = len(self.first_row(cards))
        self.assertLess(narrow_columns, 6)
        self.window.resize(2400, 1000)
        expanded = self.settle()
        self.assertEqual(expanded, cards)
        wide_row = self.first_row(cards)
        self.assertGreater(len(wide_row), narrow_columns)
        self.assertGreater(len(wide_row), 5)
        self.assertLess(cards[0].parentWidget().width() - wide_row[-1].geometry().right(), 196 + 28)
        self.assertGreater(cards[len(wide_row)].y(), cards[0].y())
        scroll = self.window._library_tabs.currentWidget() if show_page == self.window.show_library else self.window.stack.currentWidget().findChild(QScrollArea)
        self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
        self.window.resize(1120, 760)
        self.settle()
        self.assertEqual(len(self.first_row(cards)), narrow_columns)
        self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
        self.assertGreater(scroll.verticalScrollBar().maximum(), 0)

    def test_library_wraps_on_grow_and_shrink_without_recreating_cards(self):
        self.check_resize(self.window.show_library)

    def test_home_wraps_on_grow_and_shrink_without_recreating_cards(self):
        self.check_resize(self.window.show_home)

    def test_youtube_tab_reflows_wide_cards_on_grow_and_shrink(self):
        for row in self.series:
            row['library_type'] = 'YouTube'
        self.window.db.set_setting('library_tab', 'YouTube')
        self.window.resize(1120, 760); self.window.show_library()
        cards = self.settle(); columns = len(self.first_row(cards))
        self.assertEqual(cards[0].width(), 304)
        self.window.resize(2400, 1000)
        self.assertEqual(self.settle(), cards)
        self.assertGreater(len(self.first_row(cards)), columns)
        self.assertEqual(self.window._library_tabs.currentWidget().horizontalScrollBar().maximum(), 0)
        self.window.resize(1120, 760); self.settle()
        self.assertEqual(len(self.first_row(cards)), columns)
        self.assertGreater(self.window._library_tabs.currentWidget().verticalScrollBar().maximum(), 0)

    def test_continue_watching_does_not_force_home_wider_than_viewport(self):
        episodes = [dict(id=i, series_title=f'Continue example {i}', season=1, episode=3,
                         language='Sub', progress_ms=1000, duration_ms=20000) for i in range(4)]
        with patch.object(self.window.db, 'continue_watching', return_value=episodes):
            self.check_resize(self.window.show_home)

    def test_search_empty_and_filtered_results_reflow_and_keep_click_target(self):
        self.window.resize(2400, 1000)
        self.window.show_library()
        self.settle()
        search = self.window.stack.currentWidget().findChild(QLineEdit)
        search.setText('no matching series')
        self.assertEqual(self.settle(), [])
        search.setText('Example 1')
        cards = self.settle()
        self.assertEqual(len(cards), 10)
        self.assertGreater(len(self.first_row(cards)), 5)
        with patch.object(self.window, 'show_series') as show_series:
            QTest.mouseClick(cards[0], Qt.MouseButton.LeftButton)
            show_series.assert_called_once_with(10)
        self.window.resize(1120, 760)
        self.settle()
        self.assertLess(len(self.first_row(cards)), 5)

    def test_opening_library_after_resize_uses_current_width(self):
        self.window.resize(2400, 1000)
        self.settle()
        self.window.show_library()
        cards = self.settle()
        self.assertGreater(len(self.first_row(cards)), 5)
        self.window.show_home()
        self.assertGreater(len(self.first_row(self.settle())), 5)


if __name__ == '__main__':
    unittest.main()
