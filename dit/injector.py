import time
import threading
import ctypes
from ctypes import wintypes
import pyperclip

# Windows Constants
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt
VK_LWIN = 0x5B
VK_V = 0x56

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

user32 = ctypes.windll.user32

class TextInjector:
    def __init__(self, mode: str = "clipboard", restore_clipboard: bool = False, restore_delay_ms: int = 1000):
        self.mode = mode
        self.restore_clipboard = restore_clipboard
        self.restore_delay_ms = restore_delay_ms

    def get_foreground_window(self):
        try:
            return user32.GetForegroundWindow()
        except Exception:
            return None

    def focus_window(self, hwnd):
        if hwnd and hwnd != 0:
            try:
                user32.SetForegroundWindow(hwnd)
                time.sleep(0.04)
            except Exception:
                pass

    def release_all_modifiers(self):
        """Ensure Shift, Ctrl, Alt, Win are fully released so shortcuts do not corrupt."""
        for vk in [VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN]:
            try:
                user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
            except Exception:
                pass
        time.sleep(0.04)

    def inject(self, text: str, target_hwnd=None):
        if not text:
            return

        # Restore target window focus if provided
        if target_hwnd:
            self.focus_window(target_hwnd)

        # Release any pressed modifiers from the user's hotkey
        self.release_all_modifiers()

        if self.mode == "clipboard":
            self._inject_via_clipboard(text)
        else:
            self._inject_via_unicode(text)

    def _inject_via_clipboard(self, text: str):
        old_clip = None
        if self.restore_clipboard:
            try:
                old_clip = pyperclip.paste()
            except Exception:
                old_clip = None

        try:
            pyperclip.copy(text)
        except Exception as e:
            print(f"[Injector] Clipboard write failed ({e}), falling back to direct typing.")
            self._inject_via_unicode(text)
            return

        # Wait for clipboard buffer to update
        time.sleep(0.05)

        # Send Native Windows Ctrl+V
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        time.sleep(0.01)
        user32.keybd_event(VK_V, 0, 0, 0)
        time.sleep(0.01)
        user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.01)
        user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)

        # Optional restore
        if self.restore_clipboard and old_clip is not None:
            def _restore():
                time.sleep(self.restore_delay_ms / 1000.0)
                try:
                    pyperclip.copy(old_clip)
                except Exception:
                    pass
            threading.Thread(target=_restore, daemon=True).start()

    def _inject_via_unicode(self, text: str):
        """Direct keystroke injection using Windows SendInput Unicode events."""
        for char in text:
            # Send unicode character
            code = ord(char)
            # KEYBDINPUT structure
            user32.keybd_event(0, code, KEYEVENTF_UNICODE, 0)
            user32.keybd_event(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0)
            time.sleep(0.001)
