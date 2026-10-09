import unittest
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QLabel, QPushButton
from anime_watcher.downloader import CatalogResult
from tests import test_download_artwork_ui as artwork_fixture


class CatalogArtworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        artwork_fixture.DownloadArtworkTests.setUpClass()

    def setUp(self):
        self.fixture = artwork_fixture.DownloadArtworkTests(); self.fixture.setUp()
        self.window = self.fixture.window

    def tearDown(self):
        self.fixture.tearDown()

    def results(self, titles=('Example Show',)):
        self.window._catalog_results_ready([CatalogResult(title, f'https://catalog.example/show/{n}') for n, title in enumerate(titles)])

    def row(self, index=0):
        return self.window.catalog_results.itemAt(index).widget()

    def test_search_rows_show_cached_library_poster_and_year_before_download(self):
        self.fixture.seed()
        self.results()
        row = self.row()
        self.assertFalse(row.findChild(QLabel, 'catalogThumbnail').pixmap().isNull())
        self.assertEqual(row.findChild(QLabel, 'catalogReleaseYear').text(), '2023')
        self.assertFalse(self.window.catalog_artwork_pending)
        self.assertFalse(self.window.download_queue.jobs)
        with patch.object(self.window, '_load_catalog_episodes') as load:
            next(b for b in row.findChildren(QPushButton) if b.text() == 'View episodes').click()
        self.assertEqual(load.call_args.args[0].title, 'Example Show')

    def test_search_lookups_are_deduplicated_and_reused_for_episode_import(self):
        self.results(('Example Show', 'Example Show'))
        self.assertEqual(len(self.window.catalog_artwork_pending), 1)
        key = next(iter(self.window.catalog_artwork_pending))
        self.window._catalog_artwork_ready(key, 'Example Show', self.fixture.data)
        for index in range(2):
            self.assertEqual(self.row(index).findChild(QLabel, 'catalogReleaseYear').text(), '2023')
        self.assertFalse(self.window.db.series())  # Browsing never inserts an anime.
        job = self.fixture.queue(1)[0]
        self.assertFalse(self.window.download_metadata_pending)
        self.window._index_download_owner(job, self.fixture.import_path())
        self.assertEqual(self.window.db.series()[0]['poster_path'], str(self.fixture.poster))

    def test_old_results_cannot_update_new_search_or_deleted_page(self):
        self.results()
        key = next(iter(self.window.catalog_artwork_pending))
        self.window.catalog_token += 1
        self.results(('Other Show',))
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.window._catalog_artwork_ready(key, 'Example Show', self.fixture.data)
        self.assertEqual(self.row().findChild(QLabel, 'catalogReleaseYear').text(), 'Loading…')
        self.window.show_home()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.window._catalog_artwork_ready(key, 'Example Show', self.fixture.data)
        self.window.show_downloads(); self.results()
        self.assertEqual(self.row().findChild(QLabel, 'catalogReleaseYear').text(), '2023')

    def test_metadata_failure_keeps_search_and_buttons_usable(self):
        self.results()
        self.fixture.patches[0].stop()
        try:
            self.window._auto_metadata()
            worker = self.fixture.mocks[-2].call_args.args[0]
            worker.signals.failed.emit('No confident match')
            self.assertFalse(self.window.metadata_lookup_in_progress)
            self.assertEqual(self.row().findChild(QLabel, 'catalogReleaseYear').text(), 'Year unavailable')
            self.assertTrue(all(b.isEnabled() for b in self.row().findChildren(QPushButton)))
        finally:
            self.fixture.mocks[0] = self.fixture.patches[0].start()

    def test_download_metadata_has_priority_and_does_not_duplicate_search_lookup(self):
        self.results()
        job = self.fixture.queue(1)[0]
        self.fixture.patches[0].stop()
        try:
            self.window._auto_metadata()
            worker = self.fixture.mocks[-2].call_args.args[0]
            worker.signals.done.emit(self.fixture.data)
            self.assertFalse(self.window.catalog_artwork_pending)
            self.assertEqual(self.row().findChild(QLabel, 'catalogReleaseYear').text(), '2023')
        finally:
            self.fixture.mocks[0] = self.fixture.patches[0].start()

    def test_navigating_away_discards_unstarted_search_lookups(self):
        self.results(('Example Show', 'Other Show'))
        self.window.show_home()
        self.fixture.patches[0].stop()
        try:
            before = self.fixture.mocks[-2].call_count
            self.window._auto_metadata()
            self.assertFalse(self.window.catalog_artwork_pending)
            self.assertEqual(self.fixture.mocks[-2].call_count, before)
        finally:
            self.fixture.mocks[0] = self.fixture.patches[0].start()

    def test_unknown_year_and_direct_media_have_honest_placeholders(self):
        self.results()
        key = next(iter(self.window.catalog_artwork_pending))
        self.window._catalog_artwork_ready(key, 'Example Show', dict(self.fixture.data, year=None, poster_path=''))
        self.assertIn('unavailable', self.row().findChild(QLabel, 'catalogThumbnail').text())
        self.assertEqual(self.row().findChild(QLabel, 'catalogReleaseYear').text(), 'Year unavailable')
        self.window._catalog_results_ready([CatalogResult('video.mp4', 'https://catalog.example/video.mp4', True)])
        self.assertFalse(self.window.catalog_artwork_pending)
        self.assertEqual(self.row().findChild(QLabel, 'catalogReleaseYear').text(), 'Year unavailable')


if __name__ == '__main__':
    unittest.main()
