from pathlib import Path
import shutil
import unittest
import uuid

from anime_watcher.library_actions import episode_destination, rename_episode_file, rename_series_files


class LibraryActionTests(unittest.TestCase):
    def setUp(self):
        self.tmp_path = Path(__file__).parent / ".runtime" / str(uuid.uuid4())
        self.library = self.tmp_path / "Anime"

    def tearDown(self):
        shutil.rmtree(self.tmp_path, ignore_errors=True)

    def test_episode_destination_sanitizes_title(self):
        destination = episode_destination(self.library, 'Wrong: Name?', 2, 4, "Dub", ".MKV")
        self.assertEqual(
            destination.parts[-3:],
            ("Wrong- Name-", "Season 02", "Wrong- Name- - S02E04 [Dub].mkv"),
        )

    def test_rename_moves_episode_to_correct_series_and_season(self):
        source = self.library / "Wrong Show" / "Season 01" / "Wrong Show - S01E01.mp4"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"video")
        destination = rename_episode_file(source, self.library, "Correct Show", 3, 7, "Sub")
        self.assertFalse(source.exists())
        self.assertEqual(
            destination,
            self.library / "Correct Show" / "Season 03" / "Correct Show - S03E07 [Sub].mp4",
        )
        self.assertEqual(destination.read_bytes(), b"video")

    def test_rename_rejects_files_outside_library(self):
        source = self.tmp_path / "outside.mp4"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"video")
        with self.assertRaises(ValueError):
            rename_episode_file(source, self.library, "Show", 1, 1, "Unknown")

    def test_series_rename_moves_every_episode(self):
        first = self.library / "Wrong Name" / "Season 01" / "Wrong Name - S01E01 [Sub].mkv"
        second = self.library / "Wrong Name" / "Season 02" / "Wrong Name - S02E03 [Dub].mp4"
        first.parent.mkdir(parents=True)
        second.parent.mkdir(parents=True)
        first.write_bytes(b"one")
        second.write_bytes(b"two")
        plans = rename_series_files(
            [
                {"id": 11, "path": str(first), "season": 1, "episode": 1, "language": "Sub"},
                {"id": 12, "path": str(second), "season": 2, "episode": 3, "language": "Dub"},
            ],
            self.library,
            "Correct Name",
        )
        self.assertEqual(plans[11][1].name, "Correct Name - S01E01 [Sub].mkv")
        self.assertEqual(plans[12][1].name, "Correct Name - S02E03 [Dub].mp4")
        self.assertEqual(plans[11][1].read_bytes(), b"one")
        self.assertEqual(plans[12][1].read_bytes(), b"two")
        self.assertFalse((self.library / "Wrong Name").exists())

    def test_series_rename_rejects_existing_anime_folder(self):
        source = self.library / "One" / "Season 01" / "One - S01E01.mp4"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"one")
        (self.library / "Two").mkdir(parents=True)
        with self.assertRaises(FileExistsError):
            rename_series_files(
                [{"id": 1, "path": str(source), "season": 1, "episode": 1, "language": "Unknown"}],
                self.library,
                "Two",
            )


if __name__ == "__main__":
    unittest.main()
