import unittest

from anime_watcher.metadata import _select_best_candidate, _title_match_score


class MetadataTitleMatchingTests(unittest.TestCase):
    def test_redo_of_healer_beats_unrelated_re_zero_result(self):
        candidates = [
            {
                "title": "Re:Zero kara Hajimeru Isekai Seikatsu: Shin Henshuu-ban",
                "title_english": "Re:Zero Starting Life in Another World - Director's Cut",
                "title_synonyms": [],
            },
            {
                "title": "Kaifuku Jutsushi no Yarinaoshi",
                "title_english": "Redo of Healer",
                "title_synonyms": ["Kaiyari"],
            },
        ]

        selected = _select_best_candidate(
            "Redo of Healer",
            candidates,
            lambda item: [item["title"], item["title_english"], *item["title_synonyms"]],
            "test provider",
        )

        self.assertEqual(selected["title_english"], "Redo of Healer")

    def test_weak_kitsu_results_are_rejected_so_fallback_can_continue(self):
        candidates = [
            {"title": "Re:Zero Starting Life in Another World - Director's Cut"},
            {"title": "Evangelion: 3.0 You Can (Not) Redo"},
        ]

        with self.assertRaisesRegex(LookupError, "no confident title match"):
            _select_best_candidate(
                "Redo of Healer",
                candidates,
                lambda item: [item["title"]],
                "Kitsu",
            )

    def test_extended_official_title_still_matches_short_library_title(self):
        self.assertGreaterEqual(
            _title_match_score("Re:Zero", "Re:Zero - Starting Life in Another World"),
            0.72,
        )

    def test_punctuation_and_ampersand_variants_match(self):
        self.assertEqual(_title_match_score("Spice & Wolf", "Spice and Wolf"), 1.0)


if __name__ == "__main__":
    unittest.main()
