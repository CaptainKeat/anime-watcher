from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtMultimedia import QAudioOutput, QMediaMetaData, QMediaPlayer, QVideoSink


class QtMediaPlayer:
    """Small compatibility wrapper around Qt's FFmpeg-backed media player."""

    def __init__(self, parent: QObject | None = None):
        self.backend = QMediaPlayer(parent)
        self.audio_output = QAudioOutput(parent)
        self.backend.setAudioOutput(self.audio_output)

    def attach(self, video_output) -> None:
        self.backend.setVideoOutput(video_output)

    def play(self, path: str | Path) -> None:
        self.backend.stop()
        self.backend.setSource(QUrl.fromLocalFile(str(Path(path).resolve())))
        self.backend.play()

    def toggle(self) -> None:
        if self.is_playing():
            self.backend.pause()
        else:
            self.backend.play()

    def is_playing(self) -> bool:
        return self.backend.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def set_rate(self, rate: float) -> None:
        self.backend.setPlaybackRate(float(rate))

    def stop(self) -> None:
        self.backend.stop()

    def time(self) -> int:
        return max(0, int(self.backend.position()))

    def duration(self) -> int:
        return max(0, int(self.backend.duration()))

    def seek(self, milliseconds: int) -> None:
        upper_bound = self.duration() or int(milliseconds)
        self.backend.setPosition(max(0, min(int(milliseconds), upper_bound)))

    def seek_relative(self, milliseconds: int) -> None:
        self.seek(self.time() + int(milliseconds))

    def set_volume(self, value: int) -> None:
        self.audio_output.setVolume(max(0.0, min(1.0, int(value) / 100.0)))

    def audio_tracks(self) -> list[tuple[int, str]]:
        return [
            (index, self._track_name(metadata, f"Audio {index + 1}"))
            for index, metadata in enumerate(self.backend.audioTracks())
        ]

    def subtitle_tracks(self) -> list[tuple[int, str]]:
        tracks = [(-1, "No subtitles")]
        tracks.extend(
            (index, self._track_name(metadata, f"Subtitle {index + 1}"))
            for index, metadata in enumerate(self.backend.subtitleTracks())
        )
        return tracks

    @staticmethod
    def _track_name(metadata: QMediaMetaData, fallback: str) -> str:
        title = metadata.stringValue(QMediaMetaData.Key.Title).strip()
        if title:
            return title
        language = metadata.value(QMediaMetaData.Key.Language)
        if language is not None:
            name = getattr(language, "name", "") or str(language)
            if name and name not in {"AnyLanguage", "Language.AnyLanguage"}:
                return name.replace("_", " ")
        return fallback

    def set_audio_track(self, track_id: int) -> None:
        self.backend.setActiveAudioTrack(int(track_id))

    def set_subtitle_track(self, track_id: int) -> None:
        self.backend.setActiveSubtitleTrack(int(track_id))

    def on_tracks_changed(self, callback: Callable[[], None]) -> None:
        self.backend.tracksChanged.connect(callback)

    def on_error(self, callback: Callable[[str], None]) -> None:
        self.backend.errorOccurred.connect(lambda _error, message: callback(str(message)))

    def release(self) -> None:
        self.backend.stop()
        self.backend.setVideoOutput(None)
        self.backend.setSource(QUrl())


def playback_smoke(path: str | Path, timeout_ms: int = 8_000) -> int:
    """Decode real audio/video offscreen; used to validate packaged playback."""
    media_path = Path(path)
    if not media_path.is_file():
        return 2
    app = QGuiApplication.instance() or QGuiApplication([])
    player = QMediaPlayer()
    audio = QAudioOutput()
    audio.setMuted(True)
    sink = QVideoSink()
    frame_count = 0

    def count_frame(frame) -> None:
        nonlocal frame_count
        if frame.isValid():
            frame_count += 1

    def finish() -> None:
        passed = (
            player.error() == QMediaPlayer.Error.NoError
            and player.position() >= 1_000
            and frame_count > 0
        )
        player.stop()
        app.exit(0 if passed else 3)

    sink.videoFrameChanged.connect(count_frame)
    player.setAudioOutput(audio)
    player.setVideoOutput(sink)
    player.setSource(QUrl.fromLocalFile(str(media_path.resolve())))
    player.play()
    QTimer.singleShot(timeout_ms, finish)
    return app.exec()
