from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


ASS_FONTPROVIDER_AUTODETECT = 1
ASS_FONTPROVIDER_DIRECTWRITE = 4
FONT_EXTENSIONS = {".ttf", ".otf", ".ttc", ".otc"}


class LibassUnavailable(RuntimeError):
    """Raised when the bundled libass runtime cannot be loaded."""


class _ASSImage(ctypes.Structure):
    pass


_ASSImagePointer = ctypes.POINTER(_ASSImage)
_ASSImage._fields_ = [
    ("w", ctypes.c_int),
    ("h", ctypes.c_int),
    ("stride", ctypes.c_int),
    ("bitmap", ctypes.POINTER(ctypes.c_ubyte)),
    ("color", ctypes.c_uint32),
    ("dst_x", ctypes.c_int),
    ("dst_y", ctypes.c_int),
    ("next", _ASSImagePointer),
    ("type", ctypes.c_int),
]


@dataclass(frozen=True)
class AssBitmap:
    x: int
    y: int
    width: int
    height: int
    rgba: bytes


@dataclass(frozen=True)
class AssRenderResult:
    changed: bool
    bitmap: AssBitmap | None


def _runtime_directory() -> Path:
    candidates: list[Path] = []
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.append(Path(bundle_root) / "libass")
    candidates.append(Path(__file__).resolve().parent.parent / "third_party" / "libass" / "bin")
    for candidate in candidates:
        if (candidate / "libass-9.dll").is_file():
            return candidate
    raise LibassUnavailable("The bundled libass subtitle runtime was not found")


def _configure_api(library: ctypes.CDLL) -> None:
    library.ass_library_version.restype = ctypes.c_int
    library.ass_library_init.restype = ctypes.c_void_p
    library.ass_library_done.argtypes = [ctypes.c_void_p]
    library.ass_renderer_init.argtypes = [ctypes.c_void_p]
    library.ass_renderer_init.restype = ctypes.c_void_p
    library.ass_renderer_done.argtypes = [ctypes.c_void_p]
    library.ass_set_frame_size.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    library.ass_set_storage_size.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    library.ass_set_fonts.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    library.ass_get_available_font_providers.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_int)),
        ctypes.POINTER(ctypes.c_size_t),
    ]
    library.ass_read_memory.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p]
    library.ass_read_memory.restype = ctypes.c_void_p
    library.ass_free_track.argtypes = [ctypes.c_void_p]
    library.ass_add_font.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
    library.ass_render_frame.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_longlong,
        ctypes.POINTER(ctypes.c_int),
    ]
    library.ass_render_frame.restype = _ASSImagePointer


