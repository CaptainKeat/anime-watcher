import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from anime_watcher.database import LibraryDatabase
from anime_watcher.library_tools import prepare_library_transfer, transfer_library, TransferPaused, inspect_backup, TRANSFER_MARKER


class LibraryTransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.base = Path(self.temp.name)
        self.root = self.base / 'original'; self.root.mkdir(); self.target = self.base / 'portable'
        self.db = LibraryDatabase(self.base / 'library.db'); self.db.set_setting('library_root', str(self.root))
        self.path = self.root / 'Show' / 'Season 01' / 'Show - S01E01 [Sub].mp4'
        self.path.parent.mkdir(parents=True); self.path.write_bytes(b'original video' * 1000)
        row, _ = self.db.index_download(self.path, self.root); self.id = row['id']; self.series = row['series_id']
        self.db.save_progress(self.id, 400000, 1200000)
        self.db.connection.execute('UPDATE episodes SET title=? WHERE id=?', ('Custom title', self.id)); self.db.connection.commit()
        self.cancel = threading.Event(); self.progress = []

    def tearDown(self):
        self.db.close(); self.temp.cleanup()

    def plan(self):
        return prepare_library_transfer(self.db.path, self.root, self.target)

    @staticmethod
    def copy(source, target, cancel, progress, **kwargs):
        shutil.copy2(source, target); progress(1)

    def run_transfer(self, plan=None, copier=None):
        return transfer_library(self.db.path, plan or self.plan(), self.base / 'data', 'default', self.cancel, self.progress.append, copier=copier or self.copy)

    def unchanged(self):
        self.assertEqual(self.db.setting('library_root'), str(self.root))
        self.assertEqual(self.db.episode(self.id)['path'], str(self.path))
        self.assertEqual(self.path.read_bytes(), b'original video' * 1000)

    def test_transfer_preserves_ids_history_versions_metadata_and_companions(self):
        dub = self.path.with_name('Show - S01E01 [Dub].mp4'); dub.write_bytes(b'dub')
        other, _ = self.db.index_download(dub, self.root)
        self.path.with_suffix('.ass').write_text('subtitles')
        poster = self.root / 'Show' / 'poster.jpg'; poster.write_bytes(b'poster')
        self.db.update_metadata(self.series, 'A display title', 'Synopsis', str(poster), 42, 2020)
        recovery = self.root / '.anime-watcher-downloads'; recovery.mkdir(); (recovery / 'partial.mp4').write_bytes(b'incomplete')
        before = dict(self.db.episode(self.id)); result = self.run_transfer()
        after = dict(self.db.episode(self.id)); before['path'] = str(self.target / self.path.relative_to(self.root))
        self.assertEqual(after, before); self.assertEqual(self.db.episode(other['id'])['language'], 'Dub')
        self.assertEqual(self.db.get_series(self.series)['poster_path'], str(self.target / 'Show' / 'poster.jpg'))
        self.assertEqual(self.db.setting('library_root'), str(self.target))
        self.assertTrue(self.path.exists()); self.assertTrue(Path(after['path']).with_suffix('.ass').is_file())
        self.assertFalse((self.target / recovery.name).exists()); self.assertEqual(result['files'], 4)
        self.assertEqual(inspect_backup(result['backup'], 'default')['kind'], 'before-transfer')

    def test_cancel_keeps_original_and_resumes_verified_files(self):
        second = self.root / 'notes.txt'; second.write_bytes(b'notes')
        def interrupt(source, target, cancel, progress, **kwargs):
            self.copy(source, target, cancel, progress); cancel.set()
        with self.assertRaises(TransferPaused): self.run_transfer(copier=interrupt)
        self.unchanged(); self.cancel.clear()
        with patch.object(self, 'copy', wraps=self.copy) as copied:
            self.run_transfer(copier=copied)
        self.assertEqual(copied.call_count, 1)

    def test_corrupt_copy_does_not_switch(self):
        def corrupt(source, target, cancel, progress, **kwargs): target.write_bytes(b'bad bytes')
        with self.assertRaisesRegex(ValueError, 'Verification failed'): self.run_transfer(copier=corrupt)
        self.unchanged()
        self.run_transfer(); self.assertEqual(self.db.setting('library_root'), str(self.target))

    def test_changed_source_after_review_rejected(self):
        plan = self.plan(); self.path.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'changed after review'): self.run_transfer(plan)
        self.assertFalse(self.target.exists()); self.assertEqual(self.db.setting('library_root'), str(self.root))

    def test_changed_source_during_copy_does_not_switch(self):
        def mutate(source, target, cancel, progress, **kwargs):
            self.copy(source, target, cancel, progress); source.write_bytes(b'changed')
        with self.assertRaises(ValueError): self.run_transfer(copier=mutate)
        self.assertEqual(self.db.setting('library_root'), str(self.root))

    def test_changed_database_during_copy_does_not_switch(self):
        def mutate(source, target, cancel, progress, **kwargs):
            self.copy(source, target, cancel, progress)
            self.db.connection.execute('UPDATE episodes SET path=? WHERE id=?', (str(self.root / 'new.mp4'), self.id)); self.db.connection.commit()
        with self.assertRaisesRegex(ValueError, 'library changed during'): self.run_transfer(copier=mutate)
        self.assertEqual(self.db.setting('library_root'), str(self.root))

    def test_missing_indexed_file_keeps_history(self):
        self.path.unlink(); (self.root / 'notes.txt').write_text('still present')
        self.assertEqual(self.plan()['missing'], 1)
        self.run_transfer(); row = self.db.episode(self.id)
        self.assertEqual(row['progress_ms'], 400000); self.assertFalse(Path(row['path']).exists())

    def test_unrelated_target_and_changed_journal_rejected(self):
        self.target.mkdir(); unrelated = self.target / 'personal.txt'; unrelated.write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError, 'empty folder'): self.plan()
        unrelated.unlink(); self.cancel.set()
        with self.assertRaises(TransferPaused): self.run_transfer()
        self.cancel.clear(); self.run_transfer()
        self.db.set_setting('library_root', str(self.root))
        journal = self.target / TRANSFER_MARKER; data = json.loads(journal.read_text()); data['owner']['database'] = 'other'; journal.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'different or changed'): self.plan()
        self.assertEqual(self.path.read_bytes(), b'original video' * 1000)
        self.assertEqual(self.db.episode(self.id)['progress_ms'], 400000)

    def test_transaction_failure_rolls_back_all_paths(self):
        self.db.connection.execute("CREATE TRIGGER refuse_switch BEFORE INSERT ON settings WHEN NEW.key='library_root' BEGIN SELECT RAISE(ABORT,'fixture commit failure'); END")
        self.db.connection.commit()
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError): self.run_transfer()
        self.unchanged(); self.assertTrue((self.target / self.path.relative_to(self.root)).exists())

    def test_destination_modified_after_verification_does_not_switch(self):
        def progress(value):
            if value['phase'] == 'Verified':
                (self.target / self.path.relative_to(self.root)).write_bytes(b'changed target')
        with self.assertRaisesRegex(ValueError, 'Files changed'):
            transfer_library(self.db.path, self.plan(), self.base / 'data', 'default', self.cancel, progress, copier=self.copy)
        self.unchanged()

    def test_overlap_drive_root_and_relative_paths_rejected(self):
        for target in (self.root, self.root / 'nested', self.root.parent, Path(self.root.anchor), Path('relative')):
            with self.subTest(target=target), self.assertRaises(ValueError): prepare_library_transfer(self.db.path, self.root, target)

    def test_not_enough_space_and_other_database_root_rejected(self):
        with patch('anime_watcher.library_tools.shutil.disk_usage', return_value=shutil._ntuple_diskusage(1, 1, 0)):
            with self.assertRaisesRegex(ValueError, 'free space'): self.plan()
        self.db.set_setting('library_root', str(self.base / 'elsewhere'))
        with self.assertRaisesRegex(ValueError, 'library changed'): self.plan()

    def test_native_robocopy_verifies_unicode_and_preserves_original(self):
        from anime_watcher.library_tools import _robocopy_file
        companion = self.path.parent / '日本語 字幕.ass'; companion.write_text('unicode subtitles', encoding='utf-8')
        result = self.run_transfer(copier=_robocopy_file)
        self.assertEqual(result['files'], 2); self.assertTrue(self.path.exists())
        self.assertEqual((self.target / companion.relative_to(self.root)).read_bytes(), companion.read_bytes())
        self.assertTrue(self.progress)


if __name__ == '__main__': unittest.main()
