import unittest
from pathlib import Path

from PySide6.QtMultimedia import QMediaPlayer

from anime_watcher.qt_player import QtMediaPlayer, playback_smoke


class Backend:
    def __init__(self):
        self.source = None
        self.state = QMediaPlayer.PlaybackState.StoppedState
        self.position = 0
        self.length = 120_000
        self.play_calls = 0
        self.pause_calls = 0
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1
        self.state = QMediaPlayer.PlaybackState.StoppedState

    def setSource(self, source):
        self.source = source

    def play(self):
        self.play_calls += 1
        self.state = QMediaPlayer.PlaybackState.PlayingState

    def pause(self):
        self.pause_calls += 1
        self.state = QMediaPlayer.PlaybackState.PausedState

    def playbackState(self):
        return self.state

    def duration(self):
        return self.length

    def setPosition(self, value):
        self.position = value


class AudioOutput:
    def __init__(self):
        self.volume = None

    def setVolume(self, value):
        self.volume = value


class QtMediaPlayerTests(unittest.TestCase):
    def player(self):
        wrapper = QtMediaPlayer.__new__(QtMediaPlayer)
        wrapper.backend = Backend()
        wrapper.audio_output = AudioOutput()
        return wrapper

    def test_play_uses_a_local_qt_url_and_starts_playback(self):
        wrapper = self.player()
        wrapper.play("episode.mp4")
        self.assertTrue(wrapper.backend.source.isLocalFile())
        self.assertEqual(Path(wrapper.backend.source.toLocalFile()).name, "episode.mp4")
        self.assertEqual(wrapper.backend.play_calls, 1)

    def test_toggle_switches_between_playing_and_paused(self):
        wrapper = self.player()
        wrapper.toggle()
        self.assertTrue(wrapper.is_playing())
        wrapper.toggle()
        self.assertEqual(wrapper.backend.pause_calls, 1)

    def test_seek_and_volume_are_clamped(self):
        wrapper = self.player()
        wrapper.seek(999_999)
        wrapper.set_volume(125)
        self.assertEqual(wrapper.backend.position, 120_000)
        self.assertEqual(wrapper.audio_output.volume, 1.0)

    def test_playback_smoke_rejects_a_missing_file(self):
        self.assertEqual(playback_smoke("definitely-not-an-episode.mp4"), 2)


if __name__ == "__main__":
    unittest.main()
