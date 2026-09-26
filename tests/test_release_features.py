from pathlib import Path
import shutil
import unittest
import uuid

from anime_watcher.database import LibraryDatabase


class ReleaseFeatureDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Path(__file__).parent / ".runtime" / str(uuid.uuid4())
        self.runtime.mkdir(parents=True)
        self.db = LibraryDatabase(self.runtime / "library.db")
        self.db.connection.execute("INSERT INTO series(title) VALUES('Test Show')")
        self.series_id = int(self.db.connection.execute("SELECT id FROM series").fetchone()[0])
        self.db.connection.commit()

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.runtime, ignore_errors=True)

    def test_links_anilist_and_updates_schedule(self):
        media = {
            "id": 123,
            "title": {"english": "Test Show"},
            "status": "RELEASING",
            "nextAiringEpisode": {"episode": 4, "airingAt": 2_000_000_000},
        }
        self.db.link_anilist(self.series_id, media)
        linked = self.db.linked_series()[0]
        self.assertEqual(linked["anilist_id"], 123)
        updated = dict(media)
        updated["nextAiringEpisode"] = {"episode": 5, "airingAt": 2_000_100_000}
        series, changed = self.db.update_release_schedule(updated)
        self.assertTrue(changed)
        self.assertEqual(series["next_airing_episode"], 5)

    def test_notifications_deduplicate_by_fingerprint(self):
        self.assertTrue(self.db.add_notification("airing", "Title", "Body", self.series_id, "same"))
        self.assertFalse(self.db.add_notification("airing", "Title", "Body", self.series_id, "same"))
        self.assertEqual(self.db.unread_notification_count(), 1)
        self.db.mark_notifications_read()
        self.assertEqual(self.db.unread_notification_count(), 0)


if __name__ == "__main__":
    unittest.main()
