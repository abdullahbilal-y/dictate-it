"""Foreground-window metadata via Win32. Reads app name + window title only: no screenshots, no content."""
import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass
from typing import Optional

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.GetTickCount.restype = wintypes.DWORD

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# Shell surfaces that take focus but aren't "work": desktop, taskbar, Start, Alt-Tab, notification center.
SKIP_CLASSES = {
    "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman", "WorkerW", "Windows.UI.Core.CoreWindow",
    "ForegroundStaging", "MultitaskingViewFrame", "XamlExplorerHostIslandWindow", "TaskListThumbnailWnd",
    "NotifyIconOverflowWindow", "TopLevelWindowForOverflowXamlIsland", "#32768",
}
SKIP_EXES = {"lockapp.exe", "searchhost.exe", "startmenuexperiencehost.exe", "shellexperiencehost.exe",
             "searchapp.exe"}


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


@dataclass
class WindowInfo:
    hwnd: int
    pid: int
    exe: str          # lowercase basename, e.g. "chrome.exe"
    exe_path: str
    title: str
    cls: str


_exe_cache = {}


def _exe_for_pid(pid: int):
    cached = _exe_cache.get(pid)
    if cached:
        return cached
    path = ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if handle:
        try:
            size = wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                path = buf.value
        finally:
            kernel32.CloseHandle(handle)
    result = (os.path.basename(path).lower(), path)
    if len(_exe_cache) > 512:
        _exe_cache.clear()
    _exe_cache[pid] = result
    return result


def foreground_window() -> Optional[WindowInfo]:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    cls_buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls_buf, 256)
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    exe, exe_path = _exe_for_pid(pid.value)
    return WindowInfo(hwnd=hwnd, pid=pid.value, exe=exe, exe_path=exe_path, title=buf.value, cls=cls_buf.value)


def is_skippable(win: WindowInfo) -> bool:
    return (win.pid == os.getpid() or win.cls in SKIP_CLASSES or win.exe in SKIP_EXES
            or not win.title.strip())


def idle_seconds() -> float:
    info = LASTINPUTINFO(cbSize=ctypes.sizeof(LASTINPUTINFO))
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return ((kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0


# SHQueryUserNotificationState: Windows' own "should apps interrupt now?" signal.
QUNS_NOT_PRESENT, QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE = 1, 2, 3, 4
QUNS_ACCEPTS_NOTIFICATIONS, QUNS_QUIET_TIME, QUNS_APP = 5, 6, 7


def notifications_welcome() -> bool:
    """False during full-screen apps/games, presentations and Focus/quiet time: hold back nudges then."""
    state = ctypes.c_int(0)
    try:
        if shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return True
    except Exception:
        return True
    return state.value in (QUNS_ACCEPTS_NOTIFICATIONS, 0)
