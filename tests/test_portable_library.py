import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from anime_watcher.database import LibraryDatabase
from anime_watcher.portable_library import sync_portable,load_portable,portable_profiles,find_portable,new_portable_record,_exclusive
from anime_watcher.profiles import ProfileManager


class PortableLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.base=Path(self.temp.name); self.root=self.base/'drive'/'Anime'; self.root.mkdir(parents=True)
        self.db=LibraryDatabase(self.base/'computer'/'library.db'); self.db.set_setting('library_root',str(self.root))
        self.path=self.root/'Show'/'Season 01'/'Show - S01E01 [Sub].mp4'; self.path.parent.mkdir(parents=True); self.path.write_bytes(b'video')
        self.row,_=self.db.index_download(self.path,self.root); self.db.save_progress(self.row['id'],30000,120000)
        self.art=self.base/'poster.png'; self.art.write_bytes(b'artwork'); self.db.update_metadata(self.row['series_id'],'Show','Description',str(self.art),1,2020)
        self.record=dict(identity='test_identity',profile='default',root=str(self.root),sha256=None)
    def tearDown(self): self.db.close(); self.temp.cleanup()

    def test_round_trip_after_drive_change_preserves_ids_progress_and_artwork(self):
        self.db.set_series_preferences(self.row['series_id'],favorite=True,watch_state='Watching')
        self.record=sync_portable(self.db.path,self.root,self.record,'My profile')
        moved=self.base/'other-drive'/'Anime'; moved.parent.mkdir(); shutil.move(self.root,moved)
        identity,profiles=portable_profiles(moved); self.assertEqual((identity,profiles),('test_identity',[('default','My profile')]))
        target=self.base/'ally'/'library.db'; imported=load_portable(moved,'default',target,self.base/'ally'/'artwork')
        owner=LibraryDatabase(target)
        try:
            row=owner.episode(self.row['id']); series=owner.get_series(row['series_id'])
            self.assertEqual(row['progress_ms'],30000); self.assertEqual(row['duration_ms'],120000); self.assertTrue(Path(row['path']).is_file())
            self.assertTrue(series['favorite']); self.assertEqual(series['watch_state'],'Watching'); self.assertEqual(Path(series['poster_path']).read_bytes(),b'artwork')
            owner.save_progress(row['id'],60000,120000); imported=sync_portable(target,moved,imported,'My profile')
        finally: owner.close()
        another=self.base/'pc-again.db'; load_portable(moved,'default',another,self.base/'pc-art')
        owner=LibraryDatabase(another)
        try: self.assertEqual(owner.episode(self.row['id'])['progress_ms'],60000)
        finally: owner.close()

    def test_account_credentials_and_computer_download_history_do_not_travel(self):
        self.db.set_setting('anilist_token_protected','protected secret'); self.db.set_setting('anilist_viewer_name','User'); self.db.set_setting('download_history',[str(self.path)])
        self.record=sync_portable(self.db.path,self.root,self.record,'Profile'); snapshot=json.loads((self.root/'.anime-watcher-state'/'library.json').read_text())['profiles']['default']['file']
        connection=sqlite3.connect(self.root/'.anime-watcher-state'/'profiles'/snapshot)
        try:
            keys={row[0] for row in connection.execute('SELECT key FROM settings')}; self.assertNotIn('anilist_token_protected',keys); self.assertNotIn('download_history',keys)
            self.assertEqual(connection.execute('SELECT path FROM episodes').fetchone()[0],'portable-media/Show/Season 01/Show - S01E01 [Sub].mp4')
        finally: connection.close()
        self.assertEqual(self.db.setting('anilist_token_protected'),'protected secret')

    def test_stale_snapshot_refuses_to_overwrite_newer_device_progress(self):
        record=sync_portable(self.db.path,self.root,self.record,'Profile'); self.db.save_progress(self.row['id'],60000,120000)
        updated=sync_portable(self.db.path,self.root,record,'Profile')
        with self.assertRaisesRegex(ValueError,'another app'): sync_portable(self.db.path,self.root,record,'Profile')
        self.assertEqual(json.loads((self.root/'.anime-watcher-state'/'library.json').read_text())['profiles']['default']['sha256'],updated['sha256'])

    def test_missing_drive_preserves_local_working_database(self):
        self.record=sync_portable(self.db.path,self.root,self.record,'Profile'); shutil.rmtree(self.root)
        self.db.save_progress(self.row['id'],60000,120000)
        with self.assertRaises(FileNotFoundError): sync_portable(self.db.path,self.root,self.record,'Profile')
        self.assertEqual(self.db.episode(self.row['id'])['progress_ms'],60000); self.assertIsNone(find_portable(self.record,[]))

    def test_corrupt_snapshot_cannot_replace_existing_local_database(self):
        self.record=sync_portable(self.db.path,self.root,self.record,'Profile'); manifest=json.loads((self.root/'.anime-watcher-state'/'library.json').read_text())
        snapshot=self.root/'.anime-watcher-state'/'profiles'/manifest['profiles']['default']['file']; snapshot.write_bytes(b'corrupt')
        target=self.base/'existing.db'; target.write_bytes(b'original')
        with self.assertRaisesRegex(ValueError,'verified snapshot'): load_portable(self.root,'default',target,self.base/'art')
        self.assertEqual(target.read_bytes(),b'original')

    def test_sync_is_exclusive_and_keeps_only_current_and_previous_snapshot(self):
        self.record=sync_portable(self.db.path,self.root,self.record,'Profile')
        with _exclusive(self.root/'.anime-watcher-state'):
            with self.assertRaisesRegex(ValueError,'Another'): sync_portable(self.db.path,self.root,self.record,'Profile')
        for value in (35000,40000,45000):
            self.db.save_progress(self.row['id'],value,120000); self.record=sync_portable(self.db.path,self.root,self.record,'Profile')
        self.assertEqual(len(list((self.root/'.anime-watcher-state'/'profiles').glob('*.sqlite'))),2)

    def test_registry_attachment_survives_restart_without_changing_existing_profiles(self):
        manager=ProfileManager(self.base/'registry'); other=manager.create('Other'); manager.attach_portable(self.record)
        reload=ProfileManager(self.base/'registry'); self.assertEqual(reload.portable(),self.record); self.assertIn(other,reload.profiles())
        reload.attach_portable(None); self.assertIsNone(reload.portable())

    def test_new_profiles_share_identity_without_overwriting_an_existing_snapshot(self):
        self.record=sync_portable(self.db.path,self.root,self.record,'Profile')
        other=new_portable_record(self.root,'another_profile'); self.assertEqual(other['identity'],self.record['identity'])
        sync_portable(self.db.path,self.root,other,'Another profile')
        self.assertEqual(len(portable_profiles(self.root)[1]),2)
        with self.assertRaisesRegex(ValueError,'already has'): new_portable_record(self.root,'default')

    def test_damaged_metadata_is_reported_and_does_not_look_like_a_disconnected_drive(self):
        self.record=sync_portable(self.db.path,self.root,self.record,'Profile')
        marker=self.root/'.anime-watcher-state'/'library.json'; marker.write_text('[]')
        with self.assertRaises(ValueError): portable_profiles(self.root)
        with self.assertRaisesRegex(ValueError,'damaged'): find_portable(self.record,[])
        self.assertEqual(self.db.episode(self.row['id'])['progress_ms'],30000)

    def test_failed_export_cleans_temporary_snapshot_and_preserves_saved_manifest(self):
        self.record=sync_portable(self.db.path,self.root,self.record,'Profile')
        marker=self.root/'.anime-watcher-state'/'library.json'; original=marker.read_bytes()
        self.db.connection.execute('UPDATE episodes SET path=? WHERE id=?',(str(self.base/'outside.mp4'),self.row['id'])); self.db.connection.commit()
        with self.assertRaisesRegex(ValueError,'Every episode'): sync_portable(self.db.path,self.root,self.record,'Profile')
        self.assertEqual(marker.read_bytes(),original); self.assertFalse(list((self.root/'.anime-watcher-state'/'profiles').glob('*.tmp')))


if __name__=='__main__': unittest.main()
