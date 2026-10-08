import tempfile
import json
import shutil
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from anime_watcher.organizer import parse_episode
from anime_watcher.youtube import DownloadCancelled, _reject_live, download_youtube_video, youtube_video_url


URL = "https://www.youtube.com/watch?v=BaW_jenozKc"


class YouTubeTests(unittest.TestCase):
    def test_video_variants_strip_playlist_tracking_and_fragments(self):
        links = (
            URL + "&list=PLexample&index=2#t=10",
            "https://youtu.be/BaW_jenozKc?si=tracking",
            "https://m.youtube.com/shorts/BaW_jenozKc",
            "https://www.youtube.com/embed/BaW_jenozKc",
            "https://www.youtube.com/live/BaW_jenozKc",
        )
        for link in links:
            with self.subTest(link=link):
                self.assertEqual(youtube_video_url(link), URL)

    def test_rejects_non_video_urls_and_lookalike_hosts(self):
        for link in ("file:///video.mp4", "https://youtube.com.evil.example/watch?v=BaW_jenozKc",
                     "https://evil.example/youtu.be/BaW_jenozKc", "https://youtube.com/playlist?list=PLx",
                     "https://youtube.com/@channel", "https://youtu.be/short", "https://user:" + "pw@" + "youtube.com/watch?v=BaW_jenozKc"):
            with self.subTest(link=link), self.assertRaises(ValueError):
                youtube_video_url(link)

    def test_live_broadcasts_are_rejected_but_completed_recordings_are_allowed(self):
        self.assertIsNotNone(_reject_live({"is_live": True}))
        self.assertIsNotNone(_reject_live({"live_status": "is_upcoming"}))
        self.assertIsNone(_reject_live({"live_status": "was_live"}))

    def fake_downloader(self, mode="success", cancel=None, outside=None, metadata=None):
        test = self

        class FakeDownloader:
            def __init__(self, options):
                test.options = options

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def add_post_processor(self, processor, when):
                test.assertEqual(when, "after_move")
                self.processor = processor

            def extract_info(self, url, download):
                test.assertEqual(url, URL)
                test.assertTrue(download)
                job = Path(test.options["outtmpl"]).parent
                (job / "intermediate.mp4.part").write_bytes(b"partial")
                if mode == "failure":
                    raise RuntimeError("Network unavailable")
                if mode == "cancel":
                    cancel.set()
                test.options["progress_hooks"][0]({"status": "downloading", "downloaded_bytes": 8, "total_bytes": 16})
                final = outside or job / "Test video S02E15 [YE7VzlLtp-4].mp4"
                if mode != "missing":
                    final.write_bytes(b"complete video")
                self.processor.run({"filepath": str(final), **(metadata or {})})

        return FakeDownloader

    def test_imports_final_file_and_reports_progress(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            updates = []
            with patch("yt_dlp.YoutubeDL", self.fake_downloader()), patch("anime_watcher.youtube.find_ffmpeg", return_value="ffmpeg"):
                result = download_youtube_video(URL, root / "downloads", root / "library", "720p", progress=lambda *args: updates.append(args))
            self.assertEqual(result.status, "moved")
            self.assertTrue(result.destination.is_relative_to(root / "library"))
            self.assertEqual(result.destination.read_bytes(), b"complete video")
            self.assertEqual(parse_episode(result.destination).episode, 15)
            self.assertEqual(parse_episode(result.destination).season, 2)
            self.assertEqual(result.destination.parent.parent.name, "Test video S02E15")
            self.assertTrue(any(row[:2] == (8, 16) for row in updates))
            self.assertIn("[height<=720]", self.options["format"])
            self.assertNotIn("cookiefile", self.options)
            self.assertTrue(self.options["noplaylist"])
            self.assertEqual(len(list((root / "library").rglob("*.mp4"))), 1)

    def test_failure_and_cancellation_keep_partials_without_importing(self):
        for mode in ("failure", "cancel"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                cancel = threading.Event()
                expected = DownloadCancelled if mode == "cancel" else RuntimeError
                with patch("yt_dlp.YoutubeDL", self.fake_downloader(mode, cancel)), self.assertRaises(expected):
                    download_youtube_video(URL, root / "downloads", root / "library", cancel=cancel)
                self.assertFalse((root / "library").exists())
                self.assertEqual(len(list((root / "downloads").rglob("*.part"))), 1)

    def test_missing_or_outside_final_path_is_never_imported(self):
        for mode in ("missing", "outside"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                outside = root / "outside.mp4" if mode == "outside" else None
                with patch("yt_dlp.YoutubeDL", self.fake_downloader(mode, outside=outside)), self.assertRaises(RuntimeError):
                    download_youtube_video(URL, root / "downloads", root / "library")
                self.assertFalse((root / "library").exists())

    def test_without_ffmpeg_only_requests_combined_audio_video(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch("yt_dlp.YoutubeDL", self.fake_downloader()), patch("anime_watcher.youtube.find_ffmpeg", return_value=None):
                download_youtube_video(URL, root / "downloads", root / "library", "1080p")
            self.assertNotIn("+", self.options["format"])
            self.assertNotIn("ffmpeg_location", self.options)

    def test_cancel_before_start_creates_no_attempt(self):
        with tempfile.TemporaryDirectory() as temp:
            cancel = threading.Event()
            cancel.set()
            with self.assertRaises(DownloadCancelled):
                download_youtube_video(URL, Path(temp) / "downloads", Path(temp) / "library", cancel=cancel)
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_repeated_download_preserves_identical_library_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch("yt_dlp.YoutubeDL", self.fake_downloader()):
                first = download_youtube_video(URL, root / "downloads", root / "library")
                second = download_youtube_video(URL, root / "downloads", root / "library")
            self.assertEqual(second.status, "duplicate")
            self.assertEqual(second.destination, first.destination)
            self.assertEqual(len(list((root / "library").rglob("*.mp4"))), 1)
            self.assertTrue(second.source.exists())

    def test_separate_failed_attempts_never_overwrite_each_other(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch("yt_dlp.YoutubeDL", self.fake_downloader("failure")):
                for _ in range(2):
                    with self.assertRaises(RuntimeError):
                        download_youtube_video(URL, root / "downloads", root / "library")
            self.assertEqual(len(list((root / "downloads").rglob("*.part"))), 2)

    def test_download_uses_metadata_to_join_existing_series_and_saves_channel(self):
        from anime_watcher.youtube_library import read_youtube_metadata
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            groups = [{"title": "Example Abridged Show", "display_title": "", "channel_ids": set(), "episodes": [{"season": 1, "episode": 1}]}]
            metadata = {"id": "YE7VzlLtp-4", "title": "Example Abridged Show： Episode 2", "channel": "Example Studio", "channel_id": "UCexample"}
            with patch("yt_dlp.YoutubeDL", self.fake_downloader(metadata=metadata)):
                result = download_youtube_video(URL, root / "downloads", root / "library", library_series=groups)
            self.assertEqual(result.destination.parent.parent.name, "Example Abridged Show")
            self.assertEqual(parse_episode(result.destination).episode, 2)
            self.assertEqual(read_youtube_metadata(result.destination)["channel_id"], "UCexample")

    def test_unlabelled_new_upload_joins_saved_channel_at_next_slot(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            groups = [{"title": "My Channel Tab", "display_title": "", "channel_ids": {"UCexample"}, "episodes": [{"season": 1, "episode": 8}]}]
            metadata = {"id": "YE7VzlLtp-4", "title": "A new adventure", "channel": "Example Studio", "channel_id": "UCexample"}
            with patch("yt_dlp.YoutubeDL", self.fake_downloader(metadata=metadata)):
                result = download_youtube_video(URL, root / "downloads", root / "library", library_series=groups)
            self.assertEqual(result.destination.parent.parent.name, "My Channel Tab")
            self.assertEqual(parse_episode(result.destination).episode, 9)

    def test_existing_video_id_keeps_original_bytes_even_if_new_encode_differs(self):
        from anime_watcher.youtube_library import youtube_metadata_path
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            existing = root / "library" / "My Channel Tab" / "Season 01" / "YouTube - S01E02 - Old encode.mp4"
            existing.parent.mkdir(parents=True)
            existing.write_bytes(b"original encode")
            youtube_metadata_path(existing).write_text(json.dumps({"id": "YE7VzlLtp-4"}), encoding="utf-8")
            groups = [{"title": "My Channel Tab", "display_title": "", "channel_ids": {"UCexample"}, "episodes": [{"season": 1, "episode": 2, "video_id": "YE7VzlLtp-4", "path": str(existing)}]}]
            metadata = {"id": "YE7VzlLtp-4", "title": "New encode", "channel_id": "UCexample"}
            with patch("yt_dlp.YoutubeDL", self.fake_downloader(metadata=metadata)):
                result = download_youtube_video(URL, root / "downloads", root / "library", library_series=groups)
            self.assertEqual(result.status, "duplicate")
            self.assertEqual(existing.read_bytes(), b"original encode")

    def test_metadata_move_failure_keeps_complete_video_in_staging(self):
        original_move = shutil.move

        def fail_metadata(source, target):
            if str(source).endswith(".youtube.json"):
                raise OSError("Metadata move unavailable")
            return original_move(source, target)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch("yt_dlp.YoutubeDL", self.fake_downloader()), patch("anime_watcher.youtube.shutil.move", side_effect=fail_metadata), self.assertRaises(OSError):
                download_youtube_video(URL, root / "downloads", root / "library")
            self.assertEqual(len(list((root / "library").rglob("*.mp4"))), 0)
            self.assertEqual(len(list((root / "downloads").rglob("*.mp4"))), 1)


if __name__ == "__main__":
    unittest.main()
