import unittest

from anime_watcher.media_chapters import chapter_ranges_from_chapters, intro_range_from_chapters


class IntroChapterTests(unittest.TestCase):
    def test_named_intro_uses_exact_embedded_range(self):
        chapters = [
            {"start_time": "0.000", "end_time": "139.013", "tags": {"title": "Prologue"}},
            {"start_time": "139.013", "end_time": "226.975", "tags": {"title": "Intro"}},
            {"start_time": "226.975", "end_time": "1332.000", "tags": {"title": "Part 1"}},
        ]
        self.assertEqual(intro_range_from_chapters(chapters), (139013, 226975))

    def test_opening_alias_is_recognized(self):
        chapters = [
            {"start_time": "45.5", "end_time": "135.5", "tags": {"title": "Opening Theme"}},
        ]
        self.assertEqual(intro_range_from_chapters(chapters), (45500, 135500))

    def test_untrusted_or_missing_chapters_do_not_guess(self):
        self.assertIsNone(intro_range_from_chapters([]))
        self.assertIsNone(intro_range_from_chapters([
            {"start_time": "0", "end_time": "1800", "tags": {"title": "Opening"}},
            {"start_time": "0", "end_time": "90", "tags": {"title": "Episode"}},
        ]))

    def test_classifies_recap_intro_outro_and_filler(self):
        chapters = [
            {"start_time": "0", "end_time": "30", "tags": {"title": "Recap"}},
            {"start_time": "30", "end_time": "120", "tags": {"title": "OP"}},
            {"start_time": "1200", "end_time": "1290", "tags": {"title": "Ending Theme"}},
            {"start_time": "1290", "end_time": "1320", "tags": {"title": "Next Episode Preview"}},
        ]
        self.assertEqual([item.kind for item in chapter_ranges_from_chapters(chapters)], ["recap", "intro", "outro", "filler"])


if __name__ == "__main__":
    unittest.main()
