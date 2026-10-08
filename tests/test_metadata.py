import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anime_watcher.metadata import _download_poster, _select_best_candidate, _title_match_score


class PosterResponse(io.BytesIO):
    def __init__(self, payload=b"image", url="https://cdn.myanimelist.net/images/poster.jpg", content_type="image/jpeg"):
        super().__init__(payload)
        self._url = url
        self.headers = type("Headers", (), {"get_content_type": lambda self: content_type})()

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


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

    def test_poster_download_rejects_untrusted_hosts_and_redirects(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "unsupported poster"):
                _download_poster("https://example.com/poster.jpg", directory, "bad")
            response = PosterResponse(url="https://example.com/redirected.jpg")
            with patch("urllib.request.urlopen", return_value=response), self.assertRaisesRegex(ValueError, "redirected outside"):
                _download_poster("https://cdn.myanimelist.net/images/poster.jpg", directory, "redirect")
            self.assertFalse((Path(directory) / "redirect.jpg.download").exists())

    def test_poster_download_is_bounded_and_atomic(self):
        with tempfile.TemporaryDirectory() as directory, patch("urllib.request.urlopen", return_value=PosterResponse()):
            result = Path(_download_poster("https://cdn.myanimelist.net/images/poster.jpg", directory, "ok"))
            self.assertEqual(result.read_bytes(), b"image")


if __name__ == "__main__":
    unittest.main()
