from pathlib import Path
import shutil
import unittest
import uuid

from anime_watcher.organizer import destination_for, organize_file, parse_episode


class OrganizerTests(unittest.TestCase):
    def test_parses_animeheaven_season_filename(self):
        info = parse_episode("[AH2] From Old Country Bumpkin to Master Swordsman S2 - 06 (1080p)v0.mkv.mp4")
        self.assertEqual(info.title, "From Old Country Bumpkin to Master Swordsman")
        self.assertEqual(info.season, 2)
        self.assertEqual(info.episode, 6)

    def test_parses_episode_and_sub_label(self):
        info = parse_episode("Ragna Crimson - Episode 24 [English Sub].mp4")
        self.assertEqual(info.title, "Ragna Crimson")
        self.assertEqual(info.season, 1)
        self.assertEqual(info.episode, 24)
        self.assertEqual(info.language, "Sub")

    def test_parses_ep_style(self):
        info = parse_episode("The World's Finest Assassin - EP12 [English Sub].mp4")
        self.assertEqual(info.title, "The World's Finest Assassin")
        self.assertEqual(info.episode, 12)

    def test_destination_structure(self):
        target = destination_for("Chainsmoker Cat - 04.mp4", r"E:\ANIME")
        self.assertEqual(target.parts[-3:], ("Chainsmoker Cat", "Season 01", "Chainsmoker Cat - S01E04.mp4"))

    def test_move_does_not_overwrite_collision(self):
        tmp_path = Path(__file__).parent / ".runtime" / str(uuid.uuid4())
        try:
            source_a = tmp_path / "a" / "Show - 01.mp4"
            source_b = tmp_path / "b" / "Show - 01.mp4"
            source_a.parent.mkdir(parents=True)
            source_b.parent.mkdir(parents=True)
            source_a.write_bytes(b"first")
            source_b.write_bytes(b"second")
            library = tmp_path / "library"
            first = organize_file(source_a, library)
            second = organize_file(source_b, library)
            self.assertEqual(first.status, "moved")
            self.assertEqual(second.status, "moved")
            self.assertNotEqual(first.destination, second.destination)
            self.assertEqual(first.destination.read_bytes(), b"first")
            self.assertEqual(second.destination.read_bytes(), b"second")
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)
