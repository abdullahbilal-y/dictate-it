"""Background thread sampling the foreground window once a second and feeding the sessionizer."""
import threading
import time
import traceback

from .browser import BrowserUrlReader
from .context import build_context
from .sessionizer import Sessionizer
from .window import foreground_window, idle_seconds, is_skippable

POLL_INTERVAL_S = 1.0


class ContextWatcher:
    def __init__(self, config, on_start, on_end, on_tick):
        self.config = config
        self.sessionizer = Sessionizer(config.settle_s, config.idle_after_s, on_start, on_end, on_tick)
        self._stop = threading.Event()
        self._thread = None
        self.paused = False
        self._error_counts = {}
        self.urls = BrowserUrlReader() if getattr(config, "read_browser_urls", True) else None

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ContextWatcher", daemon=True)
        self._thread.start()
        print(f"[Watcher] Watching foreground app + window title{' + browser URL' if self.urls else ''} "
              f"every {POLL_INTERVAL_S:.0f}s "
              f"(settle {self.config.settle_s}s, idle {self.config.idle_after_s}s)")

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self.sessionizer.flush()

    def set_paused(self, paused: bool):
        self.paused = paused
        if paused:
            self.sessionizer.flush()

    def _run(self):
        private = {e.lower() for e in self.config.private_apps}
        while not self._stop.wait(POLL_INTERVAL_S):
            if self.paused:
                continue
            try:
                now = time.time()
                win = foreground_window()
                ctx = None
                if win is not None and not is_skippable(win):
                    probe = build_context(win, private)
                    tab = None
                    if self.urls and not probe.private:   # never read addresses of private windows
                        tab = self.urls.read(win.hwnd, win.exe)
                    ctx = build_context(win, private, tab.url, tab.title) if tab else probe
                self.sessionizer.tick(ctx, idle_seconds(), now)
            except Exception as e:
                # Fail loud, but don't let one bad window title kill the watcher or flood the log.
                key = type(e).__name__
                self._error_counts[key] = self._error_counts.get(key, 0) + 1
                if self._error_counts[key] <= 3:
                    print(f"[Watcher] Error ({key} #{self._error_counts[key]}): {e}")
                    traceback.print_exc()
