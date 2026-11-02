import time
import threading
import keyboard
from .engine import DictationEngine
from .config import Config

class HotkeyListener:
    def __init__(self, engine: DictationEngine, config: Config):
        self.engine = engine
        self.config = config
        self.hotkey_str = config.hotkey.lower()
        self.mode = config.mode.lower()
        self._last_toggle_time = 0.0
        self._is_held = False
        self._lock = threading.Lock()

    def _on_toggle(self):
        now = time.time()
        # Debounce rapid key triggers (minimum 300ms between toggles)
        if now - self._last_toggle_time < 0.3:
            return
        self._last_toggle_time = now

        if self.engine.is_listening:
            self.engine.stop_dictation()
        else:
            self.engine.start_dictation()

    def _setup_toggle_mode(self):
        print(f"[Hotkey] Listening for global toggle hotkey: {self.hotkey_str.upper()} (^⇧D)")
        keyboard.add_hotkey(self.hotkey_str, self._on_toggle, suppress=False)

    def _setup_ptt_mode(self):
        print(f"[Hotkey] Listening for Push-To-Talk hotkey: Hold {self.hotkey_str.upper()} to speak, release to paste.")
        
        # Parse trigger key (usually last key in hotkey combo, e.g. 'd')
        parts = [p.strip() for p in self.hotkey_str.split("+")]
        main_key = parts[-1]
        modifier_keys = parts[:-1]

        def _on_key_event(event):
            if event.name.lower() != main_key:
                return

            # Check if all modifiers are pressed
            mods_pressed = all(keyboard.is_pressed(mod) for mod in modifier_keys)

            if event.event_type == keyboard.KEY_DOWN:
                if mods_pressed and not self._is_held:
                    self._is_held = True
                    self.engine.start_dictation()
            elif event.event_type == keyboard.KEY_UP:
                if self._is_held:
                    self._is_held = False
                    self.engine.stop_dictation()

        keyboard.hook(_on_key_event)

    def start(self):
        if self.mode == "ptt":
            self._setup_ptt_mode()
        else:
            self._setup_toggle_mode()

    def stop(self):
        try:
            keyboard.unhook_all()
        except Exception:
            pass
