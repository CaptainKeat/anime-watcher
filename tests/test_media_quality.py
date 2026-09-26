import unittest
from unittest.mock import patch

from anime_watcher.media_quality import probe_quality_sources, quality_label


class MediaQualityTests(unittest.TestCase):
    def test_common_video_sizes_get_familiar_labels(self):
        self.assertEqual(quality_label(3840, 2160), "2160p")
        self.assertEqual(quality_label(1920, 1080), "1080p")
        self.assertEqual(quality_label(1280, 720), "720p")
        self.assertEqual(quality_label(852, 480), "480p")

    @patch("anime_watcher.media_quality.probe_video_size")
    def test_real_local_sources_sort_highest_quality_first(self, probe):
        probe.side_effect = [(1280, 720), (1920, 1080), (852, 480)]
        options = probe_quality_sources([
            (1, "episode-720.mp4"),
            (2, "episode-1080.mp4"),
            (3, "episode-480.mp4"),
        ])
        self.assertEqual([option["episode_id"] for option in options], [2, 1, 3])
        self.assertEqual([option["label"] for option in options], ["1080p", "720p", "480p"])


if __name__ == "__main__":
    unittest.main()
