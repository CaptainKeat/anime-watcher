from __future__ import annotations

import os
from pathlib import Path

VLC_DIR = Path(r"C:\Program Files\VideoLAN\VLC")
if os.name == "nt" and VLC_DIR.exists():
    os.environ.setdefault("PYTHON_VLC_LIB_PATH", str(VLC_DIR / "libvlc.dll"))
    os.environ.setdefault("PYTHON_VLC_MODULE_PATH", str(VLC_DIR / "plugins"))
    try:
        os.add_dll_directory(str(VLC_DIR))
    except (AttributeError, OSError):
        pass

import vlc


class VLCPlayer:
    def __init__(self):
        self.instance = vlc.Instance("--no-video-title-show", "--quiet")
        self.player = self.instance.media_player_new()

    def attach(self, window_id: int) -> None:
        if os.name == "nt":
            self.player.set_hwnd(window_id)
        else:
            self.player.set_xwindow(window_id)

    def play(self, path: str | Path, resume_ms: int = 0) -> None:
        media = self.instance.media_new_path(str(path))
        self.player.set_media(media)
        self.player.play()
        if resume_ms > 5000:
            # VLC needs a moment to parse the media before seeking.
            import time
            for _ in range(20):
                if self.player.get_length() > 0:
                    self.player.set_time(resume_ms)
                    break
                time.sleep(0.05)

    def toggle(self) -> None:
        self.player.pause()

    def is_playing(self) -> bool:
        return bool(self.player.is_playing())

    def set_rate(self, rate: float) -> None:
        self.player.set_rate(float(rate))

    def stop(self) -> None:
        self.player.stop()

    def time(self) -> int:
        return max(0, int(self.player.get_time()))

    def duration(self) -> int:
        return max(0, int(self.player.get_length()))

    def seek(self, milliseconds: int) -> None:
        self.player.set_time(max(0, min(milliseconds, self.duration() or milliseconds)))

    def seek_relative(self, milliseconds: int) -> None:
        self.seek(self.time() + milliseconds)

    def set_volume(self, value: int) -> None:
        self.player.audio_set_volume(max(0, min(100, value)))

    def audio_tracks(self) -> list[tuple[int, str]]:
        return [(int(track_id), self._track_name(name)) for track_id, name in (self.player.audio_get_track_description() or [])
                if int(track_id) >= 0]

    def subtitle_tracks(self) -> list[tuple[int, str]]:
        return [(int(track_id), "Disable subtitles" if int(track_id) < 0 else self._track_name(name))
                for track_id, name in (self.player.video_get_spu_description() or [])]

    @staticmethod
    def _track_name(value) -> str:
        return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)

    def set_audio_track(self, track_id: int) -> None:
        self.player.audio_set_track(track_id)

    def set_subtitle_track(self, track_id: int) -> None:
        self.player.video_set_spu(track_id)

    def release(self) -> None:
        self.stop()
        self.player.release()
        self.instance.release()
