import time
import threading
import pyperclip
import keyboard

class TextInjector:
    def __init__(self, mode: str = "clipboard", restore_clipboard: bool = True, restore_delay_ms: int = 300):
        self.mode = mode
        self.restore_clipboard = restore_clipboard
        self.restore_delay_ms = restore_delay_ms

    def inject(self, text: str):
        if not text:
            return

        # Ensure active hotkey modifiers are released to avoid shortcut collision
        self._release_modifiers()

        if self.mode == "clipboard":
            self._inject_via_clipboard(text)
        else:
            self._inject_via_typing(text)

    def _release_modifiers(self):
        for mod in ["shift", "ctrl", "alt"]:
            try:
                keyboard.release(mod)
            except Exception:
                pass
        time.sleep(0.04)

    def _inject_via_clipboard(self, text: str):
        # Save previous clipboard
        old_clip = None
        if self.restore_clipboard:
            try:
                old_clip = pyperclip.paste()
            except Exception:
                old_clip = None

        # Copy text to clipboard
        try:
            pyperclip.copy(text)
        except Exception as e:
            print(f"[Injector] Clipboard copy failed: {e}, falling back to keyboard type.")
            self._inject_via_typing(text)
            return

        time.sleep(0.03)

        # Trigger paste
        try:
            keyboard.send("ctrl+v")
        except Exception:
            # Fallback direct key combinations
            keyboard.press("ctrl")
            keyboard.send("v")
            keyboard.release("ctrl")

        # Asynchronously restore previous clipboard if requested
        if self.restore_clipboard and old_clip is not None:
            def _restore():
                time.sleep(self.restore_delay_ms / 1000.0)
                try:
                    pyperclip.copy(old_clip)
                except Exception:
                    pass
            threading.Thread(target=_restore, daemon=True).start()

    def _inject_via_typing(self, text: str):
        try:
            keyboard.write(text, delay=0.002)
        except Exception as e:
            print(f"[Injector] Typing failed: {e}")
