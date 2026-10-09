import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QLabel, QPushButton, QSpinBox
from tests import test_download_artwork_ui as fixture_module


class EpisodeVersionUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture_module.DownloadArtworkTests.setUpClass()

    def setUp(self):
        self.fixture = fixture_module.DownloadArtworkTests(); self.fixture.setUp()
        self.window = self.fixture.window
        self.series_id = self.fixture.seed()
        path = self.window.library_root / 'Example Show' / 'Season 01' / 'Example Show - S01E00 [Sub].mp4'
        path.write_bytes(b'sub')
        self.sub, _ = self.window.db.index_download(path, self.window.library_root)
        self.dub = next(row for row in self.window.db.episodes(self.series_id) if row['language'] == 'Dub')

    def tearDown(self):
        self.fixture.tearDown()

    def select_group(self, dialog):
        combo = dialog.findChild(QComboBox, 'versionGroupEpisode')
        index = next(i for i in range(1, combo.count()) if tuple(combo.itemData(i)) == (1, 0))
        combo.setCurrentIndex(index)

    def test_group_picker_merges_sub_dub_and_stops_playback_without_rescan(self):
        def choose(dialog):
            self.select_group(dialog)
            self.assertFalse(dialog.findChild(QSpinBox, 'versionEpisode').isEnabled())
            self.assertIn('Dub / Sub', dialog.findChild(QLabel, 'versionPreview').text())
            return QDialog.DialogCode.Accepted
        self.window.current_episode_id = self.dub['id']
        with patch.object(QDialog, 'exec', choose), patch.object(self.window, '_save_progress') as stop, patch.object(self.window.db, 'scan_library') as scan:
            self.window._edit_episode_version(self.dub['id'])
        stop.assert_any_call(stop=True); scan.assert_not_called()
        self.window.current_episode_id = None
        self.assertEqual(self.window.db.series()[0]['episode_count'], 1)
        self.assertEqual(len(self.window.db.episode_variants(self.sub['id'])), 2)

    def test_collision_disables_save_and_cancel_keeps_files(self):
        original = dict(self.window.db.episode(self.dub['id']))
        def choose(dialog):
            self.select_group(dialog)
            dialog.findChild(QComboBox, 'versionLanguage').setCurrentText('Sub')
            self.assertFalse(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).isEnabled())
            self.assertIn('No files will be replaced', dialog.findChild(QLabel, 'versionPreview').text())
            return QDialog.DialogCode.Rejected
        with patch.object(QDialog, 'exec', choose):
            self.window._edit_episode_version(self.dub['id'])
        self.assertEqual(dict(self.window.db.episode(self.dub['id'])), original)
        self.assertTrue(Path(original['path']).is_file())

    def test_manage_versions_exposes_editor_and_filename(self):
        def inspect(dialog):
            self.assertTrue(any(Path(self.dub['path']).name in label.text() for label in dialog.findChildren(QLabel)))
            dialog.findChild(QPushButton, f"editEpisodeVersion_{self.dub['id']}").click()
            return QDialog.DialogCode.Accepted
        with patch.object(QDialog, 'exec', inspect), patch.object(self.window, '_edit_episode_version') as edit:
            self.window._manage_versions([self.dub['id']])
        edit.assert_called_once_with(self.dub['id'])


if __name__ == '__main__':
    unittest.main()
