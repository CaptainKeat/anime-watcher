from __future__ import annotations

import ctypes
import faulthandler
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
VENDOR_DIR = PROJECT_DIR / "vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

# Windows groups taskbar windows and caches their branding by AppUserModelID.
# Use a stable ID for this branded release so the old generic Tk/PyInstaller
# identity cannot keep supplying its cached icon.
if sys.platform == "win32":
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "AnimeWatcher.Desktop.Branded.v2"
        )
    except (AttributeError, OSError):
        pass

_CRASH_LOG = None


def install_crash_logging() -> None:
    global _CRASH_LOG
    try:
        data_root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "AnimeWatcher"
        data_root.mkdir(parents=True, exist_ok=True)
        _CRASH_LOG = (data_root / "crash.log").open("a", encoding="utf-8", buffering=1)
        _CRASH_LOG.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] Anime Watcher started\n")
        faulthandler.enable(_CRASH_LOG, all_threads=True)

        def log_exception(exc_type, exc_value, exc_traceback):
            _CRASH_LOG.write(f"[{datetime.now().isoformat(timespec='seconds')}] Unhandled Python exception\n")
            traceback.print_exception(exc_type, exc_value, exc_traceback, file=_CRASH_LOG)

        sys.excepthook = log_exception
    except OSError:
        _CRASH_LOG = None


install_crash_logging()

if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--playback-smoke":
        from anime_watcher.qt_player import playback_smoke

        raise SystemExit(playback_smoke(sys.argv[2]))
    if len(sys.argv) == 3 and sys.argv[1] == "--ass-smoke":
        from anime_watcher.ass_renderer import LibassRenderer

        with LibassRenderer(sys.argv[2]) as renderer:
            rendered = renderer.render(1000, 640, 360)
        raise SystemExit(0 if rendered.bitmap and max(rendered.bitmap.rgba[3::4]) > 0 else 4)

    from anime_watcher.qt_ui import run

    raise SystemExit(run())
