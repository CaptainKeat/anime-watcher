import unittest
from pathlib import Path

from anime_watcher.text_helpers import marquee_frame
from anime_watcher.ui_common import (
    choose_episode_variant,
    episode_language_options,
    episode_variant_options,
    language_switch_required,
    library_root_from_setting,
)


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


class EpisodeVariantOptionTests(unittest.TestCase):
    def test_sub_and_dub_get_clear_version_labels(self):
        variants = [
            {"id": 1, "language": "Sub", "path": "episode-sub.mp4"},
            {"id": 2, "language": "Dub", "path": "episode-dub.mp4"},
        ]
        self.assertEqual(
            episode_variant_options(variants),
            {"SUB VERSION": 1, "DUB VERSION": 2},
        )

    def test_duplicate_labels_are_not_dropped(self):
        variants = [
            {"id": 1, "language": "Unknown", "path": "one.mp4"},
            {"id": 2, "language": "Unknown", "path": "two.mkv"},
        ]
        self.assertEqual(
            episode_variant_options(variants),
            {"UNKNOWN VERSION 1": 1, "UNKNOWN VERSION 2": 2},
        )

    def test_quality_copies_collapse_to_one_language_choice(self):
        variants = [
            {"id": 1, "language": "Sub", "path": "episode-sub-720.mp4"},
            {"id": 2, "language": "Sub", "path": "episode-sub-1080.mp4"},
            {"id": 3, "language": "Dub", "path": "episode-dub-1080.mp4"},
        ]
        self.assertEqual(
            episode_language_options(variants, current_episode_id=2),
            {"SUB VERSION": 2, "DUB VERSION": 3},
        )

    def test_language_switch_warning_only_when_known_version_changes(self):
        self.assertFalse(language_switch_required("Dub", "Dub"))
        self.assertTrue(language_switch_required("Dub", "Sub"))
        self.assertTrue(language_switch_required("Sub", "Unknown"))
        self.assertFalse(language_switch_required("Unknown", "Sub"))

    def test_episode_picker_defaults_to_sub(self):
        variants = [
            {"id": 2, "language": "Dub", "path": "episode-dub.mp4"},
            {"id": 1, "language": "Sub", "path": "episode-sub.mp4"},
        ]
        self.assertEqual(choose_episode_variant(variants)["id"], 1)

    def test_saved_dub_preference_selects_dub(self):
        variants = [
            {"id": 1, "language": "Sub", "path": "episode-sub.mp4"},
            {"id": 2, "language": "Dub", "path": "episode-dub.mp4"},
        ]
        self.assertEqual(choose_episode_variant(variants, "Dub")["id"], 2)


if __name__ == "__main__":
    unittest.main()
