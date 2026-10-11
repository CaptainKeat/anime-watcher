import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication,QEvent,Qt
from PySide6.QtWidgets import QLabel,QCheckBox,QPushButton,QApplication
from anime_watcher.controller import PadActions,PadState,ControllerNavigation
from anime_watcher.experience_ui import phone_diagnostics
from anime_watcher.library_extras import file_inventory,save_skip_marker
from anime_watcher.media_chapters import MediaChapter
import test_download_artwork_ui as fixtures


class ControllerActionsTests(unittest.TestCase):
    def test_buttons_are_edge_triggered_and_directions_repeat_with_deadzone(self):
        pad=PadActions(); self.assertEqual(pad.actions(PadState(0x1000),0),['accept']); self.assertEqual(pad.actions(PadState(0x1000),1),[])
        self.assertEqual(pad.actions(PadState(x=8000),2),[]); self.assertEqual(pad.actions(PadState(x=20000),3),['right'])
        self.assertEqual(pad.actions(PadState(x=20000),3.2),[]); self.assertEqual(pad.actions(PadState(x=20000),3.5),['right'])
    def test_focus_return_requires_neutral_state_before_any_action(self):
        pad=PadActions(); pad.reset(); self.assertEqual(pad.actions(PadState(0x1000),0),[])
        self.assertEqual(pad.actions(PadState(),1),[]); self.assertEqual(pad.actions(PadState(0x1000),2),['accept'])


class ExperienceUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): fixtures.DownloadArtworkTests.setUpClass()
    def setUp(self):
        self.fixture=fixtures.DownloadArtworkTests(); self.fixture.setUp(); self.window=self.fixture.window; self.sid=self.fixture.seed(); self.window.show_library()
        self.window._experience_timer.stop(); self.window.controller.timer.stop()
    def tearDown(self): self.window._portable_worker=None; self.window.profile_manager.attach_portable(None); self.fixture.tearDown()
    def complete_last(self):
        worker=self.fixture.mocks[-2].call_args.args[0]
        result=worker.function(*worker.args); worker.signals.done.emit(result); return result

    def test_library_filters_and_preferences_are_profile_owned(self):
        self.window.show_series(self.sid); page=self.window.stack.currentWidget(); page.findChild(QCheckBox,'seriesFavorite').click()
        self.window.show_library(); self.window.library_filters['favorite'].click()
        self.window.library_filters['year'].setCurrentText('2023')
        self.assertEqual(self.window.db.setting('library_filters')['year'],'2023')
        self.assertTrue(self.window.db.setting('library_filters')['favorite']); self.assertTrue(self.window.db.get_series(self.sid)['favorite'])
        self.window.show_settings(); self.assertIsNotNone(self.window.stack.currentWidget().findChild(QPushButton,'reviewLibraryStorage'))

    def test_folder_changes_refresh_only_after_stable_snapshot_and_keep_progress(self):
        episode=self.window.db.episodes(self.sid)[0]; self.window.db.save_progress(episode['id'],20000,1000000)
        self.window._experience_tick(); self.complete_last()
        new=self.window.library_root/'Example Show'/'Season 01'/'Example Show - S01E02 [Dub].mp4'; new.write_bytes(b'new')
        with patch.object(self.window,'_refresh_library') as refresh:
            self.window._experience_tick(); self.complete_last(); refresh.assert_not_called()
            self.window._experience_tick(); self.complete_last(); refresh.assert_called_once()
        self.assertEqual(self.window.db.episode(episode['id'])['progress_ms'],20000)

    def test_disconnect_keeps_index_and_reconnection_refreshes(self):
        self.window._experience_tick()
        worker=self.fixture.mocks[-2].call_args.args[0]; worker.signals.failed.emit('Drive disconnected')
        self.assertEqual(len(self.window.db.episodes(self.sid)),1); self.assertIn('disconnected',self.window._library_refresh_label.text())
        with patch.object(self.window,'_refresh_library') as refresh:
            self.window._experience_tick(); self.complete_last(); refresh.assert_called_once()

    def test_monitor_does_not_cross_profile_and_waits_for_imports(self):
        with patch.object(self.window,'_experience_work') as work:
            self.window.import_job='busy'; self.window._experience_tick(); work.assert_not_called(); self.window.import_job=None
        self.window._experience_tick(); worker=self.fixture.mocks[-2].call_args.args[0]
        previous=self.window.db; from anime_watcher.database import LibraryDatabase
        other=LibraryDatabase(Path(self.fixture.temp.name)/'other.db'); self.window.db=other
        try:
            with patch.object(self.window,'_refresh_library') as refresh:
                worker.signals.done.emit({}); refresh.assert_not_called()
        finally: self.window.db=previous; other.close()

    def test_portable_enable_produces_verified_snapshot_and_offline_sync_is_safe(self):
        self.window.show_settings(); self.window._enable_portable(); self.complete_last()
        record=self.window.profile_manager.portable(); self.assertTrue(record['sha256']); self.assertIn('synced',self.window.portable_status.text())
        with patch('anime_watcher.experience_ui.find_portable',return_value=None):
            self.assertFalse(self.window._sync_portable(force=True)); self.assertIn('local working copy',self.window.portable_status.text())

    def test_handheld_controls_and_controller_accept_back_and_tabs(self):
        self.window.db.set_setting('controller_large',True); self.window._apply_controller_mode(); self.assertEqual(self.window.minimumWidth(),960)
        controller=self.window.controller
        with patch('anime_watcher.controller.QApplication.focusWidget',return_value=self.window.nav_buttons[7]): controller.dispatch('accept')
        self.assertIsNotNone(self.window.settings_tabs); controller.dispatch('next_tab'); self.assertEqual(self.window.settings_tabs.currentIndex(),1)
        with patch.object(self.window,'show_home') as home: controller.dispatch('back'); home.assert_called_once()
        controller.mapper.armed=True
        with patch.object(controller.reader,'read',return_value=PadState(0x1000)),patch('anime_watcher.controller.QApplication.activeWindow',return_value=None),patch.object(controller,'dispatch') as dispatch:
            controller.tick(); dispatch.assert_not_called(); self.assertFalse(controller.mapper.armed)

    def test_manual_ranges_override_embedded_chapters_without_guessing_other_versions(self):
        row=self.window.db.episodes(self.sid)[0]; self.window.current_episode_id=row['id']; self.window.known_duration_ms=1500000
        # Use a lightweight timeline fixture; video playback is not needed.
        from unittest.mock import Mock
        self.window.timeline=Mock(); self.window._update_skip_intro=Mock()
        save_skip_marker(self.window.db,dict(row),'intro',20000,110000)
        self.window._intro_ready(self.window.intro_probe_token,[MediaChapter('OP','intro',50000,140000),MediaChapter('Ending','outro',1400000,1490000)])
        self.assertEqual([(item.kind,item.start_ms) for item in self.window.media_chapters],[('intro',20000),('outro',1400000)])
        self.window.current_episode_id=None

    def test_phone_test_requires_sharing_and_reports_only_this_server(self):
        self.window.show_settings(); page=self.window.stack.currentWidget(); page.findChild(QPushButton,'testPhoneConnection').click()
        self.assertEqual(self.window.phone_test_status.text(),'Enable Phone access first.')
        with patch('anime_watcher.experience_ui.http.client.HTTPConnection') as http:
            http.return_value.getresponse.return_value.status=200
            result=phone_diagnostics('10.20.30.40',12345)
            self.assertIn('This checks the PC',result); self.assertEqual(http.call_args_list[0].args,('127.0.0.1',12345)); self.assertEqual(http.call_args_list[1].args,('10.20.30.40',12345))

    def test_events_after_player_page_deletion_do_not_use_destroyed_video(self):
        self.window._set_page(self.window._build_player_page(),player=True)
        self.window.show_library()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.assertFalse(self.window.eventFilter(self.window,QEvent(QEvent.Type.User)))


if __name__=='__main__': unittest.main()
