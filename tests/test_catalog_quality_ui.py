import time
import unittest
from unittest.mock import Mock, patch
from PySide6.QtWidgets import QLabel, QTabWidget, QComboBox, QVBoxLayout, QWidget, QPushButton
from anime_watcher.downloader import CatalogResult, EpisodeResult
from tests import test_download_artwork_ui as fixture_module


class CatalogQualityUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture_module.DownloadArtworkTests.setUpClass()

    def setUp(self):
        self.fixture = fixture_module.DownloadArtworkTests(); self.fixture.setUp()
        self.window = self.fixture.window
        self.patch = patch('anime_watcher.wco_browser.WcoQualityProbe'); self.factory = self.patch.start()
        self.factory.side_effect = lambda *args: Mock()
        self.host = QWidget(); self.box = QVBoxLayout(self.host); self.window.catalog_results.addWidget(self.host)
        self.episodes = [EpisodeResult(f'Episode {n}', f'https://www.wco.tv/{lang}/{s}/{n}', True, s, str(n), lang)
                         for lang, s, n in [('Sub', 1, 1), ('Sub', 1, 2), ('Sub', 2, 1), ('Dub', 1, 1)]]

    def tearDown(self):
        self.fixture.tearDown(); self.patch.stop()

    def render(self):
        self.window._catalog_episodes_ready(CatalogResult('Show', 'https://www.wco.tv/anime/show'), self.box, self.episodes)

    def ready(self, label='Best: FHD (1080p)', success=True):
        probe, key, widget = self.window.catalog_quality_probe
        self.window._catalog_quality_ready(probe, key, widget, {'label': label, 'detail': 'player offered quality'}, success)

    def labels(self):
        return self.host.findChildren(QLabel, 'episodeBestQuality')

    def label_for(self, episode):
        return next(label for label in self.labels() if label.property('episodeUrl') == episode.url)

    def test_one_background_probe_shows_per_episode_results_and_caches_descriptions(self):
        self.render(); self.assertEqual(self.factory.call_count, 1)
        self.window._catalog_quality_tick(); self.assertEqual(self.factory.call_count, 1)
        self.ready(); self.window._catalog_quality_tick()
        self.assertEqual(self.label_for(self.episodes[0]).text(), 'Best: FHD (1080p)')
        self.assertEqual(self.factory.call_count, 2)
        self.assertFalse(self.window.download_queue.jobs)
        self.assertTrue(all(b.isEnabled() for b in self.host.findChildren(QPushButton) if b.text() == 'Download best available'))
        self.assertNotIn('src', str(self.window.catalog_quality_cache))

    def test_sub_dub_and_season_changes_cancel_old_probe_and_check_current_rows(self):
        self.render(); original = self.window.catalog_quality_probe[0]
        self.host.findChild(QTabWidget, 'wcoEpisodeTabs').setCurrentIndex(1)
        original.stop.assert_called_once()
        self.assertEqual(self.factory.call_args.args[1].language, 'Dub')
        self.host.findChild(QTabWidget, 'wcoEpisodeTabs').setCurrentIndex(0)
        self.host.findChild(QComboBox, 'wcoSeasonFilter').setCurrentIndex(2)
        self.assertEqual(self.factory.call_args.args[1].season, 2)

    def test_active_downloads_pause_checks_and_completion_resumes(self):
        self.render(); probe = self.window.catalog_quality_probe[0]
        self.fixture.queue(1)
        probe.stop.assert_called_once()
        self.window._catalog_quality_tick(); self.assertIsNone(self.window.catalog_quality_probe)
        self.assertIn('Waiting', self.label_for(self.episodes[0]).text())
        for job in self.window.download_queue.jobs.values():
            job.status = 'Completed'
        self.window._catalog_quality_tick(); self.assertIsNotNone(self.window.catalog_quality_probe)

    def test_navigation_and_old_callback_cannot_change_new_page(self):
        self.render(); probe, key, label = self.window.catalog_quality_probe
        self.window.show_home()
        self.window._catalog_quality_ready(probe, key, label, {'label':'Best: FHD (1080p)', 'detail':'old'})
        self.assertFalse(self.window.catalog_quality_groups); self.assertFalse(self.window.catalog_quality_cache)

    def test_downloads_tab_pauses_and_find_videos_tab_resumes(self):
        self.render(); probe = self.window.catalog_quality_probe[0]
        self.window.download_tabs.setCurrentIndex(1)
        probe.stop.assert_called_once(); self.assertIsNone(self.window.catalog_quality_probe)
        self.window.download_tabs.setCurrentIndex(0)
        self.assertIsNotNone(self.window.catalog_quality_probe)

    def test_failure_stays_honest_and_does_not_block_download_button(self):
        self.render(); self.ready('Quality unavailable', success=False)
        self.window._catalog_quality_tick()
        self.assertEqual(self.label_for(self.episodes[0]).text(), 'Quality unavailable')
        self.assertTrue(next(b for b in self.host.findChildren(QPushButton) if b.text() == 'Download best available').isEnabled())
        deadline, result = next(iter(self.window.catalog_quality_cache.values()))
        self.assertLess(deadline - time.monotonic(), 121)


if __name__ == '__main__':
    unittest.main()
