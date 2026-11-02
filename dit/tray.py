import threading
import time
from PIL import Image, ImageDraw
import pystray
from .config import save_config
from .startup import is_startup_enabled, enable_startup, disable_startup

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

HOTKEY_PRESETS = [
    ("Ctrl + Alt + D (Recommended - Conflict Free)", "ctrl+alt+d"),
    ("Ctrl + Alt + Space (Thumb Friendly)", "ctrl+alt+space"),
    ("F8 (Single Key)", "f8"),
    ("Alt + \\ (Symbol Key)", "alt+\\"),
    ("Ctrl + Shift + D (Legacy)", "ctrl+shift+d"),
]

class SystemTrayApp:
    def __init__(self, engine, config):
        self.engine = engine
        self.config = config
        
        self.icon_idle = create_circle_icon((41, 128, 185), "mic")       # Blue
        self.icon_rec = create_circle_icon((231, 76, 60), "rec")         # Red
        self.icon_busy = create_circle_icon((243, 156, 18), "busy")      # Orange

        self.tray = None
        self._thread = None
        self.status_text = f"Ready ({self.config.hotkey.upper()})"

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
                save_config(self.config)
                self._refresh_menu()
            return handler

        def _set_hotkey(hotkey_val):
            def handler(icon, item):
                self.config.hotkey = hotkey_val
                if self.engine.listener:
                    self.engine.listener.update_hotkey(hotkey_val)
                save_config(self.config)
                self.set_idle()
                self._refresh_menu()
            return handler

        def _toggle_cues(icon, item):
            self.config.audio_cues = not self.config.audio_cues
            self.engine.feedback.enabled = self.config.audio_cues
            save_config(self.config)
            self._refresh_menu()

        def _toggle_startup(icon, item):
            if is_startup_enabled():
                disable_startup()
            else:
                enable_startup()
            self._refresh_menu()

        def _quit_app(icon, item):
            if self.engine.listener:
                self.engine.listener.stop()
            self.tray.stop()

        # Build Hotkey Submenu
        hotkey_menu_items = [
            pystray.MenuItem(
                label,
                _set_hotkey(key_code),
                checked=lambda item, kc=key_code: self.config.hotkey.lower() == kc.lower()
            )
            for label, key_code in HOTKEY_PRESETS
        ]
        hotkey_submenu = pystray.Menu(*hotkey_menu_items)

        menu_items = [
            pystray.MenuItem("D^it - Dictate It", None, enabled=False),
            pystray.MenuItem(lambda text: f"Status: {self.status_text}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda text: f"🎙️ Start / Stop Dictation ({self.config.hotkey.upper()})",
                _toggle_dictation,
                default=True
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Shortcut Key", hotkey_submenu),
            pystray.MenuItem(
                "Mode: Toggle (Press to start/stop)",
                _set_mode("toggle"),
                checked=lambda item: self.config.mode == "toggle"
            ),
            pystray.MenuItem(
                "Mode: Push-to-Talk (Hold while speaking)",
                _set_mode("ptt"),
                checked=lambda item: self.config.mode == "ptt"
            ),
            pystray.MenuItem(
                "Sound Cues",
                _toggle_cues,
                checked=lambda item: self.config.audio_cues
            ),
            pystray.MenuItem(
                "Start with Windows",
                _toggle_startup,
                checked=lambda item: is_startup_enabled()
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit D^it", _quit_app)
        ]
        return pystray.Menu(*menu_items)

    def _refresh_menu(self):
        if self.tray:
            self.tray.menu = self._build_menu()

    def set_idle(self):
        self.status_text = f"Ready ({self.config.hotkey.upper()})"
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
