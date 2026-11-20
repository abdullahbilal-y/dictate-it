"""Per-pixel-alpha layered popup window (UpdateLayeredWindow) that never takes keyboard focus.

Must be created and pumped on one dedicated thread. Fully transparent pixels are click-through."""
import ctypes
from ctypes import wintypes

import numpy as np

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shcore = None
try:
    shcore = ctypes.WinDLL("shcore")
    shcore.GetDpiForMonitor.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.POINTER(wintypes.UINT),
                                        ctypes.POINTER(wintypes.UINT)]
except OSError:
    pass

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WM_MOUSEACTIVATE = 0x0021
WM_SETCURSOR = 0x0020
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MA_NOACTIVATE = 3
PM_REMOVE = 0x0001
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
ULW_ALPHA = 0x02
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
DIB_RGB_COLORS = 0
HWND_TOPMOST = wintypes.HWND(-1)
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
IDC_ARROW, IDC_HAND = 32512, 32649
MONITOR_DEFAULTTOPRIMARY = 1
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]


user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.RegisterClassExW.restype = wintypes.ATOM
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                   wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.POINTER(POINT), ctypes.POINTER(SIZE),
                                       wintypes.HDC, ctypes.POINTER(POINT), wintypes.COLORREF,
                                       ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, wintypes.UINT]
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT,
                                wintypes.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, wintypes.LPVOID]
user32.LoadCursorW.restype = wintypes.HANDLE
user32.SetCursor.argtypes = [wintypes.HANDLE]
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HANDLE
user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
user32.DestroyWindow.argtypes = [wintypes.HWND]
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
try:
    user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
except AttributeError:
    pass


def make_thread_dpi_aware() -> None:
    """Per-monitor DPI awareness for this thread only, so cards are crisp without touching tray/tkinter."""
    try:
        user32.SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
    except Exception as e:
        print(f"[UI] Could not set per-thread DPI awareness ({e}); cards may be blurry on scaled displays.")


def target_monitor():
    """(work_rect, dpi) for the monitor the user is looking at (the foreground window's monitor)."""
    hmon = user32.MonitorFromWindow(user32.GetForegroundWindow(), MONITOR_DEFAULTTOPRIMARY)
    info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    user32.GetMonitorInfoW(hmon, ctypes.byref(info))
    dpi = 96
    if shcore is not None:
        dx, dy = wintypes.UINT(96), wintypes.UINT(96)
        if shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dx), ctypes.byref(dy)) == 0:
            dpi = dx.value
    r = info.rcWork
    return (r.left, r.top, r.right, r.bottom), dpi


def cursor_pos():
    p = POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def premultiplied_bgra(img) -> bytes:
    a = np.asarray(img, dtype=np.uint8)
    alpha = a[..., 3:4].astype(np.uint16)
    rgb = (a[..., :3].astype(np.uint16) * alpha + 127) // 255
    out = np.empty_like(a)
    out[..., 0] = rgb[..., 2]
    out[..., 1] = rgb[..., 1]
    out[..., 2] = rgb[..., 0]
    out[..., 3] = a[..., 3]
    return out.tobytes()


class LayeredWindow:
    _class_registered = False
    CLASS_NAME = "DictateItTaskCards"

    def __init__(self, title: str, on_click):
        self.on_click = on_click
        self.hand_cursor = False
        self.visible = False
        self._hinst = kernel32.GetModuleHandleW(None)
        self._wndproc = WNDPROC(self._proc)   # keep a reference or Windows calls freed memory
        self._cursor_arrow = user32.LoadCursorW(None, ctypes.c_void_p(IDC_ARROW))
        self._cursor_hand = user32.LoadCursorW(None, ctypes.c_void_p(IDC_HAND))
        wc = WNDCLASSEXW(cbSize=ctypes.sizeof(WNDCLASSEXW), lpfnWndProc=self._wndproc, hInstance=self._hinst,
                         hCursor=self._cursor_arrow, lpszClassName=self.CLASS_NAME)
        if not user32.RegisterClassExW(ctypes.byref(wc)):
            raise ctypes.WinError(ctypes.get_last_error())
        ex = WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        self.hwnd = user32.CreateWindowExW(ex, self.CLASS_NAME, title, WS_POPUP, 0, 0, 1, 1,
                                           None, None, self._hinst, None)
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        self._screen_dc = user32.GetDC(None)
        self._mem_dc = gdi32.CreateCompatibleDC(self._screen_dc)
        self._bitmap = None
        self._bits = ctypes.c_void_p()
        self._size = (0, 0)
        self.pos = (0, 0)

    def _proc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_MOUSEACTIVATE:
                return MA_NOACTIVATE   # clicking a card must never steal focus from the user's app
            if msg == WM_SETCURSOR:
                user32.SetCursor(self._cursor_hand if self.hand_cursor else self._cursor_arrow)
                return 1
            if msg == WM_LBUTTONUP:
                x = ctypes.c_short(lparam & 0xFFFF).value
                y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
                self.on_click(x, y)
                return 0
        except Exception as e:
            print(f"[UI] Window proc error: {e}")
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _ensure_bitmap(self, w: int, h: int):
        if self._size == (w, h) and self._bitmap:
            return
        if self._bitmap:
            gdi32.DeleteObject(self._bitmap)
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h   # top-down rows, same order as numpy
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        self._bitmap = gdi32.CreateDIBSection(self._screen_dc, ctypes.byref(bmi), DIB_RGB_COLORS,
                                              ctypes.byref(self._bits), None, 0)
        if not self._bitmap:
            raise ctypes.WinError(ctypes.get_last_error())
        gdi32.SelectObject(self._mem_dc, self._bitmap)
        self._size = (w, h)

    def present(self, img, x: int, y: int) -> None:
        w, h = img.size
        self._ensure_bitmap(w, h)
        data = premultiplied_bgra(img)
        ctypes.memmove(self._bits, data, len(data))
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        dst, size, src = POINT(x, y), SIZE(w, h), POINT(0, 0)
        if not user32.UpdateLayeredWindow(self.hwnd, self._screen_dc, ctypes.byref(dst), ctypes.byref(size),
                                          self._mem_dc, ctypes.byref(src), 0, ctypes.byref(blend), ULW_ALPHA):
            raise ctypes.WinError(ctypes.get_last_error())
        self.pos = (x, y)
        if not self.visible:
            user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
            user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            self.visible = True

    def hide(self) -> None:
        if self.visible:
            user32.ShowWindow(self.hwnd, SW_HIDE)
            self.visible = False

    def pump(self) -> None:
        msg = wintypes.MSG()
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def destroy(self) -> None:
        if self._bitmap:
            gdi32.DeleteObject(self._bitmap)
        gdi32.DeleteDC(self._mem_dc)
        user32.ReleaseDC(None, self._screen_dc)
        user32.DestroyWindow(self.hwnd)
