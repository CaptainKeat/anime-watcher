import unittest
from pathlib import Path

from anime_watcher.text_helpers import marquee_frame
from anime_watcher.ui import library_root_from_setting


class MarqueeFrameTests(unittest.TestCase):
    def test_short_title_does_not_move(self):
        self.assertEqual(marquee_frame("Frieren", 999, 20), "Frieren")

    def test_long_title_returns_fixed_width_sliding_frames(self):
        title = "Suppose a Kid from the Last Dungeon Boonies"
        self.assertEqual(marquee_frame(title, 0, 12), title[:12])
        self.assertEqual(marquee_frame(title, 1, 12), title[1:13])
        self.assertEqual(len(marquee_frame(title, len(title) - 4, 12)), 12)

    def test_offset_wraps_cleanly(self):
        title = "A Very Long Anime Title"
        gap = " -- "
        runway_length = len(title + gap)
        self.assertEqual(
            marquee_frame(title, 3, 10, gap),
            marquee_frame(title, 3 + runway_length, 10, gap),
        )


class LibraryRootSettingTests(unittest.TestCase):
    def test_empty_setting_does_not_choose_a_drive_or_folder(self):
        self.assertIsNone(library_root_from_setting(None))
        self.assertIsNone(library_root_from_setting(""))
        self.assertIsNone(library_root_from_setting("   "))

    def test_saved_user_selection_is_preserved(self):
        self.assertEqual(library_root_from_setting(r"D:\Anime"), Path(r"D:\Anime"))


if __name__ == "__main__":
    unittest.main()
