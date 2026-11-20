"""Screen-reader support. Layered cards are invisible to UI Automation, so when Windows reports a screen
reader is running, card text is spoken via SAPI instead (queued, never interrupting)."""
import queue
import threading


class Announcer:
    def __init__(self):
        self._queue = queue.Queue()
        self._thread = None

    def say(self, text: str) -> None:
        if not text:
            return
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="Announcer", daemon=True)
            self._thread.start()
        self._queue.put(text)

    def _run(self):
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            voice = win32com.client.Dispatch("SAPI.SpVoice")
        except Exception as e:
            print(f"[UI] Screen-reader announcements unavailable: {e}")
            return
        while True:
            text = self._queue.get()
            try:
                voice.Speak(text, 1)  # SVSFlagsAsync
            except Exception as e:
                print(f"[UI] Announcement failed: {e}")
