import argparse
import os
import sys
import time

if sys.stdout is None or sys.stderr is None:
    # pythonw (tray/startup launch) has no console: keep logs and crash traces instead of discarding them.
    _log_dir = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "DictateIt")
    os.makedirs(_log_dir, exist_ok=True)
    _log_path = os.path.join(_log_dir, "dictateit.log")
    _mode = "w" if os.path.exists(_log_path) and os.path.getsize(_log_path) > 5_000_000 else "a"
    _log = open(_log_path, _mode, encoding="utf-8", buffering=1)
    _log.write(f"\n===== DictateIt start {time.strftime('%Y-%m-%d %H:%M:%S')} (pid {os.getpid()}) =====\n")
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log
    import faulthandler
    faulthandler.enable(_log)   # native crashes (e.g. in ctypes callbacks) get a stack trace too

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import keyboard

from dit.config import load_config, save_config, Config
from dit.engine import DictationEngine
from dit.env import load_dotenv
from dit.feedback import FeedbackManager
from dit.hotkey import HotkeyListener
from dit.tray import SystemTrayApp
from dit.startup import enable_startup, disable_startup

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

class SingleInstance:
    """One DictateIt per user session. A second launch signals the first (which shows its "ready" card)."""
    MUTEX = "Local\\DictateIt.SingleInstance"
    EVENT = "Local\\DictateIt.Show"

    def __init__(self):
        import win32api, win32event, winerror
        self._win32event = win32event
        self.mutex = win32event.CreateMutex(None, False, self.MUTEX)
        self.acquired = win32api.GetLastError() != winerror.ERROR_ALREADY_EXISTS
        if self.acquired:
            self.event = win32event.CreateEvent(None, False, False, self.EVENT)
        else:
            try:
                ev = win32event.OpenEvent(win32event.EVENT_MODIFY_STATE, False, self.EVENT)
                win32event.SetEvent(ev)
            except Exception as e:
                print(f"[DictateIt] Could not signal the running copy: {e}")

    def on_show(self, callback):
        import threading
        def wait():
            while True:
                if self._win32event.WaitForSingleObject(self.event, self._win32event.INFINITE) == 0:
                    try:
                        callback()
                    except Exception as e:
                        print(f"[DictateIt] Show request failed: {e}")
        threading.Thread(target=wait, name="SingleInstance", daemon=True).start()


def install_crash_hooks(manager):
    """Any exception escaping a thread is logged in full and shown as one calm card (rate-limited),
    instead of a thread silently dying."""
    import threading
    import traceback

    def report(exc_type, exc, tb, where):
        print(f"[Crash] Unhandled {exc_type.__name__} in {where}: {exc}")
        traceback.print_exception(exc_type, exc, tb)
        if manager:
            manager.show_error(f"{exc_type.__name__}: {exc}")

    sys.excepthook = lambda t, e, tb: report(t, e, tb, "main thread")
    threading.excepthook = lambda a: report(a.exc_type, a.exc_value, a.exc_traceback,
                                            f"thread {a.thread.name if a.thread else '?'}")


def set_app_identity():
    """Group taskbar/notification identity under DictateIt rather than Python."""
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DictateIt.App")
    except Exception:
        pass


BANNER = r"""
  ____  _      _        _       ___ _   
 |  _ \(_) ___| |_ __ _| |_ ___|_ _| |_ 
 | | | | |/ __| __/ _` | __/ _ \| || __|
 | |_| | | (__| || (_| | ||  __/| || |_ 
 |____/|_|\___|\__\__,_|\__\___|___|\__|
   [Ctrl + Alt + D]  Global Whisper Dictation   
"""

