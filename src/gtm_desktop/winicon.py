"""PIL image -> Win32 HICON (32 bpp, per-pixel alpha). Windows only; shared by the tray and window captions."""

from __future__ import annotations

import ctypes
import sys

from PIL import Image

if sys.platform != "win32":  # pragma: no cover - imported only on Windows
    raise ImportError("winicon is Windows-only")

from ctypes import wintypes as wt  # noqa: E402

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

SM_CXICON, SM_CXSMICON = 11, 49
WM_SETICON, ICON_SMALL, ICON_BIG = 0x0080, 0, 1


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wt.BOOL), ("xHotspot", wt.DWORD), ("yHotspot", wt.DWORD),
                ("hbmMask", wt.HBITMAP), ("hbmColor", wt.HBITMAP)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


def _sig(fn, restype, *argtypes):
    fn.restype, fn.argtypes = restype, list(argtypes)


_sig(_user32.GetSystemMetrics, ctypes.c_int, ctypes.c_int)
_sig(_user32.CreateIconIndirect, wt.HICON, ctypes.POINTER(ICONINFO))
_sig(_user32.DestroyIcon, wt.BOOL, wt.HICON)
_sig(_user32.SendMessageW, ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
_sig(_gdi32.CreateDIBSection, wt.HBITMAP, wt.HDC, ctypes.c_void_p, wt.UINT, ctypes.POINTER(ctypes.c_void_p),
     wt.HANDLE, wt.DWORD)
_sig(_gdi32.CreateBitmap, wt.HBITMAP, ctypes.c_int, ctypes.c_int, wt.UINT, wt.UINT, ctypes.c_void_p)
_sig(_gdi32.DeleteObject, wt.BOOL, wt.HGDIOBJ)


def win_error(what: str) -> OSError:
    err = ctypes.get_last_error()
    return OSError(err, f"{what} failed: {ctypes.FormatError(err).strip()} (winerror {err})")


def small_icon_size() -> int:
    return _user32.GetSystemMetrics(SM_CXSMICON) or 16


def hicon(image: Image.Image, size: int | None = None) -> int:
    """HICON at `size` px (default: the small-icon size for this DPI). The caller owns it: DestroyIcon."""
    size = size or small_icon_size()
    img = image.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
    header = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=size, biHeight=-size,
                              biPlanes=1, biBitCount=32, biCompression=0)  # top-down BI_RGB
    bits = ctypes.c_void_p()
    color = _gdi32.CreateDIBSection(None, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
    if not color:
        raise win_error("CreateDIBSection")
    mask = _gdi32.CreateBitmap(size, size, 1, 1, None)
    try:
        data = img.tobytes("raw", "BGRA")
        ctypes.memmove(bits, data, len(data))
        info = ICONINFO(fIcon=True, hbmMask=mask, hbmColor=color)
        handle = _user32.CreateIconIndirect(ctypes.byref(info))
        if not handle:
            raise win_error("CreateIconIndirect")
        return handle
    finally:  # the icon keeps its own copies of both bitmaps
        if mask:
            _gdi32.DeleteObject(mask)
        _gdi32.DeleteObject(color)


def destroy(handle: int | None) -> None:
    if handle:
        _user32.DestroyIcon(handle)


def set_caption_icon(hwnd: int, image: Image.Image) -> int:
    """Set a window's small (title bar) icon. Returns the HICON, which must outlive the window's use of it."""
    handle = hicon(image)
    _user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, handle)
    return handle
