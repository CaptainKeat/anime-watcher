import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Signal
from PySide6.QtWidgets import QApplication, QDialog, QLabel
from anime_watcher.downloader import EpisodeResult
from anime_watcher.qt_ui import AnimeWatcherWindow


class FakePlayer(QDialog):
    completed=Signal(object)
    failed=Signal(str)
    cancelled=Signal()
    transfer_started=Signal()
    verification_started=Signal()
    retry_requested=Signal(str,int)
    def __init__(self,session,title,episode,download_dir,root,parent,**options):
        super().__init__(parent)
        self.status=QLabel('Selecting FHD…',self)
        self.download=None;self.worker=None;self.terminal=False;self.auto_download=True
        self.defer_download=options.get('defer_download',False);self.begin_download=Mock()
        self.attempt=options.get('attempt',1)
    def cancel_download(self):
        self.terminal=True;self.cancelled.emit()


class DownloadQueueUiTests(unittest.TestCase):
    def test_finished_colors_and_failed_count_reset_in_place_on_retry(self):
        self.window.download_permission.setChecked(True)
        with patch('anime_watcher.wco_browser.WcoDownloadDialog',FakePlayer),patch.object(self.window,'_wco_session',return_value=object()):
            jobs=[self.window._download_wco_episode('Show',EpisodeResult(f'Episode {n}',f'https://www.wco.tv/ep{n}',True,1,str(n),'Dub')) for n in (1,2)]
            for item,state in zip(jobs,('Completed','Failed')):
                dialog=self.window.wco_downloads[item.id]['dialog'];dialog.terminal=True
                self.window.download_queue.finish(item.id,state,state);self.window._dispose_wco_job(item)
                progress=self.window._download_rows[item.id][2]
                self.assertEqual(progress.property('downloadStatus'),state);self.assertEqual(progress.parentWidget().property('downloadStatus'),state)
            self.assertIn('1 failed',self.window.download_queue_summary.text())
            bar=self.window._download_rows[jobs[1].id][2];self.window._retry_download(jobs[1])
            self.assertIs(self.window._download_rows[jobs[1].id][2],bar);self.assertEqual(bar.property('downloadStatus'),'Connecting')
            self.assertIn('0 failed',self.window.download_queue_summary.text())

    def test_automatic_retry_waits_for_import_worker_cleanup_and_reuses_job(self):
        class Worker(QObject):
            finished=Signal()
            running=True
            def isRunning(self):return self.running
        self.window.download_permission.setChecked(True);self.window.download_parallel.setValue(1)
        with patch('anime_watcher.wco_browser.WcoDownloadDialog',FakePlayer),patch.object(self.window,'_wco_session',return_value=object()):
            first=self.window._download_wco_episode('Show',EpisodeResult('Episode 1','https://www.wco.tv/ep1',True,1,'1','Dub'))
            second=self.window._download_wco_episode('Show',EpisodeResult('Episode 2','https://www.wco.tv/ep2',True,1,'2','Dub'))
            dialog=self.window.wco_downloads[first.id]['dialog'];worker=Worker();dialog.worker=worker
            self.window.download_queue.update(first.id,status='Verifying');dialog.terminal=True;dialog.retry_requested.emit('480p instead of FHD',2)
            self.assertEqual(first.status,'Verifying');self.assertIs(self.window.wco_downloads[first.id]['dialog'],dialog)
            worker.running=False;worker.finished.emit()
            self.assertEqual(first.status,'Queued');self.assertNotIn(first.id,self.window.wco_downloads)
            other=self.window.wco_downloads[second.id]['dialog'];other.terminal=True;other.failed.emit('Other failure')
            self.assertEqual(len(self.window.download_queue.jobs),2);self.assertEqual(first.status,'Connecting')
            self.assertEqual(self.window.wco_downloads[first.id]['dialog'].attempt,2)

    def test_finished_wco_history_restores_without_starting_and_keeps_retry(self):
        import json
        row=dict(id='old-job',title='Show · S01 · Episode 3 · Dub',source='WCO',profile='Default',page_url='https://www.wco.tv/ep3',status='Failed',detail='480p instead of 1080p',received=100,total=100)
        (self.window.data_root/'download-queue.json').write_text(json.dumps({'jobs':[row,dict(row,id='active',status='Downloading')]}))
        with patch.object(self.window,'_start_wco_job') as start:self.window._restore_download_history()
        self.assertEqual(len(self.window.download_queue.jobs),1);start.assert_not_called()
        job=self.window.download_queue.jobs['old-job'];self.assertIsNotNone(job.retry_action);self.assertEqual(job.root,self.window.library_root)
        self.window.download_permission.setChecked(True)
        with patch.object(self.window,'_start_wco_job') as start:self.window._retry_download(job)
        start.assert_called_once();self.assertEqual(job.status,'Connecting');self.assertEqual(len(self.window.download_queue.jobs),1)

    def test_long_transfer_prepares_next_only_near_completion(self):
        self.window.download_permission.setChecked(True);self.window.download_parallel.setValue(1)
        with patch('anime_watcher.wco_browser.WcoDownloadDialog',FakePlayer),patch.object(self.window,'_wco_session',return_value=object()):
            jobs=[self.window._download_wco_episode('Show',EpisodeResult(f'Episode {n}',f'https://www.wco.tv/ep{n}',True,1,str(n),'Dub')) for n in (1,2)]
            with patch('anime_watcher.download_queue.time.monotonic',return_value=10):
                self.window.download_queue.update(jobs[0].id,status='Downloading',received=0,total=200*1048576)
            with patch('anime_watcher.download_queue.time.monotonic',return_value=12):
                self.window.download_queue.update(jobs[0].id,received=2*1048576)
                self.window._prepare_wco_next();self.assertNotIn(jobs[1].id,self.window.wco_downloads)
            with patch('anime_watcher.download_queue.time.monotonic',return_value=14):
                self.window.download_queue.update(jobs[0].id,received=100*1048576)
                self.window._prepare_wco_next();self.assertIn(jobs[1].id,self.window.wco_downloads)

    def test_only_next_player_is_prepared_and_import_releases_transfer_slot(self):
        self.window.download_permission.setChecked(True);self.window.download_parallel.setValue(1)
        with patch('anime_watcher.wco_browser.WcoDownloadDialog',FakePlayer),patch.object(self.window,'_wco_session',return_value=object()):
            jobs=[self.window._download_wco_episode('Show',EpisodeResult(f'Episode {n}',f'https://www.wco.tv/ep{n}',True,1,str(n),'Dub')) for n in range(1,4)]
            first=self.window.wco_downloads[jobs[0].id]['dialog'];first.transfer_started.emit()
            prepared=self.window.wco_downloads[jobs[1].id]['dialog']
            self.assertTrue(prepared.defer_download);self.assertEqual(jobs[1].status,'Queued')
            self.assertNotIn(jobs[2].id,self.window.wco_downloads)
            first.transfer_started.emit();self.assertEqual(len(self.window.wco_downloads),2)
            first.verification_started.emit();prepared.begin_download.assert_called_once()
            self.assertEqual((jobs[0].status,jobs[1].status),('Verifying','Connecting'))
            self.assertEqual(self.window.download_queue.transfer_count,1)
            self.assertEqual(self.window.download_queue.verifying_count,1)
            prepared.transfer_started.emit();self.assertIn(jobs[2].id,self.window.wco_downloads)
            self.window.download_queue.cancel(jobs[2].id)
            self.assertEqual(jobs[2].status,'Cancelled');self.assertNotIn(jobs[2].id,self.window.wco_downloads)
            first.terminal=True;first.failed.emit('Probe failed')
            self.assertEqual(jobs[0].status,'Failed');self.assertEqual(self.window.download_queue.transfer_count,1)

    def test_wco_completion_indexes_one_file_and_preserves_notifications(self):
        self.window.download_permission.setChecked(True)
        self.window.db.set_setting('release_notifications_initialized',True)
        episode=EpisodeResult('Episode 1','https://www.wco.tv/ep1',True,1,'1','Dub')
        with patch.object(self.window,'_start_wco_job'):
            job=self.window._download_wco_episode('Show',episode)
        saved=self.window.library_root/'Show'/'Season 01'/'Show - S01E01 [Dub] [1080p].mp4'
        saved.parent.mkdir(parents=True);saved.write_bytes(b'verified earlier by importer')
        with patch.object(self.window,'_scan',side_effect=AssertionError('Full scan')):
            self.window._wco_job_finished(job,SimpleNamespace(status='moved',destination=saved),episode,'Show',None,None)
        self.assertEqual(job.status,'Completed');self.assertEqual(len(self.window.db.all_episodes()),1)
        self.assertEqual(len(self.window.db.notifications()),1)
        self.assertIn('Dub episode added',self.window.db.notifications()[0]['title'])

    def test_download_limit_persists_and_speed_is_rendered(self):
        self.window.download_parallel.setValue(1)
        self.assertEqual(self.window.download_queue.limit,1)
        self.window.show_home();self.window.show_downloads()
        self.assertEqual(self.window.download_parallel.value(),1)
        self.window.download_permission.setChecked(True);self.direct(1)
        job=next(iter(self.window.download_queue.jobs.values()))
        with patch('anime_watcher.download_queue.time.monotonic',return_value=10):
            self.window.download_queue.update(job.id,status='Downloading',received=0,total=10*1048576)
        with patch('anime_watcher.download_queue.time.monotonic',return_value=12):
            self.window.download_queue.update(job.id,received=2*1048576)
            text=self.window._download_rows[job.id][1].text()
            self.assertIn('1.00 MB/s',text);self.assertIn('0:08 remaining',text)

    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'APPDATA':self.temp.name});self.env.start()
        self.metadata=patch.object(AnimeWatcherWindow,'_auto_metadata');self.metadata.start()
        self.schedule=patch.object(AnimeWatcherWindow,'_refresh_release_schedule');self.schedule.start()
        self.window=AnimeWatcherWindow();self.window.library_root=Path(self.temp.name)/'library'
        self.window.db.set_setting('library_root',str(self.window.library_root));self.window.show_downloads()
    def tearDown(self):
        self.window.close();self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);self.app.processEvents()
        self.schedule.stop();self.metadata.stop();self.env.stop();self.temp.cleanup()
    def direct(self,number=1):
        self.window.download_url.setText(f'https://files.example/Show.S01E{number:02d}.mp4')
        with patch.object(self.window,'_start_worker') as start:self.window._start_download()
        return start.call_args.args[0] if start.call_args else None

    def test_one_permission_checkbox_persists_navigation_and_is_profile_scoped(self):
        self.assertFalse(self.window._downloads_allowed())
        self.assertIs(self.window.youtube_rights,self.window.rights_check)
        self.window.download_permission.setChecked(True)
        self.window.show_home();self.window.show_downloads()
        self.assertTrue(self.window.download_permission.isChecked())
        guest=self.window.profile_manager.create('Guest')
        self.window.show_settings();self.window.profile_combo.setCurrentIndex(self.window.profile_combo.findData(guest.id));self.window._switch_profile()
        self.window.show_downloads();self.assertFalse(self.window.download_permission.isChecked())
        self.window.show_settings();self.window.profile_combo.setCurrentIndex(self.window.profile_combo.findData('default'));self.window._switch_profile()
        self.window.show_downloads();self.assertTrue(self.window.download_permission.isChecked())
        self.window.download_permission.setChecked(False)
        with patch('anime_watcher.qt_ui.QMessageBox.warning') as warning:self.assertIsNone(self.direct())
        warning.assert_called_once()

    def test_two_direct_downloads_progress_survives_navigation_and_count_finishes(self):
        self.window.download_permission.setChecked(True)
        first=self.direct(1);second=self.direct(2)
        self.assertEqual(self.window.download_queue.active_count,2)
        self.assertIn('(2)',self.window.nav_buttons[4].text())
        self.window.show_home();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        first.signals.progress.emit((5*1048576,10*1048576))
        self.window.show_downloads();self.window.download_tabs.setCurrentIndex(1)
        jobs=list(self.window.download_queue.jobs.values())
        title,status,progress,cancel,player=self.window._download_rows[jobs[0].id]
        self.assertEqual(progress.value(),500);self.assertIn('5.0 / 10.0 MB',status.text())
        second.signals.failed.emit('Network failed')
        self.assertEqual(self.window.download_queue.active_count,1)
        with patch.object(self.window,'_scan') as scan:first.signals.done.emit(SimpleNamespace(status='moved',destination=Path('saved.mp4')))
        scan.assert_called_once();self.assertEqual(self.window.download_queue.active_count,0)
        self.assertNotIn('(',self.window.nav_buttons[4].text())
        self.assertEqual(progress.value(),1000)

    def test_permission_survives_restart(self):
        self.window.download_permission.setChecked(True)
        self.window.close();self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.window=AnimeWatcherWindow();self.window.show_downloads()
        self.assertTrue(self.window.download_permission.isChecked())

    def test_completion_after_switch_indexes_the_original_profile(self):
        self.window.download_permission.setChecked(True)
        worker=self.direct()
        original=self.window.db.path
        guest=self.window.profile_manager.create('Other')
        self.window.show_settings();self.window.profile_combo.setCurrentIndex(self.window.profile_combo.findData(guest.id));self.window._switch_profile()
        with patch('anime_watcher.qt_ui.LibraryDatabase') as database,patch.object(self.window,'_scan') as scan:
            database.return_value.setting.return_value=str(Path(self.temp.name)/'library')
            worker.signals.done.emit(SimpleNamespace(status='moved',destination=Path('saved.mp4')))
        scan.assert_not_called();database.assert_called_once_with(original)
        database.return_value.scan_library.assert_called_once_with(Path(self.temp.name)/'library')
        database.return_value.close.assert_called_once()

    def test_wco_jobs_run_without_modal_dialog_and_can_be_cancelled(self):
        self.window.download_permission.setChecked(True)
        with patch('anime_watcher.wco_browser.WcoDownloadDialog',FakePlayer),patch.object(self.window,'_wco_session',return_value=object()):
            for number in (1,2):
                self.window._download_wco_episode('Show',EpisodeResult(f'Episode {number}',f'https://www.wco.tv/ep{number}',True,1,str(number),'Dub'))
        self.assertEqual(self.window.download_queue.active_count,2)
        self.assertTrue(all(not entry['dialog'].isVisible() for entry in self.window.wco_downloads.values()))
        keys=list(self.window.wco_downloads)
        self.window.show_home();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        dialog=self.window.wco_downloads[keys[0]]['dialog']
        dialog.download=Mock();dialog.download.receivedBytes.return_value=50;dialog.download.totalBytes.return_value=100
        dialog.status.setText('Downloading 1080p…');self.window._poll_wco_downloads()
        self.assertEqual(self.window.download_queue.jobs[keys[0]].received,50)
        self.window.download_queue.cancel(keys[0])
        self.assertEqual(self.window.download_queue.active_count,1)
        other=self.window.wco_downloads[keys[1]]['dialog'];other.terminal=True
        other.failed.emit('Server returned HTML')
        self.assertEqual(self.window.download_queue.active_count,0)

    def test_youtube_title_and_saved_permission_are_shared_with_queue(self):
        self.window.download_permission.setChecked(True)
        self.window.youtube_url.setText('https://youtu.be/BaW_jenozKc')
        with patch.object(self.window,'_start_worker') as start:self.window._start_youtube_download()
        worker=start.call_args.args[0]
        worker.signals.metadata.emit({'title':'Example episode'})
        self.window.show_downloads()
        self.assertTrue(self.window.download_permission.isChecked())
        item=next(iter(self.window.download_queue.jobs.values()))
        self.assertEqual(item.title,'Example episode')
        self.window.download_queue.cancel(item.id)
        self.assertTrue(self.window.youtube_job['cancel'].is_set())
        self.assertFalse(self.window.youtube_cancel_button.isEnabled())
        worker.signals.failed.emit('Cancelled')
        self.assertEqual(self.window.download_queue.active_count,0)

    def test_wco_failure_releases_slot_and_retry_reuses_the_same_block(self):
        self.window.download_permission.setChecked(True)
        self.window.download_queue.limit=1
        with patch('anime_watcher.wco_browser.WcoDownloadDialog',FakePlayer),patch.object(self.window,'_wco_session',return_value=object()):
            for number in (1,2):self.window._download_wco_episode('Show',EpisodeResult(f'Episode {number}',f'https://www.wco.tv/ep{number}',True,1,str(number),'Dub'))
            jobs=list(self.window.download_queue.jobs.values())
            first=self.window.wco_downloads[jobs[0].id]['dialog'];first.terminal=True
            first.failed.emit('Could not confirm highest quality after two attempts')
            self.assertEqual(jobs[1].status,'Connecting')
            self.assertEqual(self.window.download_queue.active_count,1)
            retry=self.window._download_rows[jobs[0].id][3]
            widgets=self.window._download_rows[jobs[0].id]
            self.assertEqual(retry.text(),'Retry');self.assertTrue(retry.isEnabled())
            retry.click()
        self.assertEqual(len(self.window.download_queue.jobs),2)
        self.assertIs(self.window._download_rows[jobs[0].id],widgets)
        self.assertEqual(list(self.window.download_queue.jobs.values())[-1].status,'Queued')
        self.window._save_download_snapshot()
        import json
        snapshot=json.loads((self.window.data_root/'download-queue.json').read_text())
        self.assertEqual(len(snapshot['jobs']),2)
        self.assertNotIn('getvid',json.dumps(snapshot))

    def test_wco_retry_requires_the_original_profile_and_current_permission(self):
        self.window.download_permission.setChecked(True)
        with patch('anime_watcher.wco_browser.WcoDownloadDialog',FakePlayer),patch.object(self.window,'_wco_session',return_value=object()):
            self.window._download_wco_episode('Show',EpisodeResult('Episode 1','https://www.wco.tv/ep1',True,1,'1','Dub'))
        job=next(iter(self.window.download_queue.jobs.values()))
        player=self.window.wco_downloads[job.id]['dialog'];player.terminal=True;player.failed.emit('Timeout')
        self.window.download_permission.setChecked(False)
        with patch('anime_watcher.qt_ui.QMessageBox.warning') as warning:self.window._retry_download(job)
        warning.assert_called_once();self.assertEqual(len(self.window.download_queue.jobs),1)
        job.database=Path('other.db')
        with patch('anime_watcher.qt_ui.QMessageBox.warning') as warning:self.window._retry_download(job)
        warning.assert_called_once();self.assertEqual(len(self.window.download_queue.jobs),1)


if __name__=='__main__':unittest.main()
