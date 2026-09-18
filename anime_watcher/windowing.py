from __future__ import annotations

import os


def geometry_for_bounds(bounds: tuple[int, int, int, int]) -> str:
    """Convert (left, top, right, bottom) monitor bounds to Tk geometry."""
    left, top, right, bottom = bounds
    width = max(1, right - left)
    height = max(1, bottom - top)
    return f"{width}x{height}{left:+d}{top:+d}"


def monitor_bounds_for_window(window_id: int) -> tuple[int, int, int, int] | None:
    """Return the full bounds of the monitor nearest a native Windows window."""
    if os.name != "nt":
        return None

    import ctypes
    from ctypes import wintypes

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", RECT),
            ("rcWork", RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    user32 = ctypes.windll.user32
    root_window = user32.GetAncestor(wintypes.HWND(window_id), 2) or window_id  # GA_ROOT
    monitor = user32.MonitorFromWindow(wintypes.HWND(root_window), 2)  # nearest monitor
    if not monitor:
        return None
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    rect = info.rcMonitor
    return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
