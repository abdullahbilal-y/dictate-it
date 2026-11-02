import threading
import time
from PIL import Image, ImageDraw
import pystray

def create_circle_icon(color: tuple, accent_symbol: str = "mic"):
    width, height = 64, 64
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Outer circle
    draw.ellipse([4, 4, 60, 60], fill=color)

    if accent_symbol == "mic":
        # White microphone shape
        draw.rounded_rectangle([25, 14, 39, 36], radius=7, fill=(255, 255, 255))
        draw.arc([19, 22, 45, 42], start=0, end=180, fill=(255, 255, 255), width=3)
        draw.line([32, 42, 32, 50], fill=(255, 255, 255), width=3)
        draw.line([24, 50, 40, 50], fill=(255, 255, 255), width=3)
    elif accent_symbol == "rec":
        # Recording inner circle
        draw.ellipse([18, 18, 46, 46], fill=(255, 255, 255))
    elif accent_symbol == "busy":
        # Transcribing star/lightning
        draw.polygon([(32, 12), (24, 32), (32, 32), (28, 52), (40, 28), (32, 28)], fill=(255, 255, 255))

    return image

class SystemTrayApp:
    def __init__(self, engine, config):
        self.engine = engine
        self.config = config
        
        self.icon_idle = create_circle_icon((41, 128, 185), "mic")       # Blue
        self.icon_rec = create_circle_icon((231, 76, 60), "rec")         # Red
        self.icon_busy = create_circle_icon((243, 156, 18), "busy")      # Orange

        self.tray = None
        self._thread = None
        self.status_text = "Ready (^Shift+D)"

    def _build_menu(self):
        def _toggle_dictation(icon, item):
            if self.engine.is_listening:
                self.engine.stop_dictation()
            else:
                self.engine.start_dictation()

        def _set_mode(mode_val):
            def handler(icon, item):
                self.config.mode = mode_val
                if self.engine.listener:
                    self.engine.listener.stop()
                    self.engine.listener.mode = mode_val
                    self.engine.listener.start()
                self._refresh_menu()
            return handler

        def _toggle_cues(icon, item):
            self.config.audio_cues = not self.config.audio_cues
            self.engine.feedback.enabled = self.config.audio_cues
            self._refresh_menu()

        def _quit_app(icon, item):
            if self.engine.listener:
                self.engine.listener.stop()
            self.tray.stop()

        menu_items = [
            pystray.MenuItem("D^it - Dictate It", None, enabled=False),
            pystray.MenuItem(lambda text: f"Status: {self.status_text}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "🎙️ Start / Stop Dictation (^Shift+D)",
                _toggle_dictation,
                default=True
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Mode: Toggle",
                _set_mode("toggle"),
                checked=lambda item: self.config.mode == "toggle"
            ),
            pystray.MenuItem(
                "Mode: Push-to-Talk",
                _set_mode("ptt"),
                checked=lambda item: self.config.mode == "ptt"
            ),
            pystray.MenuItem(
                "Sound Cues",
                _toggle_cues,
                checked=lambda item: self.config.audio_cues
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit D^it", _quit_app)
        ]
        return pystray.Menu(*menu_items)

    def _refresh_menu(self):
        if self.tray:
            self.tray.menu = self._build_menu()

    def set_idle(self):
        self.status_text = "Ready (^Shift+D)"
        if self.tray:
            self.tray.icon = self.icon_idle
            self.tray.title = f"D^it: {self.status_text}"

    def set_recording(self):
        self.status_text = "Listening... Speak now"
        if self.tray:
            self.tray.icon = self.icon_rec
            self.tray.title = f"D^it: {self.status_text}"

    def set_transcribing(self):
        self.status_text = "Transcribing with Whisper..."
        if self.tray:
            self.tray.icon = self.icon_busy
            self.tray.title = f"D^it: {self.status_text}"

    def start(self):
        self.tray = pystray.Icon(
            "DitTray",
            self.icon_idle,
            f"D^it: {self.status_text}",
            self._build_menu()
        )
        self._thread = threading.Thread(target=self.tray.run, daemon=True)
        self._thread.start()

    def stop(self):
        if self.tray:
            self.tray.stop()
