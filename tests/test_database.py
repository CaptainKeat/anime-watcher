from pathlib import Path
import shutil
import unittest
import uuid

from anime_watcher.database import LibraryDatabase


class DatabaseTests(unittest.TestCase):
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