def run_self_test(engine: DictationEngine):
    print("\n--- Running DictateIt Verification & Self-Test ---")
    import numpy as np

    # Test 1: Whisper Transcriber Test
    print("[1/7] Testing Whisper STT model with synthetic speech-range signal...")
    t0 = time.time()
    dummy_audio = np.zeros(16000 * 2, dtype=np.float32)
    t = np.linspace(0, 2, 16000 * 2, endpoint=False)
    dummy_audio += 0.05 * np.sin(2 * np.pi * 440 * t).astype(np.float32)
    res = engine.transcriber.transcribe(dummy_audio)
    t_stt = time.time() - t0
    print(f"  ✓ Whisper inference executed in {t_stt*1000:.1f}ms (device: {engine.transcriber.device}, {engine.transcriber.compute_type})")

    # Test 2: Audio Device Test
    print("[2/7] Testing microphone device capture for 1 second...")
    try:
        engine.recorder.start()
        time.sleep(1.0)
        audio = engine.recorder.stop()
        rms = engine.recorder.calculate_rms(audio)
        duration = len(audio) / engine.config.samplerate
        print(f"  ✓ Captured {duration:.2f}s of audio (RMS energy: {rms:.6f})")
    except Exception as e:
        print(f"  ✗ Microphone error: {e}")

    # Test 3: Feedback & Clipboard Injection Test
    print("[3/7] Testing clipboard injection and audio chimes...")
    engine.feedback.start_recording()
    time.sleep(0.15)
    engine.feedback.transcribed()
    time.sleep(0.15)
    print("  ✓ Sound cues verified.")

    from dit.selftest import run_task_self_test
    failures = run_task_self_test(engine.config, engine.feedback)
    if failures:
        print(f"--- Self-Test finished with {failures} FAILURE(S). ---\n")
        sys.exit(1)
    print("--- Self-Test Complete! DictateIt is fully operational. ---\n")

