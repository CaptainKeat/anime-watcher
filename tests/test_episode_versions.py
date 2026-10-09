import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anime_watcher.database import LibraryDatabase
from anime_watcher.library_actions import plan_episode_version_update, update_episode_version


class EpisodeVersionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'library'
        self.db = LibraryDatabase(Path(self.temp.name) / 'library.db')
        self.sub = self.add(0, 'Sub')
        self.dub = self.add(1, 'Dub')
        self.db.save_progress(self.dub['id'], 300000, 6515704)
        self.source = Path(self.dub['path'])
        self.source.with_suffix('.en.srt').write_text('English subtitles')
        self.source.with_name(self.source.name + '.source.json').write_text('{"source":"fixture"}')

    def tearDown(self):
        self.db.close(); self.temp.cleanup()

    def add(self, number, language, title='Scarlet Bond', season=1):
        path = self.root / title / f'Season {season:02d}' / f'{title} - S{season:02d}E{number:02d} [{language}] [1080p].mkv'
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(language.encode())
        row, _ = self.db.index_download(path, self.root)
        return dict(row)

    def test_grouping_keeps_both_videos_progress_companions_and_survives_refresh(self):
        self.assertEqual(self.db.series()[0]['episode_count'], 2)
        update_episode_version(self.db, self.root, self.dub['id'], 1, 0, 'Dub')
        row = self.db.episode(self.dub['id']); destination = Path(row['path'])
        self.assertEqual(self.db.series()[0]['episode_count'], 1)
        self.assertEqual([r['language'] for r in self.db.episode_variants(self.sub['id'])], ['Sub', 'Dub'])
        self.assertEqual(destination.read_bytes(), b'Dub')
        self.assertEqual(Path(self.sub['path']).read_bytes(), b'Sub')
        self.assertEqual(destination.with_suffix('.en.srt').read_text(), 'English subtitles')
        self.assertTrue(destination.with_name(destination.name + '.source.json').is_file())
        self.assertIn('[1080p]', destination.name)
        self.db.scan_library(self.root)
        self.assertEqual(self.db.episode(self.dub['id'])['progress_ms'], 300000)
        self.assertEqual(self.db.series()[0]['episode_count'], 1)

    def test_language_correction_and_manual_numbering(self):
        update_episode_version(self.db, self.root, self.dub['id'], 2, 7, 'Sub')
        row = self.db.episode(self.dub['id'])
        self.assertEqual((row['season'], row['episode'], row['language']), (2, 7, 'Sub'))
        self.assertIn('S02E07 [Sub] [1080p]', row['path'])

    def test_existing_version_collision_preserves_both_files(self):
        before = dict(self.db.episode(self.dub['id']))
        with self.assertRaises(FileExistsError):
            update_episode_version(self.db, self.root, self.dub['id'], 1, 0, 'Sub')
        self.assertEqual(dict(self.db.episode(self.dub['id'])), before)
        self.assertEqual(self.source.read_bytes(), b'Dub')
        self.assertEqual(Path(self.sub['path']).read_bytes(), b'Sub')

    def test_companion_collision_is_checked_before_video_moves(self):
        plan = plan_episode_version_update(self.db, self.root, self.dub['id'], 1, 0, 'Dub')
        target = plan.destination.with_suffix('.en.srt'); target.write_text('existing')
        with self.assertRaises(FileExistsError):
            update_episode_version(self.db, self.root, self.dub['id'], 1, 0, 'Dub')
        self.assertTrue(self.source.is_file()); self.assertEqual(target.read_text(), 'existing')

    def test_database_failure_restores_video_companions_and_progress(self):
        before = dict(self.db.episode(self.dub['id']))
        self.db.connection.execute(f"CREATE TRIGGER reject_version BEFORE UPDATE ON episodes WHEN OLD.id={self.dub['id']} BEGIN SELECT RAISE(ABORT,'fixture'); END")
        self.db.connection.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            update_episode_version(self.db, self.root, self.dub['id'], 1, 0, 'Dub')
        self.assertEqual(dict(self.db.episode(self.dub['id'])), before)
        self.assertTrue(self.source.is_file()); self.assertTrue(self.source.with_suffix('.en.srt').is_file())

    def test_file_failure_restores_bundle_without_database_changes(self):
        before = dict(self.db.episode(self.dub['id']))
        import shutil
        move = shutil.move
        def fail(old, new):
            if Path(old).suffix == '.srt':
                raise OSError('locked companion')
            return move(old, new)
        with patch('anime_watcher.library_actions.shutil.move', side_effect=fail), self.assertRaises(OSError):
            update_episode_version(self.db, self.root, self.dub['id'], 1, 0, 'Dub')
        self.assertEqual(dict(self.db.episode(self.dub['id'])), before)
        self.assertTrue(self.source.is_file())

    def test_noop_keeps_filename_and_invalid_inputs_do_not_move_files(self):
        plan = plan_episode_version_update(self.db, self.root, self.dub['id'], 1, 1, 'Dub')
        self.assertEqual(plan.source, plan.destination)
        for season, number, language in [(-1, 1, 'Dub'), (1, 10000, 'Dub'), (1, 1, 'invalid')]:
            with self.assertRaises(ValueError):
                update_episode_version(self.db, self.root, self.dub['id'], season, number, language)
        self.assertTrue(self.source.is_file())


if __name__ == '__main__':
    unittest.main()
