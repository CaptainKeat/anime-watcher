import unittest

from anime_watcher.downloader import _search_page_urls, extract_catalog_results, extract_episode_results


class CatalogSearchTests(unittest.TestCase):
    def test_partial_title_search_is_case_insensitive(self):
        html = """
        <a href="/anime/solo-leveling"><span>Solo Leveling</span></a>
        <a href="/anime/other-show">Other Show</a>
        """
        results = extract_catalog_results(html, "https://catalog.example/browse", "LEVEL")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Solo Leveling")
        self.assertEqual(results[0].url, "https://catalog.example/anime/solo-leveling")
        self.assertFalse(results[0].direct_media)

    def test_matches_url_slug_and_marks_direct_media(self):
        html = '<a href="media/Ragna.Crimson.S01E05.MKV">Watch now</a>'
        results = extract_catalog_results(html, "https://catalog.example/list/", "ragna crimson")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://catalog.example/list/media/Ragna.Crimson.S01E05.MKV")
        self.assertTrue(results[0].direct_media)

    def test_query_placeholder_builds_one_encoded_search_url(self):
        urls = _search_page_urls("https://catalog.example/find?q={query}", "Slime Movie")
        self.assertEqual(urls, ["https://catalog.example/find?q=Slime+Movie"])

    def test_common_search_urls_include_animeheaven_style_endpoint(self):
        urls = _search_page_urls("https://catalog.example/", "Chainsmoker Cat")
        self.assertIn("https://catalog.example/search.php?s=Chainsmoker+Cat", urls)
        self.assertIn("https://catalog.example/fastsearch.php?xhr=1&s=Chainsmoker+Cat", urls)

    def test_extracts_unique_episode_links(self):
        html = """
        <a href="/watch/show-2">Episode 2</a>
        <a href="/watch/show-1"><span>Episode</span> 1</a>
        <a href="/about">About this show</a>
        """
        episodes = extract_episode_results(html, "https://catalog.example/anime/show")
        self.assertEqual([episode.title for episode in episodes], ["Episode 2", "Episode 1"])
        self.assertTrue(all(episode.direct_open for episode in episodes))

    def test_cookie_selected_gate_links_are_not_opened_as_direct_episode_urls(self):
        html = """
        <a href="gate.php" onclick="gatea('abc')" onmouseover="gateh('abc')">Episode 12</a>
        <a href="gate.php" onclick="gatea('def')">Episode 11</a>
        """
        episodes = extract_episode_results(html, "https://anime.example/anime.php?id=show")
        self.assertEqual(len(episodes), 2)
        self.assertFalse(episodes[0].direct_open)
        self.assertFalse(episodes[1].direct_open)
        self.assertEqual(episodes[0].url, "https://anime.example/gate.php")

    def test_short_query_is_rejected(self):
        with self.assertRaises(ValueError):
            extract_catalog_results("<a href='/a'>A</a>", "https://example.com", "a")


if __name__ == "__main__":
    unittest.main()
