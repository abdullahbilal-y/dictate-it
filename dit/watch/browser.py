"""Active tab of the foreground browser (address + page title), read via Windows UI Automation.

No extension needed. Chromium browsers expose the omnibox as the first Edit control in the window; Firefox
as AutomationId "urlbar-input". The element is cached per window, so steady-state reads cost ~0.2ms
(first lookup ~10-30ms, ~800ms on the very first UIA call of the process). Must be used from one thread.

The page title comes from the selected TabItem in the tab strip, because the window title can't be trusted:
Edge Workspaces / named windows keep the window title fixed (e.g. just "Ibras95") on every tab. Reading the
tab strip costs ~80ms with ~75 tabs, so it only happens when the address changes."""
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlsplit

BROWSER_EXES = {"chrome.exe", "msedge.exe", "brave.exe", "firefox.exe", "opera.exe", "vivaldi.exe", "arc.exe"}
INTERNAL_SCHEMES = ("about:", "chrome:", "edge:", "brave:", "opera:", "vivaldi:", "file:", "view-source:")


@dataclass
class BrowserTab:
    url: Optional[str]
    title: Optional[str]


def clean_url(raw: str) -> Optional[str]:
    """scheme://host/path only. Query strings and fragments are dropped: they often carry tokens, emails or
    search terms, and the path alone is a stable identity for a page (doc IDs, repo/PR paths)."""
    raw = (raw or "").strip()
    if not raw or " " in raw:
        return None   # the user is typing a search into the bar, not looking at a page
    if raw.lower().startswith(INTERNAL_SCHEMES):
        return None
    if "://" not in raw:
        if "." not in raw.split("/")[0]:
            return None
        raw = "https://" + raw
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    path = parts.path.rstrip("/")
    return f"{parts.scheme}://{parts.hostname}{path}"


def site_of(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    host = urlsplit(url).hostname or ""
    return host[4:] if host.startswith("www.") else host


class BrowserUrlReader:
    def __init__(self):
        self._uia = None
        self._failed = False
        self._cache = {}          # hwnd -> value pattern
        self._last = {}           # hwnd -> (url, title): title is refreshed only when the url changes
        self._announced = set()

    def _init(self) -> bool:
        if self._uia is not None or self._failed:
            return not self._failed
        try:
            import comtypes
            import comtypes.client
            comtypes.CoInitialize()   # this (watcher) thread needs its own COM apartment
            comtypes.client.GetModule("UIAutomationCore.dll")
            from comtypes.gen import UIAutomationClient as UIA
            self._UIA = UIA
            self._uia = comtypes.client.CreateObject(UIA.CUIAutomation, interface=UIA.IUIAutomation)
            self._cond_edit = self._uia.CreatePropertyCondition(UIA.UIA_ControlTypePropertyId,
                                                                UIA.UIA_EditControlTypeId)
            self._cond_ff = self._uia.CreatePropertyCondition(UIA.UIA_AutomationIdPropertyId, "urlbar-input")
            self._cond_tab = self._uia.CreatePropertyCondition(UIA.UIA_ControlTypePropertyId,
                                                               UIA.UIA_TabItemControlTypeId)
            return True
        except Exception as e:
            # Fail loud once, then keep working with titles only.
            self._failed = True
            print(f"[Watcher] Browser tab reading unavailable ({e}); using window titles only. "
                  f"Install it with: pip install comtypes")
            return False

    def _find(self, hwnd, exe):
        UIA = self._UIA
        t0 = time.perf_counter()
        root = self._uia.ElementFromHandle(hwnd)
        edit = root.FindFirst(UIA.TreeScope_Descendants, self._cond_ff if exe == "firefox.exe" else self._cond_edit)
        if not edit:
            return None
        pattern = edit.GetCurrentPattern(UIA.UIA_ValuePatternId).QueryInterface(UIA.IUIAutomationValuePattern)
        if exe not in self._announced:
            self._announced.add(exe)
            print(f"[Watcher] Reading {exe} address bar via UI Automation "
                  f"(lookup {(time.perf_counter() - t0) * 1000:.0f}ms)")
        if len(self._cache) > 32:
            self._cache.clear()
            self._last.clear()
        self._cache[hwnd] = pattern
        return pattern

    def _selected_tab_title(self, hwnd) -> Optional[str]:
        UIA = self._UIA
        try:
            tabs = self._uia.ElementFromHandle(hwnd).FindAll(UIA.TreeScope_Descendants, self._cond_tab)
            for i in range(tabs.Length):
                tab = tabs.GetElement(i)
                if tab.GetCurrentPropertyValue(UIA.UIA_SelectionItemIsSelectedPropertyId):
                    name = (tab.CurrentName or "").strip()
                    return name or None
        except Exception:
            return None
        return None

    def read(self, hwnd, exe) -> Optional[BrowserTab]:
        if exe not in BROWSER_EXES or not self._init():
            return None
        for attempt in (0, 1):
            pattern = self._cache.get(hwnd) if attempt == 0 else None
            try:
                pattern = pattern or self._find(hwnd, exe)
                if pattern is None:
                    return None
                url = clean_url(pattern.CurrentValue)
                break
            except Exception:
                self._cache.pop(hwnd, None)   # stale element (tab strip rebuilt, window closed): look again
        else:
            return None
        last = self._last.get(hwnd)
        if last and last[0] == url:
            return BrowserTab(url, last[1])
        title = self._selected_tab_title(hwnd)
        self._last[hwnd] = (url, title)
        return BrowserTab(url, title)
