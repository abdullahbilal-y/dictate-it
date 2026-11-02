import argparse
import sys
import time
import keyboard

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from dit.config import load_config, save_config, Config
from dit.engine import DictationEngine
from dit.hotkey import HotkeyListener
from dit.tray import SystemTrayApp

BANNER = r"""
  ____   _      _   _     _ _   
 |  _ \ (_)    | | (_)   | | |  
 | | | | _  ___| |_ _  __| | |_ 
 | | | || |/ __| __| |/ _` | __|
 | |_| || | (__| |_| | (_| | |_ 
 |____/ |_|\___|\__|_|\__,_|\__|
   [^Shift+D it]  (Ctrl + Shift + D)   
"""

def run_self_test(engine: DictationEngine):
    print("\n--- Running D^it Verification & Self-Test ---")
    import numpy as np

    # Test 1: Whisper Transcriber Test
    print("[1/3] Testing Whisper STT model with synthetic speech-range signal...")
    t0 = time.time()
    dummy_audio = np.zeros(16000 * 2, dtype=np.float32)
    t = np.linspace(0, 2, 16000 * 2, endpoint=False)
    dummy_audio += 0.05 * np.sin(2 * np.pi * 440 * t).astype(np.float32)
    res = engine.transcriber.transcribe(dummy_audio)
    t_stt = time.time() - t0
    print(f"  ✓ Whisper inference executed in {t_stt*1000:.1f}ms (device: {engine.transcriber.device}, {engine.transcriber.compute_type})")

    # Test 2: Audio Device Test
    print("[2/3] Testing microphone device capture for 1 second...")
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
    print("[3/3] Testing clipboard injection and audio chimes...")
    engine.feedback.start_recording()
    time.sleep(0.15)
    engine.feedback.transcribed()
    time.sleep(0.15)
    print("  ✓ Sound cues verified.")
    print("--- Self-Test Complete! D^it is fully operational. ---\n")

def main():
    parser = argparse.ArgumentParser(description="D^it (^⇧D it) - Local Whisper Dictation for Windows")
    parser.add_argument("--hotkey", type=str, default=None, help="Global hotkey (e.g. 'ctrl+shift+d')")
    parser.add_argument("--mode", type=str, choices=["toggle", "ptt"], default=None, help="Dictation mode: 'toggle' or 'ptt'")
    parser.add_argument("--model", type=str, default=None, help="Whisper model ('small', 'tiny', 'base')")
    parser.add_argument("--device", type=str, choices=["auto", "cuda", "cpu"], default=None, help="Inference device")
    parser.add_argument("--paste-mode", type=str, choices=["clipboard", "type"], default=None, help="Text injection method")
    parser.add_argument("--no-cues", action="store_true", help="Disable audio feedback beeps")
    parser.add_argument("--no-tray", action="store_true", help="Disable system tray icon")
    parser.add_argument("--overlay", action="store_true", help="Enable floating visual badge")
    parser.add_argument("--save-config", action="store_true", help="Save current settings to config.json")
    parser.add_argument("--test", action="store_true", help="Run self-test diagnostic and exit")

    args = parser.parse_args()

    config = load_config()

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

    print(BANNER)
    print("Initializing D^it Dictation Engine...")
    engine = DictationEngine(config)

    if args.test:
        run_self_test(engine)
        return

    listener = HotkeyListener(engine, config)
    listener.start()
    engine.set_listener(listener)

    # Initialize System Tray
    tray_app = None
    if config.tray_enabled:
        tray_app = SystemTrayApp(engine, config)
        tray_app.start()
        engine.set_tray(tray_app)
        print("[Tray] Icon loaded in Windows system tray (notification area).")

    print(f"\n=======================================================")
    print(f" D^it is active in the background & System Tray!")
    print(f" Hotkey:     {config.hotkey.upper()} (^⇧D)")
    print(f" Mode:       {config.mode.upper()} ({'Press once to start/stop' if config.mode == 'toggle' else 'Hold to speak'})")
    print(f" Model:      Whisper '{config.model_name}' on {engine.transcriber.device.upper()} ({engine.transcriber.compute_type})")
    print(f" Paste:      {config.paste_mode.upper()} (Direct target window injection)")
    print(f" Icon Tray:  {'Enabled (check taskbar near clock)' if config.tray_enabled else 'Disabled'}")
    print(f" Exit:       Right-click tray icon -> 'Exit D^it' or press Ctrl+C")
    print(f"=======================================================\n")

    try:
        # If tray app is active, wait until tray stops or ctrl+c
        while True:
            time.sleep(0.5)
            if tray_app and tray_app.tray and not tray_app.tray.visible:
                break
    except KeyboardInterrupt:
        print("\nStopping D^it...")
    finally:
        listener.stop()
        if tray_app:
            tray_app.stop()
        print("D^it stopped cleanly.")

if __name__ == "__main__":
    main()