class LibassRenderer:
    """Render an external ASS/SSA track to transparent RGBA pixels.

    This class never creates a native or Qt window. The caller owns where the
    returned pixels are composited, which keeps Anime Watcher's video and
    subtitles inside one Qt scene on Windows.
    """

    def __init__(self, subtitle_path: str | Path):
        self.subtitle_path = Path(subtitle_path).resolve()
        self._dll_directory = None
        self._library_handle: int | None = None
        self._renderer_handle: int | None = None
        self._track_handle: int | None = None
        self._frame_size = (0, 0)
        self._storage_size = (0, 0)
        runtime = _runtime_directory()
        try:
            if os.name == "nt" and hasattr(os, "add_dll_directory"):
                self._dll_directory = os.add_dll_directory(str(runtime))
            self._api = ctypes.CDLL(str(runtime / "libass-9.dll"))
            _configure_api(self._api)
            self._library_handle = self._api.ass_library_init()
            if not self._library_handle:
                raise LibassUnavailable("libass could not create its library context")
            self._load_adjacent_fonts()
            subtitle_text = self.subtitle_path.read_text(encoding="utf-8-sig", errors="replace")
            subtitle_data = subtitle_text.encode("utf-8")
            subtitle_buffer = ctypes.create_string_buffer(subtitle_data)
            self._track_handle = self._api.ass_read_memory(
                self._library_handle,
                ctypes.cast(subtitle_buffer, ctypes.c_char_p),
                len(subtitle_data),
                b"UTF-8",
            )
            if not self._track_handle:
                raise ValueError("libass could not read this ASS/SSA subtitle track")
            self._renderer_handle = self._api.ass_renderer_init(self._library_handle)
            if not self._renderer_handle:
                raise LibassUnavailable("libass could not create its renderer")
            provider = (
                ASS_FONTPROVIDER_DIRECTWRITE
                if ASS_FONTPROVIDER_DIRECTWRITE in self.available_font_providers()
                else ASS_FONTPROVIDER_AUTODETECT
            )
            self._api.ass_set_fonts(self._renderer_handle, None, b"Arial", provider, None, 0)
        except Exception:
            self.close()
            raise

    @property
    def version(self) -> int:
        return int(self._api.ass_library_version())

    def available_font_providers(self) -> tuple[int, ...]:
        if not self._library_handle:
            return ()
        providers = ctypes.POINTER(ctypes.c_int)()
        size = ctypes.c_size_t()
        self._api.ass_get_available_font_providers(
            self._library_handle,
            ctypes.byref(providers),
            ctypes.byref(size),
        )
        if size.value == ctypes.c_size_t(-1).value or not providers:
            return ()
        return tuple(int(providers[index]) for index in range(size.value))

    def _load_adjacent_fonts(self) -> None:
        if not self._library_handle:
            return
        directories = [self.subtitle_path.parent]
        directories.extend(
            candidate
            for candidate in (self.subtitle_path.parent / "Fonts", self.subtitle_path.parent / "fonts")
            if candidate.is_dir()
        )
        fonts: dict[str, Path] = {}
        for directory in directories:
            for candidate in directory.iterdir():
                if candidate.is_file() and candidate.suffix.casefold() in FONT_EXTENSIONS:
                    fonts[str(candidate.resolve()).casefold()] = candidate
        for font in fonts.values():
            try:
                data = font.read_bytes()
                buffer = ctypes.create_string_buffer(data)
                self._api.ass_add_font(
                    self._library_handle,
                    font.name.encode("utf-8", errors="replace"),
                    ctypes.cast(buffer, ctypes.c_char_p),
                    len(data),
                )
            except OSError:
                continue

    def render(
        self,
        position_ms: int,
        width: int,
        height: int,
        storage_width: int | None = None,
        storage_height: int | None = None,
    ) -> AssRenderResult:
        if not self._renderer_handle or not self._track_handle:
            return AssRenderResult(False, None)
        width, height = max(1, int(width)), max(1, int(height))
        size_changed = self._frame_size != (width, height)
        if size_changed:
            self._frame_size = (width, height)
            self._api.ass_set_frame_size(self._renderer_handle, width, height)
        storage = (
            max(1, int(storage_width or width)),
            max(1, int(storage_height or height)),
        )
        storage_changed = self._storage_size != storage
        if storage_changed:
            self._storage_size = storage
            self._api.ass_set_storage_size(self._renderer_handle, storage[0], storage[1])
        changed = ctypes.c_int()
        images = self._api.ass_render_frame(
            self._renderer_handle,
            self._track_handle,
            max(0, int(position_ms)),
            ctypes.byref(changed),
        )
        if not size_changed and not storage_changed and not changed.value:
            return AssRenderResult(False, None)
        image_rows: list[tuple[int, int, int, int, int, bytes]] = []
        pointer = images
        while pointer:
            image = pointer.contents
            if image.w > 0 and image.h > 0 and image.bitmap:
                left = max(0, image.dst_x)
                top = max(0, image.dst_y)
                right = min(width, image.dst_x + image.w)
                bottom = min(height, image.dst_y + image.h)
                if right > left and bottom > top:
                    address = ctypes.addressof(image.bitmap.contents)
                    rows = b"".join(
                        ctypes.string_at(address + row * image.stride, image.w)
                        for row in range(image.h)
                    )
                    image_rows.append((image.dst_x, image.dst_y, image.w, image.h, int(image.color), rows))
            pointer = image.next
        if not image_rows:
            return AssRenderResult(True, None)
        min_x = max(0, min(row[0] for row in image_rows))
        min_y = max(0, min(row[1] for row in image_rows))
        max_x = min(width, max(row[0] + row[2] for row in image_rows))
        max_y = min(height, max(row[1] + row[3] for row in image_rows))
        canvas = Image.new("RGBA", (max_x - min_x, max_y - min_y), (0, 0, 0, 0))
        for dst_x, dst_y, glyph_width, glyph_height, color, rows in image_rows:
            mask = Image.frombytes("L", (glyph_width, glyph_height), rows)
            clip_left = max(0, -dst_x)
            clip_top = max(0, -dst_y)
            clip_right = min(glyph_width, width - dst_x)
            clip_bottom = min(glyph_height, height - dst_y)
            if (clip_left, clip_top, clip_right, clip_bottom) != (0, 0, glyph_width, glyph_height):
                mask = mask.crop((clip_left, clip_top, clip_right, clip_bottom))
            opacity = 255 - (color & 0xFF)
            if opacity != 255:
                mask = mask.point([round(value * opacity / 255) for value in range(256)])
            red = (color >> 24) & 0xFF
            green = (color >> 16) & 0xFF
            blue = (color >> 8) & 0xFF
            glyph = Image.new("RGBA", mask.size, (red, green, blue, 0))
            glyph.putalpha(mask)
            canvas.alpha_composite(
                glyph,
                (max(0, dst_x) - min_x, max(0, dst_y) - min_y),
            )
        return AssRenderResult(
            True,
            AssBitmap(min_x, min_y, canvas.width, canvas.height, canvas.tobytes("raw", "RGBA")),
        )

    def close(self) -> None:
        api = getattr(self, "_api", None)
        if api is not None and self._track_handle:
            api.ass_free_track(self._track_handle)
            self._track_handle = None
        if api is not None and self._renderer_handle:
            api.ass_renderer_done(self._renderer_handle)
            self._renderer_handle = None
        if api is not None and self._library_handle:
            api.ass_library_done(self._library_handle)
            self._library_handle = None
        if self._dll_directory is not None:
            self._dll_directory.close()
            self._dll_directory = None

    def __enter__(self) -> LibassRenderer:
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
