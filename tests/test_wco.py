import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs

from anime_watcher.downloader import EpisodeResult, extract_catalog_results, extract_episode_results, wco_search_request
from anime_watcher.wco import batch_episodes, best_quality, downloadable_media, import_wco_video, library_status, library_title, playable_media, single_stream_media


class WcoTests(unittest.TestCase):
    def test_batch_skips_same_version_only_and_sorts_numeric_slots(self):
        with tempfile.TemporaryDirectory() as tmp:
            present=Path(tmp)/'ep.mp4';present.write_bytes(b'video')
            local=[dict(season=1,episode=2,language='Dub',path=str(present)),dict(season=1,episode=3,language='Dub',path=str(Path(tmp)/'missing.mp4'))]
            episodes=[EpisodeResult(f'Episode {n}',f'https://www.wco.tv/{lang}/{n}',True,1,str(n),lang) for lang,n in [('Dub',10),('Dub',2),('Sub',2),('Dub',3)]]
            planned,stats=batch_episodes(episodes,local)
            self.assertEqual([(r.number,r.language) for r in planned],[('2','Sub'),('3','Dub'),('10','Dub')])
            self.assertEqual(stats['in_library'],1)
            upgraded,_=batch_episodes(episodes,local,False)
            self.assertEqual(len(upgraded),4);self.assertTrue(present.is_file())

    def test_batch_deduplicates_slots_and_urls_and_skips_ambiguous_specials(self):
        rows=[EpisodeResult('E1','https://www.wco.tv/1',True,1,'1','Dub'),
              EpisodeResult('E1 alias','https://www.wco.tv/alias',True,1,'01','Dub'),
              EpisodeResult('URL alias','https://www.wco.tv/1',True,1,'2','Dub'),
              EpisodeResult('Special','https://www.wco.tv/special',True,1,'1.5','Dub'),
              EpisodeResult('Gate','https://www.wco.tv/gate',False,1,'3','Dub'),
              EpisodeResult('Invalid slot','https://www.wco.tv/invalid',True,1,'10000','Dub')]
        planned,stats=batch_episodes(rows,[])
        self.assertEqual(len(planned),1);self.assertEqual(stats,{'in_library':0,'unsupported':3,'duplicates':2})

    def test_real_search_fields_and_encoding(self):
        url, body = wco_search_request(' Slime & Dragon ')
        self.assertEqual(url, 'https://www.wco.tv/search')
        self.assertEqual(parse_qs(body.decode()), {'catara':['Slime & Dragon'],'konuara':['series']})

    def test_search_titles_and_same_site_series_only(self):
        html = '<a href="/anime/my-show"><img alt="My Show" /></a><a href="https://evil.example/anime/my-show">My Show</a><a href="/my-show-episode-1">My Show Episode 1</a>'
        rows=extract_catalog_results(html,'https://www.wco.tv/search','my show')
        self.assertEqual([r.title for r in rows],['My Show'])

    def test_episode_scope_aliases_seasons_and_versions(self):
        html='''<div id="episodeList"><br/><a data-season="s2-0" data-lang="dub" href="/english-episode-24">Episode 24 English Dubbed</a><img/><a data-season="s1-0" data-lang="sub" href="/japanese-episode-24">Episode 24 English Subbed</a><a href="https://evil.example/episode">Episode 25</a></div><a href="/unrelated">Episode 99</a>'''
        rows=extract_episode_results(html,'https://www.wco.tv/anime/my-show')
        self.assertEqual([(r.season,r.number,r.language) for r in rows],[(2,'24','Dub'),(1,'24','Sub')])
        self.assertTrue(rows[1].url.endswith('/japanese-episode-24'))

    def test_highest_quality_and_invalid_media_state(self):
        self.assertEqual(best_quality(['SD','FHD','HD']),'FHD')
        self.assertEqual(best_quality(['1080p','2160p','720p']),'2160p')
        self.assertIsNone(best_quality(['FullHD download']))
        state=dict(readyState=4,width=1920,height=1080,duration=1442,src='https://u11.wcostream.com/getvid',error='')
        self.assertTrue(playable_media(state))
        for field,value in [('duration',float('inf')),('height',0),('src','blob:video'),('error','Network error')]:
            self.assertFalse(playable_media(dict(state,**{field:value})))

    def test_existing_title_and_version_status_require_real_file(self):
        rows=[dict(title='2.5 Dimensional Seduction',display_title='2.5 Dimensional Seduction')]
        self.assertEqual(library_title('2.5 dimensional seduction',rows),rows[0]['title'])
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'ep.mp4';file.write_bytes(b'video')
            episode=EpisodeResult('Episode 24','https://www.wco.tv/ep',True,1,'24','Dub')
            local=[dict(season=1,episode=24,language='Sub',path=str(file))]
            self.assertEqual(library_status(episode,local),'Other version in library')
            local[0]['language']='Dub'
            self.assertEqual(library_status(episode,local),'In library')
            file.unlink()
            self.assertEqual(library_status(episode,local),'Not downloaded')

    def test_browser_codec_fallback_requires_selected_real_player_source(self):
        state=dict(src='https://neptun.wcostream.com/getvid?evid=example',mp4Support='',selected='FHD',readyState=0,width=0,height=0,error='')
        self.assertTrue(downloadable_media(state))
        for field,value in [('src','https://evil.example/getvid'),('src','https://embed.wcostream.com/blank.mp3'),('selected',''),('mp4Support','probably'),('error','Network failure')]:
            self.assertFalse(downloadable_media(dict(state,**{field:value})))

    def test_single_stream_requires_loaded_declaration_and_real_source(self):
        state=dict(singleSource=True, choices=[], selected='', src='https://ndisk.wcostream.com/getvid?evid=example',
                   mp4Support='', height=0, error='')
        self.assertTrue(single_stream_media(state));self.assertTrue(downloadable_media(state))
        for field,value in [('singleSource',False),('singleSource',1),('choices',['HD']),('selected','SD'),
                            ('closeReady',True),('src','https://embed.wcostream.com/error.mp4'),
                            ('src','https://evil.example/getvid'),('mp4Support','probably'),('error','Network failure')]:
            with self.subTest(field=field,value=value):
                self.assertFalse(single_stream_media(dict(state,**{field:value})))

    def test_unlabeled_stream_import_uses_actual_resolution_and_rejects_invalid_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'episode.mp4';source.write_bytes(b'video')
            episode=EpisodeResult('Episode 14','https://www.wco.tv/ep14',True,1,'14','Dub')
            with patch('anime_watcher.wco.probe_video_size',return_value=(0,0)),self.assertRaises(ValueError):
                import_wco_video(source,Path(tmp)/'library','Show',episode,0)
            self.assertTrue(source.exists())
            with patch('anime_watcher.wco.probe_video_size',return_value=(854,480)):
                result=import_wco_video(source,Path(tmp)/'library','Show',episode,0)
            self.assertIn('[480p]',result.destination.name)
            metadata=json.loads(result.destination.with_name(result.destination.name+'.source.json').read_text())
            self.assertEqual((metadata['width'],metadata['height']),(854,480))

    def test_verified_import_preserves_other_quality_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'library';source=Path(tmp)/'episode.mp4';source.write_bytes(b'new video')
            existing=root/'Show'/'Season 01'/'Show - S01E24 [Dub] [480p].mp4'
            existing.parent.mkdir(parents=True);existing.write_bytes(b'old video')
            episode=EpisodeResult('Episode 24','https://www.wco.tv/ep24',True,1,'24','Dub')
            with patch('anime_watcher.wco.probe_video_size',return_value=(1920,1080)):
                result=import_wco_video(source,root,'Show',episode,1080)
            self.assertEqual(result.status,'moved')
            self.assertEqual(existing.read_bytes(),b'old video')
            self.assertIn('[1080p]',result.destination.name)
            metadata=json.loads(result.destination.with_name(result.destination.name+'.source.json').read_text())
            self.assertEqual(metadata['page_url'],episode.url)
            self.assertNotIn('getvid',json.dumps(metadata))

    def test_bad_or_lower_quality_download_stays_in_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'episode.mp4';source.write_bytes(b'not a high quality video')
            episode=EpisodeResult('Episode 24','https://www.wco.tv/ep24',True,1,'24','Dub')
            for size in [(0,0),(854,480)]:
                with patch('anime_watcher.wco.probe_video_size',return_value=size),self.assertRaises(ValueError):
                    import_wco_video(source,Path(tmp)/'library','Show',episode,1080)
                self.assertTrue(source.is_file())

    def test_failed_metadata_write_rolls_video_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'episode.mp4';source.write_bytes(b'video')
            episode=EpisodeResult('Episode 24','https://www.wco.tv/ep24',True,1,'24','Dub')
            with patch('anime_watcher.wco.probe_video_size',return_value=(1920,1080)),patch.object(Path,'write_text',side_effect=OSError('Disk error')),self.assertRaises(OSError):
                import_wco_video(source,Path(tmp)/'library','Show',episode,1080)
            self.assertEqual(source.read_bytes(),b'video')


if __name__=='__main__': unittest.main()
