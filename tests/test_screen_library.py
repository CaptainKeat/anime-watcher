import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QLabel, QPushButton, QComboBox, QDialog
from anime_watcher.database import LIBRARY_TYPES
from anime_watcher.metadata import fetch_metadata, metadata_source_url
from test_metadata import PosterResponse
import test_download_artwork_ui as artwork_fixture


class ScreenMetadataTests(unittest.TestCase):
    def movie(self, pageid, title, description, index=1):
        return dict(pageid=pageid,title=title,index=index,terms=dict(description=[description]),
                    extract='A movie synopsis.', original=dict(source='https://upload.wikimedia.org/wikipedia/en/poster.png'))

    def fetch_movie(self, title, pages):
        with tempfile.TemporaryDirectory() as folder:
            response=PosterResponse(json.dumps(dict(query=dict(pages={str(page['pageid']):page for page in pages}))).encode())
            with patch('urllib.request.urlopen',return_value=response), patch('anime_watcher.metadata._download_poster',return_value='poster.png'), \
                    patch('anime_watcher.metadata._fetch_jikan') as anime:
                result=fetch_metadata(title,folder,'Movies')
            anime.assert_not_called()
            return result

    def test_movie_matches_film_not_same_named_soundtrack_and_retains_year_and_source(self):
        movie=self.movie(19701,'Monty Python and the Holy Grail','1975 British comedy film')
        soundtrack=self.movie(2,'Monty Python and the Holy Grail','album by Monty Python',0)
        result=self.fetch_movie('Monty Python and the Holy Grail',[soundtrack,movie])
        self.assertEqual((result['id'],result['year']), (19701,1975))
        self.assertEqual(result['provider'],'Wikipedia')
        self.assertEqual(result['poster_path'],'poster.png')
        self.assertTrue(result['source_url'].startswith('https://en.wikipedia.org/wiki/'))

    def test_movie_remakes_require_year_and_year_selects_correct_film(self):
        pages=[self.movie(1,'Dune (1984 film)','1984 science fiction film'),self.movie(2,'Dune (2021 film)','2021 science fiction film',2)]
        with self.assertRaisesRegex(LookupError,'release year'): self.fetch_movie('Dune',pages)
        result=self.fetch_movie('Dune (2021)',pages)
        self.assertEqual((result['title'],result['id'],result['year']),('Dune',2,2021))
        with self.assertRaises(LookupError): self.fetch_movie('Dune (2000)',pages)

    def test_weak_movie_matches_are_rejected(self):
        with self.assertRaises(LookupError): self.fetch_movie('Holy Grail',[self.movie(1,'The Life of Brian','1979 film')])

    def test_musical_films_are_movies(self):
        self.assertEqual(self.fetch_movie('The Sound of Music',[self.movie(1,'The Sound of Music (film)','1965 American musical film')])['year'],1965)

    def test_tv_uses_tvmaze_and_year_disambiguates_remakes(self):
        candidates=[dict(show=dict(id=1,name='The Office',premiered='2001-07-09',summary='<p>Original show.</p>')),
                    dict(show=dict(id=2,name='The Office',premiered='2005-03-24',summary='<p>US show.</p>'))]
        with tempfile.TemporaryDirectory() as folder, patch('urllib.request.urlopen',return_value=PosterResponse(json.dumps(candidates).encode())), \
                patch('anime_watcher.metadata._fetch_jikan') as anime:
            result=fetch_metadata('The Office (2005)',folder,'TV Shows')
        anime.assert_not_called(); self.assertEqual((result['id'],result['year'],result['synopsis']),(2,2005,'US show.'))
        self.assertEqual(result['source_url'],'https://www.tvmaze.com/shows/2')

    def test_metadata_source_links_reject_untrusted_hosts_and_schemes(self):
        for provider,url in [('Wikipedia','https://en.wikipedia.org.evil.example/wiki/Film'),('TVmaze','javascript:alert(1)'),('Other','https://en.wikipedia.org/wiki/Film')]:
            self.assertEqual(metadata_source_url(provider,url),'')


class ScreenLibraryUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): artwork_fixture.DownloadArtworkTests.setUpClass(); cls.app=artwork_fixture.DownloadArtworkTests.app
    def setUp(self):
        self.fixture=artwork_fixture.DownloadArtworkTests(); self.fixture.setUp(); self.window=self.fixture.window
        self.sid=self.fixture.seed('Monty Python and the Holy Grail')
    def tearDown(self): self.fixture.tearDown()

    def test_category_change_preserves_episode_and_progress_and_fetches_movie_metadata(self):
        row=self.window.db.episodes(self.sid)[0]
        self.window.db.save_progress(row['id'],500,1000)
        before=dict(self.window.db.episode(row['id']))
        self.window.show_series(self.sid)
        self.assertIsNone(self.window._series_page.findChild(QComboBox,'moveLibraryTab'))
        def choose(dialog):
            dialog.findChild(QComboBox,'moveLibraryTab').setCurrentText('Movies')
            return QDialog.DialogCode.Accepted
        with patch.object(QDialog,'exec',choose): self.window._bulk_move_episodes([row['id']])
        self.assertEqual(dict(self.window.db.episode(row['id'])),before)
        worker=self.fixture.mocks[-2].call_args.args[0]
        worker.signals.done.emit(dict(self.fixture.data,title='Monty Python and the Holy Grail',year=1975,
            provider='Wikipedia',source_url='https://en.wikipedia.org/wiki/Monty_Python_and_the_Holy_Grail'))
        self.assertEqual(self.window.db.get_series(self.sid)['release_year'],1975)
        labels=[label.text() for label in self.window._series_page.findChildren(QLabel)]
        self.assertFalse(any(label.startswith('Season ') for label in labels))
        buttons=[button.text() for button in self.window._series_page.findChildren(QPushButton)]
        self.assertIn('▶   Play movie',buttons); self.assertNotIn('Link AniList',buttons)
        self.assertIsNotNone(self.window._series_page.findChild(QPushButton,'seriesMetadataSource'))
        self.window.show_library(); self.assertEqual(self.window._library_tabs.tabText(self.window._library_tabs.currentIndex()),'Movies')
        self.window.db.scan_library(self.window.library_root)
        self.assertEqual(self.window.db.get_series(self.sid)['library_type'],'Movies')

    def test_late_metadata_from_old_category_cannot_overwrite_new_category(self):
        self.window._refresh_metadata(self.sid)
        old_worker=self.fixture.mocks[-2].call_args.args[0]
        self.window.db.set_series_library_type(self.sid,'Movies')
        before=dict(self.window.db.get_series(self.sid))
        old_worker.signals.done.emit(dict(self.fixture.data,title='Wrong anime'))
        self.assertEqual(dict(self.window.db.get_series(self.sid)),before)

    def test_movie_and_tv_import_choices_persist_and_do_not_reclassify_other_items(self):
        for category,title in [('Movies','Example Film (2001)'),('TV Shows','Example Television')]:
            path=Path(self.fixture.temp.name)/f'{title}.mp4'; path.write_bytes(b'fixture')
            self.window.show_import(); self.window.import_library_type.setCurrentText(category)
            with patch('anime_watcher.qt_ui.ImportReviewDialog.exec',return_value=1): self.window._organize([path])
            self.fixture.mocks[-2].call_args.args[0].run()
            self.assertEqual(self.window.db.series_for_title(title)['library_type'],category)
        self.assertEqual(self.window.db.get_series(self.sid)['library_type'],'Anime')

    def test_tv_and_movie_tabs_only_show_their_own_entries(self):
        movie=self.sid; tv=self.fixture.seed('Example Television')
        self.window.db.set_series_library_type(movie,'Movies'); self.window.db.set_series_library_type(tv,'TV Shows')
        self.window.show_library()
        self.assertEqual(tuple(self.window._library_tabs.tabText(i) for i in range(4)),LIBRARY_TYPES)
        for index,title in [(2,'Monty Python and the Holy Grail'),(3,'Example Television')]:
            names=[label.text() for label in self.window._library_tabs.widget(index).findChildren(QLabel)]
            self.assertIn(title,names)
            self.assertNotIn('Example Television' if index==2 else 'Monty Python and the Holy Grail',names)

    def test_movies_are_excluded_from_anilist_sync_and_linked_schedule(self):
        self.window.db.link_anilist(self.sid,dict(id=99,title=dict(english='Example'),status='RELEASING'))
        self.window.db.set_series_library_type(self.sid,'Movies')
        self.assertEqual(self.window.db.linked_series(),[])
        self.assertEqual(self.window.db.update_release_schedule(dict(id=99)),(None,False))
