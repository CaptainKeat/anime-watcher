import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anime_watcher.database import LibraryDatabase
from anime_watcher.library_extras import (library_view,storage_review,recycle_reviewed,file_inventory,
    save_skip_marker,custom_skip_markers,download_groups)
from anime_watcher.download_queue import DownloadJob


class LibraryExtrasTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)/'media'; self.root.mkdir()
        self.db=LibraryDatabase(Path(self.temp.name)/'local.db'); self.db.set_setting('library_root',str(self.root))
        self.paths=[]; self.rows=[]
        for title,language in [('Alpha','Sub'),('Alpha','Dub'),('Beta','Sub')]:
            path=self.root/title/'Season 01'/f'{title} - S01E01 [{language}].mp4'; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(b'video')
            row,_=self.db.index_download(path,self.root); self.paths.append(path); self.rows.append(row)
    def tearDown(self): self.db.close(); self.temp.cleanup()

    def test_watch_status_favorites_sort_and_version_filter(self):
        alpha,beta=self.rows[0]['series_id'],self.rows[2]['series_id']
        self.db.set_series_preferences(alpha,favorite=True,watch_state='On hold')
        self.db.update_metadata(alpha,'Alpha','',None,1,2020); self.db.update_metadata(beta,'Beta','',None,2,2024)
        self.assertEqual([row['title'] for row in library_view(self.db,favorite=True,state='On hold')],['Alpha'])
        self.assertEqual([row['title'] for row in library_view(self.db,language='Dub')],['Alpha'])
        self.assertEqual([row['title'] for row in library_view(self.db,sort='Year')],['Beta','Alpha'])
        self.assertEqual([row['title'] for row in library_view(self.db,year='2024')],['Beta'])
        self.assertEqual(library_view(self.db,year='Unknown'),[])
        self.db.set_series_preferences(alpha,watch_state='Automatic'); self.db.save_progress(self.rows[0]['id'],5000,300000)
        self.assertEqual([row['title'] for row in library_view(self.db,state='Watching')],['Alpha'])
        self.db.save_progress(self.rows[0]['id'],299000,300000)
        self.assertEqual([row['title'] for row in library_view(self.db,state='Completed')],['Alpha'])

    def test_quality_filter_requires_matching_current_file_signature(self):
        path=self.paths[0]; stat=path.stat(); self.db.set_setting('verified_video_heights',{str(path):1080})
        self.assertEqual(library_view(self.db,quality=1080),[])
        self.db.set_setting('verified_video_signatures',{str(path):[1080,stat.st_size,stat.st_mtime_ns]})
        self.assertEqual(len(library_view(self.db,quality=1080)),1)
        self.assertEqual(library_view(self.db,language='Dub',quality=1080),[])
        path.write_bytes(b'replacement low quality')
        self.assertEqual(library_view(self.db,quality=1080),[])

    def test_recovery_review_confines_cleanup_and_checks_every_selection_first(self):
        old=self.root/'.anime-watcher-downloads'/'imports'/'batch'/'old'; old.mkdir(parents=True); file=old/'old.mp4'; file.write_bytes(b'old')
        review=storage_review(self.root,[row['path'] for row in self.rows]); self.assertEqual(review['used'],15)
        self.assertEqual(review['recovery_bytes'],3); self.assertEqual(len(review['recovery']),1)
        with patch('anime_watcher.library_actions.send_to_recycle_bin') as recycle:
            file.write_bytes(b'changed');
            with self.assertRaisesRegex(ValueError,'changed'): recycle_reviewed(self.root,review['recovery'])
            recycle.assert_not_called()
            review=storage_review(self.root); recycle_reviewed(self.root,review['recovery']); recycle.assert_called_once_with(old,self.root.resolve(),recovery_folder=True)
        with self.assertRaises(ValueError): recycle_reviewed(self.root,[dict(path=str(self.root/'Alpha'),inventory={})])
        self.assertEqual(storage_review(self.root,[str(file)])['recovery'],[])

    def test_disconnected_drive_does_not_make_an_empty_inventory(self):
        with self.assertRaises(FileNotFoundError): file_inventory(self.root/'missing')
        hidden=self.root/'.anime-watcher-state'/'profiles'; hidden.mkdir(parents=True); (hidden/'private.mp4').write_bytes(b'not media')
        self.assertEqual(len(file_inventory(self.root,media_only=True)),3)

    def test_manual_markers_are_scoped_by_language_and_episode_overrides(self):
        sub,dub=dict(self.rows[0]),dict(self.rows[1]); sub['duration_ms']=300000
        save_skip_marker(self.db,sub,'intro',30000,120000,season=True)
        self.assertEqual(custom_skip_markers(self.db,dub),[])
        save_skip_marker(self.db,sub,'intro',40000,130000)
        self.assertEqual([(row.start_ms,row.end_ms) for row in custom_skip_markers(self.db,sub)],[(40000,130000)])
        self.assertEqual(custom_skip_markers(self.db,sub,100000),[])
        with self.assertRaises(ValueError): save_skip_marker(self.db,sub,'outro',200000,400000)
        with self.assertRaises(ValueError): save_skip_marker(self.db,sub,'intro',120000,30000)
        self.assertEqual(self.db.episode(sub['id'])['progress_ms'],0)

    def test_season_summary_uses_owner_and_numeric_status_with_honest_eta(self):
        jobs=[]
        for number,status in [(1,'Completed'),(2,'Downloading'),(3,'Queued'),(4,'Failed')]:
            job=DownloadJob(str(number),'YouTube','',self.db.path,self.root,'Default',lambda:None,lambda:None,status=status)
            job.retry_data=dict(title='Show',season=1,language='Sub',number=number)
            jobs.append(job)
        jobs[0].retry_data['verified_height']=720; jobs[0].retry_data['preferred_height']=1080
        result=download_groups(jobs,self.db.path)[0]
        self.assertEqual((result['completed'],result['active'],result['queued'],result['failed']),(1,1,1,1))
        self.assertEqual(result['progress'],250); self.assertIsNone(result['eta']); self.assertEqual(result['lower_quality'],1)
        self.assertEqual(download_groups(jobs,self.root/'other.db'),[])
        jobs[0].retry_data['season']='invalid'; self.assertTrue(download_groups(jobs,self.db.path))


if __name__=='__main__': unittest.main()
