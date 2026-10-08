import json
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from anime_watcher.database import LibraryDatabase
from anime_watcher.library_actions import move_library_episode
from anime_watcher.organizer import parse_episode
from anime_watcher.youtube_library import match_youtube_series, read_youtube_metadata, series_snapshot, suggested_slot, youtube_destination, youtube_metadata_path


class YouTubeGroupingTests(unittest.TestCase):
    def group(self, title, channel_ids=(), episodes=()):
        return {"title": title, "display_title": "", "channel_ids": set(channel_ids), "episodes": list(episodes)}

    def test_numbered_title_matches_canonical_series_with_legacy_duplicate_tab(self):
        series = self.group("That Time I Became a Test Slime")
        old = self.group("That Time I Became a Test Slime： Episode 10 [Picf46N3668]")
        metadata = {"title": "That Time I Became a Test Slime： Episode 10", "channel": "Example Studio"}
        self.assertIs(match_youtube_series(metadata, [series, old]), series)
        self.assertEqual(suggested_slot(metadata["title"], []), (1, 10))

    def test_id_text_is_never_an_episode_number(self):
        self.assertEqual(suggested_slot("My video [YE7VzlLtp-4]", []), (1, 1))
        self.assertEqual(parse_episode("YouTube - S123E4567 - S01E07 [YE7VzlLtp-4].mp4").episode, 4567)

    def test_title_wins_over_channel_with_multiple_shows(self):
        first = self.group("Example Abridged Show", ["UCexample"])
        other = self.group("Another Abridged Show", ["UCexample"])
        metadata = {"title": "Example Abridged Show - Episode 5", "channel_id": "UCexample"}
        self.assertIs(match_youtube_series(metadata, [first, other]), first)
        self.assertIsNone(match_youtube_series({"title": "Unrelated video", "channel_id": "UCexample"}, [first, other]))

    def test_unique_saved_channel_matches_unrelated_video_title(self):
        series = self.group("My Existing Channel Tab", ["UCexample"])
        self.assertIs(match_youtube_series({"title": "A new adventure", "channel_id": "UCexample"}, [series]), series)

    def test_channel_name_matches_legacy_channel_tab(self):
        series = self.group("Example Studio")
        self.assertIs(match_youtube_series({"title": "New upload", "channel": "example studio"}, [series]), series)

    def test_loose_words_and_ambiguous_titles_do_not_merge(self):
        self.assertIsNone(match_youtube_series({"title": "Slime tutorial"}, [self.group("Slime")]))
        self.assertIsNone(match_youtube_series({"title": "Example Show Episode 2"}, [self.group("Example Show"), self.group("Example-Show")]))

    def test_episode_label_fills_gap_and_unlabelled_title_appends(self):
        episodes = [{"season": 1, "episode": 1}, {"season": 1, "episode": 3}]
        self.assertEqual(suggested_slot("Example Show Episode 2", episodes), (1, 2))
        self.assertEqual(suggested_slot("A new upload", episodes), (1, 4))
        self.assertEqual(suggested_slot("Example Show #12", episodes), (1, 12))
        self.assertEqual(suggested_slot("Example Show S02E03", episodes), (2, 3))
        self.assertEqual(suggested_slot("Example Show S02E03", episodes, 4, 9), (4, 9))

    def test_destination_targets_existing_series_and_rejects_occupied_slot(self):
        group = self.group("Example Show", episodes=[{"season": 1, "episode": 1}])
        video = Path("Example Show Episode 2 [BaW_jenozKc].mp4")
        destination = youtube_destination(video, Path("library"), {"title": "Example Show Episode 2"}, [group])
        self.assertEqual(destination.parts[:3], ("library", "Example Show", "Season 01"))
        self.assertEqual(parse_episode(destination).episode, 2)
        with self.assertRaises(FileExistsError):
            youtube_destination(video, Path("library"), {"title": "Example Show Episode 1"}, [group])
        forced = youtube_destination(video, Path("library"), {"title": "Example Show Episode 2"}, [group], "My New Series", 2, 8)
        self.assertEqual(forced.parts[1], "My New Series")
        self.assertEqual(parse_episode(forced).episode, 8)


class MoveEpisodeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "library"
        self.source = self.root / "Example Show： Episode 10 [Picf46N3668]" / "Season 01" / "YouTube - S01E00 - Example Show： Episode 10 [Picf46N3668].mp4"
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b"new episode")
        self.subtitle = self.source.with_suffix(".en.srt")
        self.subtitle.write_text("Subtitles", encoding="utf-8")
        youtube_metadata_path(self.source).write_text(json.dumps({"id": "Picf46N3668", "channel_id": "UCexample", "channel": "Example Studio", "title": "Example Show Episode 10"}), encoding="utf-8")
        first = self.root / "Example Show" / "Season 01" / "Example Show - S01E01.mp4"
        first.parent.mkdir(parents=True)
        first.write_bytes(b"old episode")
        self.db = LibraryDatabase(Path(self.temp.name) / "library.db")
        with patch("anime_watcher.database.probe_embedded_language", return_value="Unknown"):
            self.db.scan_library(self.root)
        self.row = next(row for row in self.db.all_episodes() if row["path"] == str(self.source))
        self.db.save_progress(self.row["id"], 300000, 1200000)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_move_preserves_progress_subtitles_channel_and_series_metadata(self):
        target = next(series for series in self.db.series() if series["title"] == "Example Show")
        self.db.update_metadata(target["id"], "Example Show Official", "synopsis", "poster.png", 42)
        target_id = move_library_episode(self.db, self.root, self.row["id"], "Example Show", 1, 10)
        moved = self.db.episode(self.row["id"])
        path = Path(moved["path"])
        self.assertEqual(target_id, target["id"])
        self.assertEqual(moved["progress_ms"], 300000)
        self.assertEqual(path.read_bytes(), b"new episode")
        self.assertEqual(path.with_suffix(".en.srt").read_text(), "Subtitles")
        self.assertEqual(read_youtube_metadata(path)["channel_id"], "UCexample")
        self.assertIsNone(self.db.get_series(self.row["series_id"]))
        self.assertEqual(self.db.get_series(target_id)["poster_path"], "poster.png")
        with patch("anime_watcher.database.probe_embedded_language", return_value="Unknown"):
            self.db.scan_library(self.root)
        self.assertEqual(self.db.episode(self.row["id"])["episode"], 10)
        self.assertEqual(self.db.episode(self.row["id"])["progress_ms"], 300000)
        groups = series_snapshot(self.db.series(), self.db.all_episodes())
        self.assertEqual(match_youtube_series({"title": "Another upload", "channel_id": "UCexample"}, groups)["title"], "Example Show")

    def test_db_failure_rolls_video_and_companions_back(self):
        with patch.object(self.db, "relocate_episode", side_effect=RuntimeError("DB unavailable")), self.assertRaises(RuntimeError):
            move_library_episode(self.db, self.root, self.row["id"], "Example Show", 1, 10)
        self.assertEqual(self.source.read_bytes(), b"new episode")
        self.assertTrue(self.subtitle.is_file())
        self.assertTrue(youtube_metadata_path(self.source).is_file())
        self.assertEqual(self.db.episode(self.row["id"])["path"], str(self.source))

    def test_occupied_slot_leaves_both_videos_and_database_unchanged(self):
        with self.assertRaises(FileExistsError):
            move_library_episode(self.db, self.root, self.row["id"], "Example Show", 1, 1)
        self.assertTrue(self.source.is_file())
        self.assertEqual(self.db.episode(self.row["id"])["path"], str(self.source))

    def test_move_to_new_series_and_large_number_survives_rescan(self):
        target_id = move_library_episode(self.db, self.root, self.row["id"], "My New Channel", 123, 4567)
        with patch("anime_watcher.database.probe_embedded_language", return_value="Unknown"):
            self.db.scan_library(self.root)
        self.assertEqual(self.db.episode(self.row["id"])["episode"], 4567)
        self.assertEqual(self.db.episode(self.row["id"])["season"], 123)
        self.assertEqual(self.db.get_series(target_id)["title"], "My New Channel")

    def test_subtitle_move_failure_restores_video_before_updating_database(self):
        original_move = shutil.move

        def fail_subtitle(source, target):
            if Path(source) == self.subtitle:
                raise OSError("Subtitle move unavailable")
            return original_move(source, target)

        with patch("anime_watcher.library_actions.shutil.move", side_effect=fail_subtitle), self.assertRaises(OSError):
            move_library_episode(self.db, self.root, self.row["id"], "Example Show", 1, 10)
        self.assertTrue(self.source.is_file())
        self.assertTrue(self.subtitle.is_file())
        self.assertEqual(self.db.episode(self.row["id"])["path"], str(self.source))


if __name__ == "__main__":
    unittest.main()
