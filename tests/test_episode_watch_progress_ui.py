import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton
from tests import test_download_artwork_ui as fixture_module


class EpisodeWatchProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture_module.DownloadArtworkTests.setUpClass()

    def setUp(self):
        self.fixture = fixture_module.DownloadArtworkTests(); self.fixture.setUp()
        self.window = self.fixture.window
        self.series_id = self.fixture.seed()
        self.episode = self.window.db.episodes(self.series_id)[0]

    def tearDown(self):
        self.fixture.tearDown()

    def show(self):
        self.window.show_series(self.series_id)
        page = self.window.stack.currentWidget()
        return page.findChild(QProgressBar, 'episodeWatchProgress'), page.findChild(QLabel, 'episodeWatchStatus')

    def test_unwatched_episode_has_empty_bar_and_still_plays(self):
        bar, label = self.show()
        self.assertEqual((bar.minimum(), bar.maximum(), bar.value()), (0, 1000, 0))
        self.assertEqual(label.text(), 'Not watched')
        button = next(b for b in self.window.stack.currentWidget().findChildren(QPushButton) if 'Episode 01' in b.text())
        with patch.object(self.window, 'play_episode') as play:
            button.click()
        play.assert_called_once_with(self.episode['id'])

    def test_partial_progress_has_percentage_time_and_fractional_bar(self):
        self.window.db.save_progress(self.episode['id'], 630000, 1500000)
        bar, label = self.show()
        self.assertEqual(bar.value(), 420)
        self.assertEqual(label.text(), '42% watched · 10:30 / 25:00')
        self.assertEqual(bar.property('watchState'), 'In progress')

    def test_completed_bar_is_green_and_keeps_actual_watched_fraction(self):
        self.window.db.save_progress(self.episode['id'], 1425000, 1500000)
        bar, label = self.show()
        self.assertEqual(bar.value(), 950)
        self.assertEqual(bar.property('watchState'), 'Completed')
        self.assertIn('95% watched', label.text()); self.assertIn('Complete', label.text())

    def test_unknown_duration_is_empty_instead_of_busy_and_shows_saved_time(self):
        self.window.db.save_progress(self.episode['id'], 630000, 0)
        bar, label = self.show()
        self.assertEqual((bar.minimum(), bar.maximum(), bar.value()), (0, 1000, 0))
        self.assertEqual(label.text(), '10:30 watched · duration unavailable')

    def test_multiple_versions_use_furthest_fraction_without_combining_times(self):
        sub_path = Path(self.episode['path']).with_name('Example Show - S01E01 [Sub].mp4')
        sub_path.write_bytes(b'sub'); sub, _ = self.window.db.index_download(sub_path, self.window.library_root)
        self.window.db.save_progress(self.episode['id'], 600000, 1000000)
        self.window.db.save_progress(sub['id'], 750000, 1500000)
        bar, label = self.show()
        self.assertEqual(len(self.window.stack.currentWidget().findChildren(QProgressBar, 'episodeWatchProgress')), 1)
        self.assertEqual(bar.value(), 600)
        self.assertIn('Dub version', bar.toolTip())
        self.assertEqual(label.text(), '60% watched · 10:00 / 16:40')
        self.assertEqual(self.window.db.episode(sub['id'])['progress_ms'], 750000)

    def test_return_from_playback_saves_final_position_before_rendering(self):
        self.window.current_episode_id = self.episode['id']
        self.window.known_duration_ms = 1500000
        with patch.object(self.window.player, 'time', return_value=750000), patch.object(self.window.player, 'stop') as stop:
            bar, label = self.show()
        self.assertEqual(bar.value(), 500); self.assertIn('12:30 / 25:00', label.text())
        self.assertIsNone(self.window.current_episode_id); stop.assert_called_once()

    def test_progress_is_clamped_and_negative_values_do_not_fill_bar(self):
        self.window.db.save_progress(self.episode['id'], 1600000, 1500000)
        bar, _ = self.show(); self.assertEqual(bar.value(), 1000)
        self.window.db.save_progress(self.episode['id'], -1, 1500000)
        bar, label = self.show(); self.assertEqual(bar.value(), 0); self.assertEqual(label.text(), 'Not watched')

    def test_youtube_series_and_seasons_show_each_episodes_own_progress(self):
        self.window.db.set_series_library_type(self.series_id, 'YouTube')
        path = self.window.library_root / 'Example Show' / 'Season 02' / 'Example Show - S02E01 [Dub].mp4'
        path.parent.mkdir(); path.write_bytes(b'fixture'); second, _ = self.window.db.index_download(path, self.window.library_root)
        self.window.db.save_progress(self.episode['id'], 600000, 1500000)
        self.window.db.save_progress(second['id'], 1200000, 1500000)
        self.show()
        bars = self.window.stack.currentWidget().findChildren(QProgressBar, 'episodeWatchProgress')
        self.assertEqual({(b.property('season'), b.property('episode')): b.value() for b in bars}, {(1, 1): 400, (2, 1): 800})


if __name__ == '__main__':
    unittest.main()
