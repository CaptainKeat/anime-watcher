import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QFrame, QLabel, QPushButton, QTabWidget, QVBoxLayout, QWidget
from anime_watcher.downloader import CatalogResult, EpisodeResult
from anime_watcher.qt_ui import AnimeWatcherWindow


class WcoUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'APPDATA':self.temp.name});self.env.start()
        self.metadata=patch.object(AnimeWatcherWindow,'_auto_metadata');self.metadata.start()
        self.schedule=patch.object(AnimeWatcherWindow,'_refresh_release_schedule');self.schedule.start()
        self.window=AnimeWatcherWindow();self.window.library_root=Path(self.temp.name)/'library'
        self.window.show_downloads()

    def tearDown(self):
        self.window.close();self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);self.app.processEvents()
        self.schedule.stop();self.metadata.stop();self.env.stop();self.temp.cleanup()

    def test_wco_search_uses_browser_and_ignores_old_results(self):
        self.window.search_source.setText('https://www.wco.tv/')
        self.window.catalog_query.setText('dimensional')
        session=Mock()
        with patch.object(self.window,'_wco_session',return_value=session),patch.object(self.window,'_start_worker') as worker:
            self.window._catalog_search()
        worker.assert_not_called()
        query,done,failed=session.search.call_args.args
        self.assertEqual(query,'dimensional')
        self.window.show_home()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        done([CatalogResult('Show','https://www.wco.tv/anime/show')]);failed('old failure')
        self.window.show_downloads()
        self.assertEqual(self.window.catalog_status.text(),'')

    def test_filters_separate_seasons_and_versions(self):
        host=QWidget(self.window);box=QVBoxLayout(host)
        episodes=[EpisodeResult('Dub episode','https://www.wco.tv/dub',True,1,'1','Dub'),EpisodeResult('Sub episode','https://www.wco.tv/sub',True,2,'1','Sub')]
        self.window._catalog_episodes_ready(CatalogResult('Show','https://www.wco.tv/anime/show'),box,episodes)
        combos=host.findChildren(QComboBox)
        tabs=host.findChild(QTabWidget,'wcoEpisodeTabs')
        self.assertEqual([tabs.tabText(i) for i in range(tabs.count())],['Sub (1)','Dub (1)'])
        self.assertEqual(len(combos),1)
        for index,language in [(0,'Sub'),(1,'Dub')]:
            buttons=tabs.widget(index).findChildren(QPushButton)
            self.assertEqual([button.text() for button in buttons],['Download best available','Open page'])
            with patch.object(self.window,'_download_wco_episode') as download:
                buttons[0].click()
            self.assertEqual(download.call_args.args[1].language,language)
        combos[0].setCurrentIndex(combos[0].findData(2))
        self.assertEqual([tabs.tabText(i) for i in range(tabs.count())],['Sub (1)','Dub (0)'])
        empty=[label for label in tabs.widget(1).findChildren(QLabel) if label.text().startswith('No Dub episodes')][0]
        self.assertFalse(empty.isHidden())
        combos[0].setCurrentIndex(0)
        self.assertEqual(tabs.tabText(1),'Dub (1)')
        self.assertTrue(empty.isHidden())

    def test_first_episode_click_animates_without_navigation_and_repeat_reuses_it(self):
        self.window.download_permission.setChecked(True)
        host=QWidget();box=QVBoxLayout(host)
        self.window.catalog_results.addWidget(host)
        episode=EpisodeResult('Episode 1','https://www.wco.tv/episode-1',True,1,'1','Dub')
        self.window._catalog_episodes_ready(CatalogResult('Show','https://www.wco.tv/anime/show'),box,[episode])
        tabs=host.findChild(QTabWidget,'wcoEpisodeTabs')
        button=next(button for button in tabs.findChildren(QPushButton) if button.text()=='Download best available')
        self.assertEqual(self.window.download_tabs.currentIndex(),0)
        with patch.object(self.window,'_start_wco_job') as start:
            QTest.mouseClick(button,Qt.MouseButton.LeftButton)
            self.assertEqual(len(self.window.download_queue.jobs),1)
            self.assertEqual(self.window.download_tabs.currentIndex(),0)
            job=next(iter(self.window.download_queue.jobs.values()))
            self.assertEqual(job.status,'Connecting')
            self.assertIn(job.id,self.window._download_rows)
            flyout=self.window.findChild(QLabel,'downloadFlyout')
            self.assertIsNotNone(flyout)
            self.assertTrue(flyout.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
            self.assertIs(flyout.parentWidget(),self.window._download_page)
            self.assertTrue(any(label.text().endswith('Added to Downloads') for label in tabs.findChildren(QLabel)))
            QTest.mouseClick(button,Qt.MouseButton.LeftButton)
            self.assertEqual(self.window.download_tabs.currentIndex(),0)
            self.assertEqual(len(self.window.download_queue.jobs),1)
            start.assert_called_once()
        self.window.download_tabs.setCurrentIndex(0)
        self.assertIs(host.findChild(QTabWidget,'wcoEpisodeTabs'),tabs)
        self.assertEqual(tabs.currentWidget().property('wcoLanguage'),'Dub')
        QTest.qWait(800)
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.assertFalse(self.window.findChildren(QLabel,'downloadFlyout'))

    def test_navigation_during_download_animation_cleans_up_safely(self):
        origin=QPushButton('Download best available',self.window._download_page)
        self.window._animate_download_to_tab(origin)
        self.assertIsNotNone(self.window.findChild(QLabel,'downloadFlyout'))
        self.window.show_home()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        QTest.qWait(800)
        self.assertFalse(self.window.findChildren(QLabel,'downloadFlyout'))

    def bulk_host(self):
        host=QWidget(self.window);box=QVBoxLayout(host)
        episodes=[EpisodeResult(f'Episode {number}',f'https://www.wco.tv/{language}/{season}/{number}',True,season,str(number),language)
                  for language in ('Sub','Dub') for season in (1,2) for number in (2,1)]
        episodes.append(EpisodeResult('Special','https://www.wco.tv/special',True,1,'1.5','Sub'))
        self.window._catalog_episodes_ready(CatalogResult('Show','https://www.wco.tv/anime/show'),box,episodes)
        return host

    def test_bulk_controls_scope_to_current_season_and_version(self):
        host=self.bulk_host();seasons=host.findChild(QComboBox,'wcoSeasonFilter');tabs=host.findChild(QTabWidget,'wcoEpisodeTabs')
        selected=host.findChild(QPushButton,'wcoDownloadSelected');full=host.findChild(QPushButton,'wcoDownloadSeason')
        self.assertFalse(full.isEnabled());self.assertFalse(selected.isEnabled())
        seasons.setCurrentIndex(seasons.findData(1))
        self.assertIn('season 1',full.text());self.assertIn('Sub',full.text())
        host.findChild(QPushButton,'wcoSelectAll').click()
        self.assertEqual(selected.text(),'Download selected (2)')
        with patch.object(self.window,'_queue_wco_batch',return_value={'queued':2,'in_library':0,'already_queued':0,'unsupported':0,'duplicates':0}) as queued:
            selected.click()
        self.assertEqual([(e.season,e.language) for e in queued.call_args.args[1]],[(1,'Sub'),(1,'Sub')])
        self.assertTrue(queued.call_args.args[2]);self.assertFalse(selected.isEnabled())
        tabs.setCurrentIndex(1)
        with patch.object(self.window,'_queue_wco_batch',return_value={'queued':2,'in_library':0,'already_queued':0,'unsupported':0,'duplicates':0}) as queued:full.click()
        self.assertTrue(all(e.season==1 and e.language=='Dub' for e in queued.call_args.args[1]))
        self.assertIn('Queued 2',host.findChild(QLabel,'wcoBulkStatus').text())

    def test_selection_in_other_filters_never_enters_batch(self):
        host=self.bulk_host();seasons=host.findChild(QComboBox,'wcoSeasonFilter');tabs=host.findChild(QTabWidget,'wcoEpisodeTabs')
        boxes=host.findChildren(QCheckBox,'wcoEpisodeSelect')
        for box in boxes:
            if box.property('season')==2 and box.property('language')=='Dub':box.setChecked(True)
        seasons.setCurrentIndex(seasons.findData(1))
        self.assertFalse(host.findChild(QPushButton,'wcoDownloadSelected').isEnabled())
        tabs.setCurrentIndex(1);self.assertFalse(host.findChild(QPushButton,'wcoDownloadSelected').isEnabled())
        seasons.setCurrentIndex(seasons.findData(2))
        self.assertEqual(host.findChild(QPushButton,'wcoDownloadSelected').text(),'Download selected (2)')

    def test_batch_permission_duplicates_and_capacity(self):
        episodes=[EpisodeResult(f'Episode {n}',f'https://www.wco.tv/{n}',True,1,str(n),'Dub') for n in range(6,0,-1)]
        with patch('anime_watcher.qt_ui.QMessageBox.warning') as warning:
            self.assertIsNone(self.window._queue_wco_batch('Show',episodes))
        warning.assert_called_once();self.assertFalse(self.window.download_queue.jobs)
        self.window.download_permission.setChecked(True)
        with patch.object(self.window,'_start_wco_job') as start:
            first=self.window._queue_wco_batch('Show',episodes)
            repeated=self.window._queue_wco_batch('Show',episodes)
        self.assertEqual(first['queued'],6);self.assertEqual(repeated['already_queued'],6)
        self.assertEqual(start.call_count,3)
        self.assertEqual([job.title for job in self.window.download_queue.jobs.values()],[f'Show · Episode {n}' for n in range(1,7)])
        self.assertEqual((self.window.download_queue.active_count,self.window.download_queue.queued_count),(3,3))

    def test_bulk_existing_skip_can_be_disabled_for_upgrades(self):
        present=Path(self.temp.name)/'present.mp4';present.write_bytes(b'video')
        rows=[dict(season=1,episode=1,language='Dub',path=str(present))]
        episode=EpisodeResult('Episode 1','https://www.wco.tv/1',True,1,'1','Dub')
        self.window.download_permission.setChecked(True)
        with patch.object(self.window.db,'series',return_value=[{'id':1,'title':'Show'}]),patch.object(self.window.db,'episodes',return_value=rows),patch.object(self.window,'_start_wco_job'):
            skipped=self.window._queue_wco_batch('Show',[episode])
            included=self.window._queue_wco_batch('Show',[episode],False)
        self.assertEqual(skipped['in_library'],1);self.assertEqual(skipped['queued'],0)
        self.assertEqual(included['queued'],1);self.assertTrue(present.is_file())


if __name__=='__main__':unittest.main()
