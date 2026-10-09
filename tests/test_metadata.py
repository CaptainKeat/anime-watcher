import io
import json
import urllib.parse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anime_watcher.metadata import _download_poster, _fetch_jikan, _fetch_kitsu, _select_best_candidate, _title_match_score


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
    def test_shared_short_alias_does_not_beat_exact_canonical_title(self):
        candidates = [dict(title='Fate/stay night: Unlimited Blade Works', aliases=['Fate - Stay Night']),
                      dict(title='Fate/stay night', aliases=['Fate - Stay Night'])]
        result = _select_best_candidate('Fate/stay night', candidates, lambda item: [item['title'], *item['aliases']], 'test')
        self.assertEqual(result['title'], 'Fate/stay night')

    def test_exact_anime_beyond_first_five_candidates_beats_popular_spinoffs(self):
        for fetch, parameter in ((_fetch_jikan, 'limit'), (_fetch_kitsu, 'page[limit]')):
            titles = ['Fate/stay night [Unlimited Blade Works]', 'Fate/stay night: Heaven\'s Feel I',
                      'Fate/stay night: Heaven\'s Feel II', 'Fate/stay night: Heaven\'s Feel III',
                      'Fate/stay night: Unlimited Blade Works Movie', 'Fate/stay night']
            if fetch is _fetch_jikan:
                items = [dict(mal_id=n, title=title, year=2006 if n == 5 else 2014) for n, title in enumerate(titles)]
            else:
                items = [dict(id=str(n), attributes=dict(canonicalTitle=title, startDate='2006-01-07' if n == 5 else '2014-10-04')) for n, title in enumerate(titles)]
            with self.subTest(provider=fetch.__name__), tempfile.TemporaryDirectory() as temp:
                response = PosterResponse(json.dumps(dict(data=items)).encode())
                with patch('urllib.request.urlopen', return_value=response) as request, patch('anime_watcher.metadata._download_poster', return_value=''):
                    result = fetch('Fate/stay night', temp)
                query = urllib.parse.parse_qs(urllib.parse.urlparse(request.call_args.args[0].full_url).query)
                self.assertEqual(query[parameter], ['20'])
                self.assertEqual(result['title'], 'Fate/stay night')
                self.assertEqual(result['year'], 2006)

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
