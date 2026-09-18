import shutil
import unittest
import uuid
from pathlib import Path

from anime_watcher.preview import (
    cached_video_preview,
    nearest_cached_video_preview,
    preview_bucket,
    preview_cache_name,
    preview_cache_path,
    preview_warmup_targets,
    trim_preview_cache,
)


class PreviewTests(unittest.TestCase):
    def test_preview_bucket_uses_five_second_intervals(self):
        self.assertEqual(preview_bucket(0), 0)
        self.assertEqual(preview_bucket(4999), 0)
        self.assertEqual(preview_bucket(5000), 5000)
        self.assertEqual(preview_bucket(12888), 10000)

    def test_cache_name_is_stable_within_bucket(self):
        folder = Path(__file__).parent / ".runtime" / str(uuid.uuid4())
        try:
            folder.mkdir(parents=True)
            video = folder / "episode.mkv"
            video.write_bytes(b"video")
            self.assertEqual(preview_cache_name(video, 10001), preview_cache_name(video, 14999))
            self.assertNotEqual(preview_cache_name(video, 10001), preview_cache_name(video, 15000))
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_cache_trim_keeps_newest_files(self):
        directory = Path(__file__).parent / ".runtime" / str(uuid.uuid4())
        try:
            directory.mkdir(parents=True)
            for index in range(5):
                item = directory / f"{index}.jpg"
                item.write_bytes(str(index).encode())
                item.touch()
            trim_preview_cache(directory, max_files=2)
            self.assertEqual(len(list(directory.glob("*.jpg"))), 2)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_nearest_cached_preview_returns_a_ready_neighbor(self):
        directory = Path(__file__).parent / ".runtime" / str(uuid.uuid4())
        try:
            directory.mkdir(parents=True)
            video = directory / "episode.mkv"
            video.write_bytes(b"video")
            nearby = preview_cache_path(video, 15000, directory)
            nearby.write_bytes(b"jpeg")
            self.assertIsNone(cached_video_preview(video, 10000, directory))
            self.assertEqual(nearest_cached_video_preview(video, 10000, directory), nearby)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_warmup_targets_cover_episode_before_filling_intervals(self):
        targets = preview_warmup_targets(60000, interval_ms=15000)
        self.assertEqual(targets[:5], [0, 15000, 30000, 45000, 55000])
        self.assertTrue(all(timestamp % 5000 == 0 for timestamp in targets))


if __name__ == "__main__":
    unittest.main()
