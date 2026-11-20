"""Global hotkeys, built on raw key-down/key-up events so holding a key behaves like people expect.

* Auto-repeat is ignored: holding a hotkey fires it once (holding Ctrl+Alt+Q used to toggle the queue ~30x/s).
* Recording keys (dictate, task): tap = toggle (tap again to stop); hold = push-to-talk (release stops).
  In "ptt" mode release always stops.
* Action keys (queue peek): tap = toggle; hold = show while held, hide on release.
* Esc while listening cancels the recording; nothing is pasted or queued.
* Callbacks run on one worker thread, never on the keyboard hook thread (a slow hook lags typing everywhere).
"""
import queue
import threading
import time
import traceback

import keyboard

from .engine import DictationEngine
from .config import Config

HOLD_S = 0.4              # pressed longer than this = a hold, not a tap
STALE_DOWN_S = 0.6        # no repeat for this long + another key-down = we missed the key-up (e.g. UAC prompt)


class Binding:
    def __init__(self, hotkey: str, on_press, on_release):
        parts = [p.strip().lower() for p in hotkey.split("+") if p.strip()]
        self.hotkey = hotkey.lower()
        self.key = parts[-1]
        self.mods = parts[:-1]
        self.on_press = on_press
        self.on_release = on_release
        self.down_at = None
        self.last_seen = 0.0


class HotkeyListener:
    def __init__(self, engine: DictationEngine, config: Config, actions=None):
        self.engine = engine
        self.config = config
        self.hotkey_str = config.hotkey.lower()
        self.mode = config.mode.lower()
        self.actions = actions or {}   # hotkey -> callable(event) with event in ("press", "release", held_s)
        self._jobs = queue.Queue()
        self._worker = threading.Thread(target=self._work, name="HotkeyActions", daemon=True)
        self._worker.start()
        self._bindings = []
        self._hook = None
        self._lock = threading.Lock()
        self._started_by = None    # which recording binding started the current recording (for hold-to-talk)

    # ------------------------------------------------------------------ bindings
    def _build(self):
        bindings = [self._record_binding(self.hotkey_str, "dictate")]
        if self.engine.task_manager and self.config.task_hotkey:
            bindings.append(self._record_binding(self.config.task_hotkey, "task"))
        for hotkey, fn in self.actions.items():
            if hotkey:
                bindings.append(Binding(hotkey, lambda fn=fn: fn("press"), lambda held, fn=fn: fn(("release", held))))
        return bindings

    def _record_binding(self, hotkey, route):
        def press():
            if self.engine.is_listening:
                self._started_by = None
                self.engine.stop_dictation()           # a tap while recording = stop
            else:
                self._started_by = route
                self.engine.start_dictation(route)

        def release(held):
            if self._started_by != route or not self.engine.is_listening:
                return
            if self.mode == "ptt" or held >= HOLD_S:   # it was held: push-to-talk, so release stops
                self._started_by = None
                self.engine.stop_dictation()
        return Binding(hotkey, press, release)

    # ------------------------------------------------------------------ event handling (hook thread: keep fast)
    def process(self, name: str, is_down: bool, now: float, mods_ok) -> None:
        """Pure state machine, separated from the keyboard library so it can be tested."""
        name = (name or "").lower()
        if is_down and name == "esc":
            # Decide in the worker, in order with the start/stop jobs queued before it (checking is_listening
            # here would miss an Esc pressed right after a start). Esc still reaches the focused app.
            self._jobs.put((self._cancel_if_listening, ()))
            return
        for b in self._bindings:
            if name != b.key:
                continue
            if is_down:
                if b.down_at is not None and now - b.last_seen < STALE_DOWN_S:
                    b.last_seen = now                  # auto-repeat while held: ignore
                    continue
                if not mods_ok(b.mods):
                    continue
                b.down_at = b.last_seen = now
                self._jobs.put((b.on_press, ()))
            elif b.down_at is not None:
                held = now - b.down_at
                b.down_at = None
                self._jobs.put((b.on_release, (held,)))

    def _cancel_if_listening(self):
        if self.engine.is_listening:
            self._started_by = None
            self.engine.cancel_dictation()

    def _on_event(self, event):
        try:
            mods_ok = lambda mods: all(keyboard.is_pressed(m) for m in mods)
            self.process(event.name, event.event_type == keyboard.KEY_DOWN, time.time(), mods_ok)
        except Exception as e:   # never let an exception escape into the keyboard hook
            print(f"[Hotkey] Event error: {e}")

    def _work(self):
        while True:
            fn, args = self._jobs.get()
            try:
                fn(*args)
            except Exception as e:
                print(f"[Hotkey] Action failed: {e}")
                traceback.print_exc()
            finally:
                self._jobs.task_done()

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        with self._lock:
            self._bindings = self._build()
            for b in self._bindings:
                print(f"[Hotkey] {b.hotkey.upper()} (tap or hold)")
            try:
                self._hook = keyboard.hook(self._on_event)
            except Exception as e:
                print(f"[Hotkey] FAILED to install keyboard hook: {e}")
                traceback.print_exc()

    def stop(self):
        with self._lock:
            try:
                keyboard.unhook_all()
            except Exception:
                pass
            self._hook = None

    def update_hotkey(self, new_hotkey_str: str):
        self.stop()
        self.hotkey_str = new_hotkey_str.lower()
        self.config.hotkey = self.hotkey_str
        self.start()