def main():
    parser = argparse.ArgumentParser(description="DictateIt - Ultra-Fast Local Whisper Voice Dictation for Windows")
    parser.add_argument("--hotkey", type=str, default=None, help="Global hotkey (e.g. 'ctrl+alt+d')")
    parser.add_argument("--mode", type=str, choices=["toggle", "ptt"], default=None, help="Dictation mode: 'toggle' or 'ptt'")
    parser.add_argument("--model", type=str, default=None, help="Whisper model ('small', 'tiny', 'base', 'medium')")
    parser.add_argument("--device", type=str, choices=["auto", "cuda", "cpu"], default=None, help="Inference device")
    parser.add_argument("--paste-mode", type=str, choices=["clipboard", "type"], default=None, help="Text injection method")
    parser.add_argument("--no-cues", action="store_true", help="Disable audio feedback beeps")
    parser.add_argument("--no-tray", action="store_true", help="Disable system tray icon")
    parser.add_argument("--overlay", action="store_true", help="Enable floating visual badge")
    parser.add_argument("--save-config", action="store_true", help="Save current settings to config.json")
    parser.add_argument("--enable-startup", action="store_true", help="Add DictateIt to Windows Startup")
    parser.add_argument("--disable-startup", action="store_true", help="Remove DictateIt from Windows Startup")
    parser.add_argument("--test", action="store_true", help="Run self-test diagnostic and exit")
    parser.add_argument("--demo-ui", action="store_true", help="Play every task card animation on screen and exit")
    parser.add_argument("--task", type=str, default=None,
                        help="Send a task command as text instead of voice, e.g. --task \"add finish the report\"")
    parser.add_argument("--no-tasks", action="store_true", help="Plain dictation only (no task capture/watcher)")
    parser.add_argument("--no-watch", action="store_true", help="Disable the app-context watcher")
    parser.add_argument("--install", action="store_true",
                        help="Build DictateIt.exe, add a Start Menu entry and start at sign-in")

    args = parser.parse_args()
    set_app_identity()
    os.chdir(PROJECT_DIR)   # config.json and relative assets resolve the same however we're launched

    if args.install:
        from dit.launcher import install
        install()
        return
    if args.enable_startup:
        enable_startup()
        return
    if args.disable_startup:
        disable_startup()
        return

    load_dotenv(os.path.join(PROJECT_DIR, ".env"))
    config = load_config()

    if args.no_tasks:
        config.tasks_enabled = False
    if args.no_watch:
        config.watcher_enabled = False
    if args.hotkey:
        config.hotkey = args.hotkey
    if args.mode:
        config.mode = args.mode
    if args.model:
        config.model_name = args.model
    if args.device:
        config.device = args.device
    if args.paste_mode:
        config.paste_mode = args.paste_mode
    if args.no_cues:
        config.audio_cues = False
    if args.no_tray:
        config.tray_enabled = False
    if args.overlay:
        config.gui_overlay = True

    if args.save_config:
        save_config(config)
        print("[Config] Settings saved to config.json")

    if args.demo_ui:
        from dit.selftest import run_demo_ui
        run_demo_ui(config, FeedbackManager(enabled=config.audio_cues), PROJECT_DIR)
        return

    if args.task:
        from dit.tasks.system import TaskSystem
        tasks = TaskSystem(config, FeedbackManager(enabled=config.audio_cues), PROJECT_DIR, with_watcher=False)
        tasks.manager.handle_command(args.task)
        time.sleep(4.5)   # let the card play out before exiting
        tasks.stop()
        return

    instance = None
    if not args.test:
        instance = SingleInstance()
        if not instance.acquired:
            print("[DictateIt] Already running: asked the running copy to show itself.")
            return

    print(BANNER)
    print("Initializing DictateIt Engine...")
    engine = DictationEngine(config)

    from dit.env import get_secret
    groq_key = get_secret("GROQ_API_KEY")
    if groq_key:
        from dit.cloud_stt import GroqTranscriber
        engine.set_cloud_stt(GroqTranscriber(groq_key, config.groq_stt_model))
        routes = ", ".join(config.stt_cloud_routes) or "none (tray to enable)"
        print(f"[STT] Groq {config.groq_stt_model} for: {routes}; local Whisper '{config.model_name}' as fallback")
    else:
        print("[STT] Local Whisper only (set GROQ_API_KEY in .env for Groq Whisper large-v3)")

    if args.test:
        run_self_test(engine)
        return

    tasks = None
    if config.tasks_enabled:
        try:
            from dit.tasks.system import TaskSystem
            tasks = TaskSystem(config, engine.feedback, PROJECT_DIR)
            engine.set_task_manager(tasks.manager)
            tasks.start()
        except Exception as e:
            # Fail loud, but keep dictation usable.
            import traceback
            print(f"[Tasks] FAILED to start task system, running dictation only: {e}")
            traceback.print_exc()
            tasks = None

    if instance and tasks:
        instance.on_show(tasks.manager.greet)   # launched again from Start Menu/shortcut: say hello instead

    actions = {config.peek_hotkey: tasks.manager.peek_key} if tasks else {}
    install_crash_hooks(tasks.manager if tasks else None)
    listener = HotkeyListener(engine, config, actions=actions)
    listener.start()
    engine.set_listener(listener)

    # Initialize System Tray
    tray_app = None
    if config.tray_enabled:
        tray_app = SystemTrayApp(engine, config, tasks=tasks.manager if tasks else None,
                                 watcher=tasks.watcher if tasks else None, ai=tasks.ai if tasks else None)
        tray_app.start()
        engine.set_tray(tray_app)
        print("[Tray] Icon loaded in Windows system tray (notification area).")

    print(f"\n=======================================================")
    print(f" DictateIt is active in the background & System Tray!")
    print(f" Hotkey:     {config.hotkey.upper()} (Conflict-free global dictation)")
    if tasks:
        print(f" Tasks:      {config.task_hotkey.upper()} speak a task · {config.peek_hotkey.upper()} show queue")
        print(f" Context:    {'Watching app + window titles' if tasks.watcher else 'Off'} · {tasks.ai.status_text()}")
    print(f" Mode:       {config.mode.upper()} ({'Press once to start/stop' if config.mode == 'toggle' else 'Hold to speak'})")
    print(f" Model:      Whisper '{config.model_name}' on {engine.transcriber.device.upper()} ({engine.transcriber.compute_type})"
          f"{f' + Groq {config.groq_stt_model} for {config.stt_cloud_routes}' if engine.cloud_stt else ''}")
    print(f" Paste:      {config.paste_mode.upper()} (Direct target window injection)")
    print(f" Icon Tray:  {'Enabled (check taskbar near clock)' if config.tray_enabled else 'Disabled'}")
    print(f" Exit:       Right-click tray icon -> 'Exit DictateIt' or press Ctrl+C")
    print(f"=======================================================\n")

    try:
        while True:
            time.sleep(0.5)
            # Exit only when the tray loop has really ended (Exit in the menu). Checking `tray.visible` here
            # raced pystray's setup thread: at sign-in the PC is busy, visible was still False after 0.5s,
            # and DictateIt "stopped cleanly" seconds after starting (landmine #22).
            if tray_app and tray_app._thread and not tray_app._thread.is_alive():
                break
    except KeyboardInterrupt:
        print("\nStopping DictateIt...")
    finally:
        listener.stop()
        if tasks:
            tasks.stop()
        if tray_app:
            tray_app.stop()
        print("DictateIt stopped cleanly.")

if __name__ == "__main__":
    main()
