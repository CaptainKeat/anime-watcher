from pathlib import Path
import shutil
import unittest
import uuid
from unittest.mock import patch

from anime_watcher.database import LibraryDatabase


class DatabaseTests(unittest.TestCase):
    def test_targeted_download_index_preserves_progress_and_other_missing_entries(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'library';first=root/'Show'/'Season 01'/'Show - S01E01 [Dub].mp4'
            first.parent.mkdir(parents=True);first.write_bytes(b'video')
            db=LibraryDatabase(Path(tmp)/'library.db');row,added=db.index_download(first,root)
            self.assertTrue(added);db.save_progress(row['id'],300000,1200000)
            first.unlink()
            second=first.with_name('Show - S01E02 [Dub].mp4');second.write_bytes(b'video')
            with patch('anime_watcher.database.scan_video_files',side_effect=AssertionError('Full scan')):
                row,added=db.index_download(second,root)
            self.assertTrue(added);self.assertEqual(len(db.all_episodes()),2)
            first.write_bytes(b'video');row,added=db.index_download(first,root)
            self.assertFalse(added);self.assertEqual(row['progress_ms'],300000)
            for wrong in (Path(tmp)/'outside.mp4',root/'.anime-watcher-downloads'/'job'/'episode.mp4'):
                wrong.parent.mkdir(parents=True,exist_ok=True);wrong.write_bytes(b'video')
                with self.assertRaises(ValueError):db.index_download(wrong,root)
            db.close()

    def test_library_scan_ignores_pending_downloads(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'library';staging=root/'.anime-watcher-downloads'/'job'/'episode.mp4'
            staging.parent.mkdir(parents=True);staging.write_bytes(b'unverified')
            saved=root/'Show'/'Season 01'/'Show - S01E01 [Dub].mp4';saved.parent.mkdir(parents=True);saved.write_bytes(b'video')
            db=LibraryDatabase(Path(tmp)/'library.db');stats=db.scan_library(root)
            self.assertEqual(stats['files'],1);self.assertEqual(db.all_episodes()[0]['path'],str(saved));db.close()

    def test_scan_and_resume_progress(self):
        tmp_path = Path(__file__).parent / ".runtime" / str(uuid.uuid4())
        try:
            library = tmp_path / "Anime"
            episode = library / "Example Show" / "Season 01" / "Example Show - S01E02 [Dub].mp4"
            episode.parent.mkdir(parents=True)
            episode.write_bytes(b"video")
            db = LibraryDatabase(tmp_path / "library.db")
            stats = db.scan_library(library)
            self.assertEqual(stats["files"], 1)
            series = db.series()[0]
            self.assertEqual(series["title"], "Example Show")
            row = db.episodes(series["id"])[0]
            self.assertEqual(row["episode"], 2)
            self.assertEqual(row["language"], "Dub")
            db.save_progress(row["id"], 300_000, 1_200_000)
            self.assertEqual(db.continue_watching()[0]["progress_ms"], 300_000)
            relocated = library / "Correct Show" / "Season 02" / "Correct Show - S02E04 [Sub].mp4"
            relocated.parent.mkdir(parents=True)
            episode.rename(relocated)
            new_series_id = db.relocate_episode(row["id"], relocated, "Correct Show", 2, 4, "Sub")
            moved = db.episode(row["id"])
            self.assertEqual(moved["series_id"], new_series_id)
            self.assertEqual(moved["progress_ms"], 300_000)
            self.assertEqual(moved["path"], str(relocated))
            db.update_metadata(new_series_id, "Correct Show Official", "synopsis", "poster.jpg", 42)
            final_path = library / "Final Show" / "Season 02" / "Final Show - S02E04 [Sub].mp4"
            final_path.parent.mkdir(parents=True)
            relocated.rename(final_path)
            db.rename_series(new_series_id, "Final Show", {row["id"]: final_path})
            renamed_series = db.get_series(new_series_id)
            renamed_episode = db.episode(row["id"])
            self.assertEqual(renamed_series["title"], "Final Show")
            self.assertEqual(renamed_series["display_title"], "Final Show")
            self.assertIsNone(renamed_series["synopsis"])
            self.assertIsNone(renamed_series["poster_path"])
            self.assertIsNone(renamed_series["metadata_id"])
            self.assertIsNone(renamed_series["metadata_updated"])
            self.assertEqual(renamed_episode["progress_ms"], 300_000)
            self.assertEqual(renamed_episode["path"], str(final_path))
            db.close()
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    @patch("anime_watcher.database.probe_embedded_language", return_value="Unknown")
    def test_unlabeled_variant_beside_dub_is_inferred_as_sub(self, _probe):
        tmp_path = Path(__file__).parent / ".runtime" / str(uuid.uuid4())
        try:
            library = tmp_path / "Anime"
            season = library / "Chainsmoker Cat" / "Season 01"
            season.mkdir(parents=True)
            (season / "Chainsmoker Cat - S01E01 [Dub].mp4").write_bytes(b"dub")
            (season / "Chainsmoker Cat - S01E01.mp4").write_bytes(b"sub")
            db = LibraryDatabase(tmp_path / "library.db")
            stats = db.scan_library(library)
            episodes = db.episodes(db.series()[0]["id"])
            self.assertEqual(stats["language_updates"], 1)
            self.assertEqual([row["language"] for row in episodes], ["Sub", "Dub"])
            db.close()
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    @patch("anime_watcher.database.probe_embedded_language", return_value="Unknown")
    def test_confirmed_release_group_classifies_later_unlabeled_episode(self, _probe):
        tmp_path = Path(__file__).parent / ".runtime" / str(uuid.uuid4())
        try:
            library = tmp_path / "Anime"
            season = library / "Chainsmoker Cat" / "Season 01"
            season.mkdir(parents=True)
            (season / "[AH2] Chainsmoker Cat - 05 (1080p)v0.mkv.mp4").write_bytes(b"sub")
            (season / "Chainsmoker Cat - S01E05 [Dub].mp4").write_bytes(b"dub")
            (season / "[AH2] Chainsmoker Cat - 06 (1080p)v0.mkv.mp4").write_bytes(b"sub")
            db = LibraryDatabase(tmp_path / "library.db")
            stats = db.scan_library(library)
            episodes = db.episodes(db.series()[0]["id"])
            self.assertEqual(stats["language_updates"], 2)
            self.assertEqual(
                [(row["episode"], row["language"]) for row in episodes],
                [(5, "Sub"), (5, "Dub"), (6, "Sub")],
            )
            db.close()
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_next_episode_prefers_current_language(self):
        tmp_path = Path(__file__).parent / ".runtime" / str(uuid.uuid4())
        try:
            library = tmp_path / "Anime"
            season = library / "Example Show" / "Season 01"
            season.mkdir(parents=True)
            for episode in (1, 2):
                for language in ("Sub", "Dub"):
                    (season / f"Example Show - S01E{episode:02d} [{language}].mp4").write_bytes(b"video")
            db = LibraryDatabase(tmp_path / "library.db")
            db.scan_library(library)
            episodes = db.episodes(db.series()[0]["id"])
            current_dub = next(row for row in episodes if row["episode"] == 1 and row["language"] == "Dub")
            next_episode = db.next_episode(current_dub["id"])
            self.assertEqual(next_episode["episode"], 2)
            self.assertEqual(next_episode["language"], "Dub")
            self.assertEqual(db.series()[0]["episode_count"], 2)
            db.close()
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_series_language_preference_defaults_to_sub_and_persists_dub(self):
        tmp_path = Path(__file__).parent / ".runtime" / str(uuid.uuid4())
        try:
            db = LibraryDatabase(tmp_path / "library.db")
            self.assertEqual(db.series_language_preference(42), "Sub")
            db.set_series_language_preference(42, "Dub")
            self.assertEqual(db.series_language_preference(42), "Dub")
            db.set_series_language_preference(42, "Unknown")
            self.assertEqual(db.series_language_preference(42), "Dub")
            db.close()
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)
