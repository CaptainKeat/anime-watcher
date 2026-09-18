import shutil
import unittest
import uuid
from pathlib import Path

from anime_watcher.ui import AnimeWatcherApp


class PreviewFileHandoffTests(unittest.TestCase):
    def test_completed_preview_file_is_delivered_on_main_poll(self):
        directory = Path(__file__).parent / ".runtime" / str(uuid.uuid4())
        try:
            directory.mkdir(parents=True)
            frame = directory / "frame.jpg"
            frame.write_bytes(b"jpeg")

            class FakeApp:
                _preview_wait_job = object()
                _preview_request_token = 7
                preview_image_label = object()
                ready = None

                def _timeline_preview_ready(self, token, bucket, path):
                    self.ready = (token, bucket, path)

            fake = FakeApp()
            AnimeWatcherApp._wait_for_preview_file(fake, 7, 5000, frame)
            self.assertEqual(fake.ready, (7, 5000, frame))
            self.assertIsNone(fake._preview_wait_job)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_controls_do_not_hide_while_timeline_is_hovered(self):
        class Player:
            @staticmethod
            def is_playing():
                return True

        class FakeApp:
            current_episode_id = 1
            _timeline_hovered = True
            _seeking = False
            _controls_visible = True
            _controls_hide_job = object()
            player = Player()

        fake = FakeApp()
        AnimeWatcherApp._hide_player_controls(fake)
        self.assertTrue(fake._controls_visible)
        self.assertIsNone(fake._controls_hide_job)

    def test_last_duration_survives_a_temporary_buffering_zero(self):
        class Player:
            def __init__(self):
                self.values = iter((120000, 0))

            def duration(self):
                return next(self.values)

        class FakeApp:
            _known_duration_ms = 0
            player = Player()

        fake = FakeApp()
        self.assertEqual(AnimeWatcherApp._timeline_duration(fake), 120000)
        self.assertEqual(AnimeWatcherApp._timeline_duration(fake), 120000)

    def test_preview_is_raised_topmost_above_native_video_window(self):
        class Popup:
            def __init__(self):
                self.calls = []

            @staticmethod
            def winfo_exists():
                return True

            def deiconify(self):
                self.calls.append("deiconify")

            def wm_attributes(self, name, value):
                self.calls.append((name, value))

            def lift(self):
                self.calls.append("lift")

        class FakeApp:
            player_preview = Popup()

            @staticmethod
            def after_idle(callback):
                callback()

        fake = FakeApp()
        AnimeWatcherApp._raise_timeline_preview(fake)
        self.assertIn(("-topmost", True), fake.player_preview.calls)
        self.assertGreaterEqual(fake.player_preview.calls.count("lift"), 2)


if __name__ == "__main__":
    unittest.main()
