from __future__ import annotations

import os


Bounds = tuple[int, int, int, int]


def geometry_for_bounds(bounds: Bounds, scale: float = 1.0) -> str:
    """Convert physical monitor bounds to Tk geometry without double-scaling size."""
    left, top, right, bottom = bounds
    safe_scale = max(0.25, float(scale or 1.0))
    width = max(1, round((right - left) / safe_scale))
    height = max(1, round((bottom - top) / safe_scale))
    return f"{width}x{height}{left:+d}{top:+d}"


def overlay_bounds_for_video(
    video_bounds: Bounds,
    scale: float,
    topbar_height: int = 76,
    controls_height: int = 170,
) -> tuple[Bounds, Bounds, Bounds]:
    """Return physical-pixel bounds for the topbar, controls, and click layer."""
    left, top, right, bottom = video_bounds
    safe_scale = max(0.25, float(scale or 1.0))
    physical_height = max(1, bottom - top)
    topbar_pixels = min(physical_height, max(1, round(topbar_height * safe_scale)))
    controls_pixels = min(
        max(0, physical_height - topbar_pixels),
        max(1, round(controls_height * safe_scale)),
    )
    topbar_bottom = min(bottom, top + topbar_pixels)
    controls_top = max(topbar_bottom, bottom - controls_pixels)
    topbar_bounds = (left, top, right, topbar_bottom)
    controls_bounds = (left, controls_top, right, bottom)
    input_bounds = (left, topbar_bottom, right, controls_top)
    return topbar_bounds, controls_bounds, input_bounds


def native_window_bounds(window_id: int, *, root: bool = False) -> Bounds | None:
    """Return an HWND rectangle in physical pixels, optionally using its root window."""
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

    user32 = ctypes.windll.user32
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    handle = wintypes.HWND(window_id)
    if root:
        handle = user32.GetAncestor(handle, 2) or handle  # GA_ROOT
    rect = RECT()
    if not user32.GetWindowRect(handle, ctypes.byref(rect)):
        return None
    return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)


def dpi_scale_for_window(window_id: int) -> float:
    """Return an HWND's physical-pixel scale relative to Tk's 96-DPI units."""
    if os.name != "nt":
        return 1.0

    import ctypes
    from ctypes import wintypes

    get_dpi = getattr(ctypes.windll.user32, "GetDpiForWindow", None)
    if get_dpi is None:
        return 1.0
    get_dpi.argtypes = [wintypes.HWND]
    get_dpi.restype = wintypes.UINT
    dpi = int(get_dpi(wintypes.HWND(window_id)) or 96)
    return max(0.25, dpi / 96.0)


def set_native_window_bounds(window_id: int, bounds: Bounds, *, root: bool = True) -> bool:
    """Place an HWND using unscaled physical pixels, bypassing Tk DPI transforms."""
    if os.name != "nt":
        return False

    import ctypes
    from ctypes import wintypes

    left, top, right, bottom = bounds
    width = max(1, right - left)
    height = max(1, bottom - top)
    user32 = ctypes.windll.user32
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    handle = wintypes.HWND(window_id)
    if root:
        handle = user32.GetAncestor(handle, 2) or handle  # GA_ROOT
    flags = 0x0004 | 0x0010 | 0x0020  # NOZORDER | NOACTIVATE | FRAMECHANGED
    return bool(user32.SetWindowPos(handle, wintypes.HWND(0), left, top, width, height, flags))


def monitor_bounds_for_window(window_id: int) -> Bounds | None:
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
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
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
