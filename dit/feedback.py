import threading
import time

try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False

def _play_pattern(pattern):
    if not HAS_WINSOUND:
        return
    try:
        for item in pattern:
            if isinstance(item, tuple):
                freq, dur = item
                winsound.Beep(freq, dur)
            elif isinstance(item, (int, float)):
                time.sleep(item)
    except Exception:
        pass

class FeedbackManager:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def _async_beep(self, pattern):
        if not self.enabled:
            return
        threading.Thread(target=_play_pattern, args=(pattern,), daemon=True).start()

    def start_recording(self):
        """Rising chirp indicating microphone is hot."""
        self._async_beep([(650, 45), (950, 60)])

    def end_recording(self):
        """Soft click acknowledging recording stopped."""
        self._async_beep([(800, 35)])

    def transcribed(self):
        """Pleasant confirmation chime indicating text was typed/pasted."""
        self._async_beep([(880, 50), (1320, 75)])

    def empty_or_silence(self):
        """Low double-tap indicating silence/no speech heard."""
        self._async_beep([(350, 40), 0.05, (300, 40)])

    def error(self):
        """Low buzz indicating an issue."""
        self._async_beep([(250, 150)])
