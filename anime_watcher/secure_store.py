from __future__ import annotations

import base64
import ctypes
import sys
from ctypes import wintypes


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[_DataBlob, object]:
    buffer = ctypes.create_string_buffer(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def protect_secret(value: str) -> str:
    """Protect a secret for the current Windows account using DPAPI."""
    if not value:
        return ""
    if sys.platform != "win32":
        raise RuntimeError("Secure token storage currently requires Windows")
    source, keepalive = _blob(value.encode("utf-8"))
    output = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    description = "Anime Watcher AniList token"
    if not crypt32.CryptProtectData(ctypes.byref(source), description, None, None, None, 0, ctypes.byref(output)):
        raise ctypes.WinError()
    try:
        encrypted = ctypes.string_at(output.pbData, output.cbData)
        return base64.b64encode(encrypted).decode("ascii")
    finally:
        kernel32.LocalFree(output.pbData)
        del keepalive


def unprotect_secret(value: str) -> str:
    if not value:
        return ""
    if sys.platform != "win32":
        raise RuntimeError("Secure token storage currently requires Windows")
    source_bytes = base64.b64decode(value.encode("ascii"), validate=True)
    source, keepalive = _blob(source_bytes)
    output = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData).decode("utf-8")
    finally:
        kernel32.LocalFree(output.pbData)
        del keepalive
