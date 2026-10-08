import json, tempfile, unittest, shutil, sqlite3
from pathlib import Path
from unittest.mock import patch
from anime_watcher.database import LibraryDatabase
from anime_watcher.library_actions import move_library_episodes, plan_library_episode_moves

class BulkMoveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'library'
        for title,season,number,version in [('Horimiya',1,1,'Sub'),('Horimiya Piece',1,1,'Sub'),('Horimiya Piece',1,2,'Sub')]:
            path=self.root/title/f'Season {season:02d}'/f'{title} - S{season:02d}E{number:02d} [{version}] [1080p].mkv'
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(f'{title}{number}'.encode())
        self.db=LibraryDatabase(Path(self.temp.name)/'library.db');self.db.scan_library(self.root)
        self.rows=[dict(row) for row in self.db.all_episodes() if row['series_title']=='Horimiya Piece'];self.ids=[r['id'] for r in self.rows]
        self.target=next(r for r in self.db.series() if r['title']=='Horimiya')
        self.db.update_metadata(self.target['id'],'Horimiya','synopsis','poster.png',42)
        for row in self.rows:
            path=Path(row['path']);path.with_suffix('.en.srt').write_text('subtitles')
            path.with_name(path.name+'.source.json').write_text(json.dumps({'provider':'wco','page_url':'https://www.wco.tv/example'}))
            self.db.save_progress(row['id'],300000,1200000)
        self.before=[dict(r) for r in self.db.all_episodes()]

    def tearDown(self):
        self.db.close();self.temp.cleanup()

    def unchanged(self):
        self.assertEqual([dict(r) for r in self.db.all_episodes()],self.before)
        for row in self.rows:
            path=Path(row['path']);self.assertTrue(path.exists());self.assertTrue(path.with_suffix('.en.srt').exists());self.assertTrue(path.with_name(path.name+'.source.json').exists())

    def test_whole_season_merges_with_progress_companions_and_quality(self):
        result=move_library_episodes(self.db,self.root,self.ids,'horimiya',2)
        self.assertEqual(result,self.target['id']);self.assertEqual(len(self.db.series()),1)
        self.assertEqual(self.db.get_series(result)['poster_path'],'poster.png')
        for row in self.rows:
            moved=self.db.episode(row['id']);path=Path(moved['path'])
            self.assertEqual((moved['season'],moved['episode'],moved['progress_ms']),(2,row['episode'],300000))
            self.assertIn('[1080p]',path.name);self.assertEqual(path.with_suffix('.en.srt').read_text(),'subtitles')
            self.assertEqual(json.loads(path.with_name(path.name+'.source.json').read_text())['provider'],'wco')
        self.db.scan_library(self.root)
        self.assertEqual(self.db.episode(self.ids[0])['progress_ms'],300000)
        self.assertFalse((self.root/'Horimiya Piece').exists())

    def test_late_slot_conflict_moves_nothing(self):
        with self.assertRaises(FileExistsError):move_library_episodes(self.db,self.root,self.ids,'Horimiya',1)
        self.unchanged()

    def test_late_subtitle_collision_moves_nothing(self):
        plans=plan_library_episode_moves(self.db,self.root,self.ids,'Horimiya',2)
        subtitle=plans[-1].destination.with_suffix('.en.srt');subtitle.parent.mkdir(parents=True);subtitle.write_text('existing')
        with self.assertRaises(FileExistsError):move_library_episodes(self.db,self.root,self.ids,'Horimiya',2)
        self.unchanged();self.assertEqual(subtitle.read_text(),'existing')

    def test_second_file_failure_restores_whole_batch(self):
        original=shutil.move
        def fail(source,target):
            if Path(source)==Path(self.rows[-1]['path']):raise OSError('Locked file')
            return original(source,target)
        with patch('anime_watcher.library_actions.shutil.move',side_effect=fail),self.assertRaises(OSError):
            move_library_episodes(self.db,self.root,self.ids,'Horimiya',2)
        self.unchanged()

    def test_second_database_update_failure_restores_files_and_all_rows(self):
        self.db.connection.execute(f"CREATE TRIGGER reject_bulk BEFORE UPDATE ON episodes WHEN OLD.id={self.ids[-1]} BEGIN SELECT RAISE(ABORT,'database write failure'); END")
        self.db.connection.commit()
        with self.assertRaises(sqlite3.IntegrityError):move_library_episodes(self.db,self.root,self.ids,'Horimiya',2)
        self.unchanged();self.assertEqual(len(self.db.series()),2)

    def test_renumber_keeps_variants_of_same_episode_together(self):
        row=self.rows[0];other=Path(row['path']).with_name(Path(row['path']).name.replace('[Sub]','[Dub]'));other.write_bytes(b'dub')
        self.db.scan_library(self.root)
        ids=[r['id'] for r in self.db.all_episodes() if r['series_title']=='Horimiya Piece']
        result=move_library_episodes(self.db,self.root,ids,'Horimiya',2,5)
        slots=[(r['season'],r['episode'],r['language']) for r in self.db.episodes(result) if r['season']==2]
        self.assertEqual(slots,[(2,5,'Sub'),(2,5,'Dub'),(2,6,'Sub')])

    def test_collapsing_two_source_seasons_requires_renumber(self):
        path=self.root/'Horimiya Piece'/'Season 02'/'Horimiya Piece - S02E01 [Sub].mkv';path.parent.mkdir(parents=True);path.write_bytes(b'next season')
        self.db.scan_library(self.root)
        ids=[r['id'] for r in self.db.all_episodes() if r['series_title']=='Horimiya Piece']
        with self.assertRaises(FileExistsError):plan_library_episode_moves(self.db,self.root,ids,'Horimiya',3)
        self.assertTrue(path.exists())
        self.assertEqual([p.episode for p in plan_library_episode_moves(self.db,self.root,ids,'Horimiya',3,1)],[1,2,3])

    def test_blank_title_and_missing_selection_are_rejected(self):
        for ids,title in [(self.ids,' '),([], 'Horimiya'),([999999],'Horimiya')]:
            with self.assertRaises(ValueError):plan_library_episode_moves(self.db,self.root,ids,title,2)
        self.unchanged()

    def test_renumber_overflow_is_rejected_before_moving(self):
        with self.assertRaises(ValueError):move_library_episodes(self.db,self.root,self.ids,'Horimiya',2,9999)
        self.unchanged()

if __name__=='__main__':unittest.main()
