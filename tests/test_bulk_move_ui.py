import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication,QCheckBox,QComboBox,QDialog,QDialogButtonBox,QLineEdit,QPushButton,QSpinBox
from anime_watcher.qt_ui import AnimeWatcherWindow

class BulkMoveUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'APPDATA':self.temp.name});self.env.start()
        self.metadata=patch.object(AnimeWatcherWindow,'_auto_metadata');self.metadata.start()
        self.schedule=patch.object(AnimeWatcherWindow,'_refresh_release_schedule');self.schedule.start()
        self.window=AnimeWatcherWindow();self.root=Path(self.temp.name)/'library';self.window.library_root=self.root
        for title,season,ep in [('Horimiya',1,1),('Horimiya Piece',1,1),('Horimiya Piece',1,2),('Horimiya Piece',2,1)]:
            path=self.root/title/f'Season {season:02d}'/f'{title} - S{season:02d}E{ep:02d} [Sub].mp4';path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'video')
        self.window.db.scan_library(self.root)
        self.rows=[dict(r) for r in self.window.db.all_episodes() if r['series_title']=='Horimiya Piece'];self.ids=[r['id'] for r in self.rows]
        self.target=next(r for r in self.window.db.series() if r['title']=='Horimiya')
    def tearDown(self):
        self.window.close();self.window.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);self.app.processEvents()
        self.schedule.stop();self.metadata.stop();self.env.stop();self.temp.cleanup()
    def choose(self,dialog):
        target=dialog.findChild(QComboBox,'bulkMoveTarget');target.setCurrentIndex(target.findData('Horimiya'))
        dialog.findChild(QSpinBox,'bulkMoveSeason').setValue(2)
    def test_series_dialog_filters_source_season_and_keeps_numbers_without_full_scan(self):
        def choose(dialog):
            self.choose(dialog);selector=dialog.findChild(QComboBox,'bulkSourceSeason');selector.setCurrentIndex(selector.findData(1))
            self.assertFalse(dialog.findChild(QCheckBox,'bulkRenumber').isChecked())
            self.assertTrue(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).isEnabled())
            return QDialog.DialogCode.Accepted
        with patch.object(QDialog,'exec',choose),patch.object(self.window.db,'scan_library') as scan,patch('anime_watcher.qt_ui.QMessageBox.critical') as error:
            self.window._bulk_move_episodes(self.ids)
        error.assert_not_called();scan.assert_not_called()
        for row in self.rows:
            moved=self.window.db.episode(row['id'])
            self.assertEqual(moved['series_id'],self.target['id'] if row['season']==1 else row['series_id'])
            self.assertEqual(moved['season'],2);self.assertEqual(moved['episode'],row['episode'])
    def test_collision_disables_save_and_cancel_changes_nothing(self):
        before=[dict(r) for r in self.window.db.all_episodes()]
        def choose(dialog):
            target=dialog.findChild(QComboBox,'bulkMoveTarget');target.setCurrentIndex(target.findData('Horimiya'))
            dialog.findChild(QSpinBox,'bulkMoveSeason').setValue(1)
            self.assertFalse(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).isEnabled())
            return QDialog.DialogCode.Rejected
        with patch.object(QDialog,'exec',choose):self.window._bulk_move_episodes(self.ids)
        self.assertEqual([dict(r) for r in self.window.db.all_episodes()],before)
    def test_file_manager_select_shown_uses_current_filter_and_carries_selected_files(self):
        self.window.show_file_manager();page=self.window.stack.currentWidget();search=page.findChild(QLineEdit)
        search.setText('Horimiya Piece');page.findChild(QPushButton,'selectShownFiles').click()
        button=page.findChild(QPushButton,'bulkMoveFiles');self.assertTrue(button.isEnabled());self.assertIn('(3)',button.text())
        search.setText('Horimiya - S01');self.app.processEvents()
        with patch.object(self.window,'_bulk_move_episodes') as move:button.click()
        self.assertEqual(set(move.call_args.args[0]),set(self.ids))
    def test_series_button_passes_all_versions_to_bulk_dialog(self):
        series_id=self.rows[0]['series_id'];self.window.show_series(series_id)
        with patch.object(self.window,'_bulk_move_episodes') as move:self.window.stack.currentWidget().findChild(QPushButton,'bulkMoveSeries').click()
        self.assertEqual(set(move.call_args.args[0]),set(self.ids))
    def test_bulk_renumber_updates_episode_groups_and_stops_selected_playback(self):
        def choose(dialog):
            self.choose(dialog);dialog.findChild(QSpinBox,'bulkMoveSeason').setValue(3)
            dialog.findChild(QCheckBox,'bulkRenumber').setChecked(True);dialog.findChild(QSpinBox,'bulkFirstEpisode').setValue(5)
            return QDialog.DialogCode.Accepted
        self.window.current_episode_id=self.ids[0]
        with patch.object(QDialog,'exec',choose),patch.object(self.window,'_save_progress') as save,patch('anime_watcher.qt_ui.QMessageBox.critical') as error:
            self.window._bulk_move_episodes(self.ids)
        error.assert_not_called();save.assert_any_call(stop=True)
        self.assertEqual([(self.window.db.episode(eid)['season'],self.window.db.episode(eid)['episode']) for eid in self.ids],[(3,5),(3,6),(3,7)])
        self.window.current_episode_id=None

if __name__=='__main__':unittest.main()
