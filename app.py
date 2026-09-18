from __future__ import annotations

import ctypes
import os
import sys
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

VLC_DIR = Path(r"C:\Program Files\VideoLAN\VLC")
if sys.platform == "win32" and VLC_DIR.exists():
    os.environ.setdefault("PYTHON_VLC_LIB_PATH", str(VLC_DIR / "libvlc.dll"))
    os.environ.setdefault("PYTHON_VLC_MODULE_PATH", str(VLC_DIR / "plugins"))
    try:
        os.add_dll_directory(str(VLC_DIR))
    except (AttributeError, OSError):
        pass

from anime_watcher.ui import AnimeWatcherApp


if __name__ == "__main__":
    AnimeWatcherApp().mainloop()
