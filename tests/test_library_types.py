import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QLabel, QPushButton
from anime_watcher.database import LibraryDatabase
from anime_watcher.youtube_library import youtube_metadata_path
import test_download_artwork_ui as artwork_fixture


class LibraryTypeDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'library'
        self.db_path = Path(self.temp.name) / 'library.db'
        self.db = LibraryDatabase(self.db_path)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def seed(self, title='Channel', number=1, library_type='Anime'):
        path = self.root / title / 'Season 01' / f'{title} - S01E{number:02d} [Dub].mp4'
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'fixture')
        return self.db.index_download(path, self.root, library_type=library_type)[0]

    def test_old_schema_defaults_to_anime_without_reclassifying_existing_series(self):
        path = Path(self.temp.name) / 'old.db'
        with sqlite3.connect(path) as old:
            old.executescript("CREATE TABLE series(id INTEGER PRIMARY KEY,title TEXT NOT NULL UNIQUE COLLATE NOCASE,display_title TEXT,synopsis TEXT,poster_path TEXT,metadata_id INTEGER,metadata_updated TEXT); INSERT INTO series VALUES(1,'Abridged','Abridged','Details','cover.png',NULL,NULL);")
        old.close()
        old = LibraryDatabase(path)
        try:
            self.assertEqual(old.get_series(1)['library_type'], 'Anime')
            self.assertEqual(old.get_series(1)['poster_path'], 'cover.png')
        finally:
            old.close()

    def test_move_is_reversible_and_preserves_metadata_versions_files_and_progress(self):
        episode = self.seed()
        self.db.update_metadata(episode['series_id'], 'My Channel', 'Description', 'cover.png', None, 2024)
        self.db.save_progress(episode['id'], 400000, 1000000)
        before = dict(self.db.episode(episode['id']))
        for category in ('YouTube', 'Anime', 'YouTube'):
            self.db.set_series_library_type(episode['series_id'], category)
            self.assertEqual(dict(self.db.episode(episode['id'])), before)
            self.assertEqual(self.db.get_series(episode['series_id'])['synopsis'], 'Description')
            self.assertTrue(Path(episode['path']).is_file())
        self.db.scan_library(self.root)
        self.db.close(); self.db = LibraryDatabase(self.db_path)
        self.assertEqual(self.db.get_series(episode['series_id'])['library_type'], 'YouTube')
        self.assertEqual(self.db.episode(episode['id'])['progress_ms'], 400000)
        self.assertEqual(len(self.db.series('My', library_type='YouTube')), 1)
        self.assertFalse(self.db.series(library_type='Anime'))

    def test_new_download_uses_source_but_existing_series_keeps_chosen_tab(self):
        first = self.seed(library_type='YouTube')
        self.seed(number=2)
        self.assertEqual(self.db.get_series(first['series_id'])['library_type'], 'YouTube')
        self.db.set_series_library_type(first['series_id'], 'Anime')
        self.seed(number=3, library_type='YouTube')
        self.assertEqual(self.db.get_series(first['series_id'])['library_type'], 'Anime')

    def test_rename_and_episode_moves_inherit_category_and_keep_actual_thumbnail(self):
        first = self.seed(library_type='YouTube')
        self.db.update_metadata(first['series_id'], 'Channel', 'Description', 'youtube.png', None, 2024)
        self.db.rename_series(first['series_id'], 'Renamed', {first['id']: first['path']})
        series = self.db.get_series(first['series_id'])
        self.assertEqual((series['library_type'], series['poster_path']), ('YouTube', 'youtube.png'))
        target = self.db.relocate_episode(first['id'], first['path'], 'Moved', 2, 3, 'Dub')
        self.assertEqual(self.db.get_series(target)['library_type'], 'YouTube')
        plan = SimpleNamespace(episode_id=first['id'], season=2, episode=3, destination=first['path'], language='Dub')
        target = self.db.relocate_episodes('Bulk moved', [plan])
        self.assertEqual(self.db.get_series(target)['library_type'], 'YouTube')
        anime = self.seed('Anime')
        target = self.db.relocate_episodes('Anime', [plan])
        self.assertEqual(target, anime['series_id'])
        self.assertEqual(self.db.get_series(target)['library_type'], 'Anime')

    def test_bad_category_and_missing_series_are_rejected(self):
        with self.assertRaises(ValueError): self.db.set_series_library_type(100, 'Other')
        with self.assertRaises(ValueError): self.db.set_series_library_type(100, 'YouTube')
        with self.assertRaises(ValueError): self.db.series(library_type='Other')


class LibraryTypeUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        artwork_fixture.DownloadArtworkTests.setUpClass()
        cls.app = artwork_fixture.DownloadArtworkTests.app

    def setUp(self):
        self.fixture = artwork_fixture.DownloadArtworkTests(); self.fixture.setUp()
        self.window = self.fixture.window
        self.anime_id = self.fixture.seed('Anime Show')
        self.youtube_id = self.fixture.seed('Abridged Channel')
        self.window.db.set_series_library_type(self.youtube_id, 'YouTube')

    def tearDown(self):
        self.fixture.tearDown()

    def test_library_tabs_filter_search_and_use_wide_thumbnails(self):
        self.window.show_library()
        tabs = self.window._library_tabs
        self.assertEqual([tabs.tabText(i) for i in range(tabs.count())], ['Anime', 'YouTube'])
        names = lambda index: [label.text() for label in tabs.widget(index).findChildren(QLabel)]
        self.assertIn('Anime Show', names(0)); self.assertNotIn('Abridged Channel', names(0))
        self.assertIn('Abridged Channel', names(1)); self.assertNotIn('Anime Show', names(1))
        thumb = tabs.widget(1).findChild(QLabel, 'seriesThumbnail')
        self.assertEqual((thumb.width(), thumb.height()), (288, 162))
        self.assertEqual((thumb.pixmap().width(), thumb.pixmap().height()), (288, 162))
        tabs.setCurrentIndex(1); self.window._library_search.setText('Abridged')
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertNotIn('Anime Show', names(0)); self.assertIn('Abridged Channel', names(1))
        self.window.show_home(); self.window.show_library()
        self.assertEqual(self.window._library_tabs.currentIndex(), 1)

    def test_series_button_moves_whole_series_both_ways_and_selects_its_library_tab(self):
        before = [dict(row) for row in self.window.db.episodes(self.anime_id)]
        self.window.show_series(self.anime_id)
        self.window.stack.currentWidget().findChild(QPushButton, 'moveLibraryTab').click()
        self.assertEqual(self.window.db.get_series(self.anime_id)['library_type'], 'YouTube')
        self.assertEqual([dict(row) for row in self.window.db.episodes(self.anime_id)], before)
        thumb = self.window.stack.currentWidget().findChild(QLabel, 'seriesDetailThumbnail')
        self.assertEqual((thumb.width(), thumb.height()), (320, 180))
        self.window.stack.currentWidget().findChild(QPushButton, 'moveLibraryTab').click()
        self.assertEqual(self.window.db.get_series(self.anime_id)['library_type'], 'Anime')
        self.assertEqual(self.window.db.setting('library_tab'), 'Anime')

    def test_import_checkbox_classifies_imported_series_without_changing_other_series(self):
        path = Path(self.fixture.temp.name) / 'Imported Channel - S01E01 [Dub].mp4'
        path.write_bytes(b'fixture')
        self.window.show_import(); self.window.import_youtube.setChecked(True)
        with patch('anime_watcher.qt_ui.QMessageBox.information'):
            self.window._organize([path])
        series = self.window.db.series_for_title('Imported Channel')
        self.assertEqual(series['library_type'], 'YouTube')
        self.assertEqual(self.window.db.get_series(self.anime_id)['library_type'], 'Anime')
        self.assertEqual(self.window._library_tabs.currentIndex(), 1)
        self.assertFalse(path.exists())
        self.assertTrue(Path(self.window.db.episodes(series['id'])[0]['path']).is_file())

    def test_unchecked_import_preserves_existing_youtube_category(self):
        path = Path(self.fixture.temp.name) / 'Abridged Channel - S01E02 [Dub].mp4'
        path.write_bytes(b'fixture')
        self.window.show_import()
        self.assertFalse(self.window.import_youtube.isChecked())
        with patch('anime_watcher.qt_ui.QMessageBox.information'):
            self.window._organize([path])
        self.assertEqual(self.window.db.get_series(self.youtube_id)['library_type'], 'YouTube')
        self.assertEqual(len(self.window.db.episodes(self.youtube_id)), 2)

    def test_new_youtube_download_is_classified_in_owning_profile(self):
        from anime_watcher.download_queue import DownloadJob
        path = self.window.library_root / 'New Channel' / 'Season 01' / 'New Channel - S01E01 [Dub].mp4'
        path.parent.mkdir(parents=True); path.write_bytes(b'fixture')
        original = self.window.db
        job = DownloadJob('video', 'YouTube', 'https://youtu.be/example', original.path, self.window.library_root, 'Default', lambda job: None, lambda: None)
        other = LibraryDatabase(Path(self.fixture.temp.name) / 'other.db')
        self.window.db = other
        try:
            self.window._index_download_owner(job, path)
            self.assertEqual(original.series_for_title('New Channel')['library_type'], 'YouTube')
            self.assertFalse(other.series())
        finally:
            self.window.db = original; other.close()

    def test_late_anime_metadata_does_not_overwrite_youtube_series(self):
        key = (self.window.db.path, self.window.library_root, 'abridged channel')
        before = dict(self.window.db.get_series(self.youtube_id))
        self.window._download_metadata_ready(key, 'Abridged Channel', self.fixture.data)
        self.window._metadata_ready(self.youtube_id, self.fixture.data)
        self.assertEqual(dict(self.window.db.get_series(self.youtube_id)), before)

    def test_reclassification_recovers_youtube_thumbnail_and_ignores_stale_reply(self):
        path = self.window.db.episodes(self.anime_id)[0]['path']
        info = dict(thumbnail='https://i.ytimg.com/vi/example/hqdefault.jpg', description='YouTube description', upload_date='20220102')
        youtube_metadata_path(path).write_text(json.dumps(info))
        self.window._move_series_library_tab(self.anime_id, 'YouTube')
        worker = self.fixture.mocks[-2].call_args.args[0]
        worker.signals.done.emit(str(self.fixture.poster))
        series = self.window.db.get_series(self.anime_id)
        self.assertEqual((series['synopsis'], series['release_year']), ('YouTube description', 2022))
        self.window._move_series_library_tab(self.anime_id, 'Anime')
        self.window._youtube_series_thumbnail_ready(self.window.db.path, self.anime_id, series['title'], dict(info, description='Stale'), self.fixture.poster)
        self.assertEqual(self.window.db.get_series(self.anime_id)['synopsis'], 'YouTube description')


if __name__ == '__main__':
    unittest.main()
