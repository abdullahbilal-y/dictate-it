import json
import os
from dataclasses import dataclass, asdict

@dataclass
class Config:
    hotkey: str = "ctrl+shift+d"
    mode: str = "toggle"             # "toggle" (press to start, press to stop) or "ptt" (hold)
    model_name: str = "small"        # "small", "tiny", "base", "medium"
    device: str = "auto"             # "auto", "cuda", "cpu"
    compute_type: str = "auto"       # "auto", "float16", "int8"
    paste_mode: str = "clipboard"    # "clipboard" (instant Ctrl+V) or "type" (keystrokes)
    restore_clipboard: bool = True   # restore previous clipboard content after paste
    restore_delay_ms: int = 250      # wait before restoring clipboard to let target app read it
    audio_cues: bool = True          # auditory chimes for start/stop/dictate
    gui_overlay: bool = True         # small floating visual status badge
    samplerate: int = 16000          # 16kHz for Whisper
    language: str = "en"             # "en" or None for multilingual auto-detect
    beam_size: int = 1               # 1 is greedy & ultra fast, 5 is higher accuracy
    energy_threshold: float = 0.003  # RMS audio threshold to detect speech vs silence

CONFIG_FILE = "config.json"

def load_config(path: str = CONFIG_FILE) -> Config:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return Config(**{k: v for k, v in data.items() if k in Config.__dataclass_fields__})
        except Exception as e:
            print(f"[Config] Error loading {path}: {e}, using defaults.")
    return Config()

def save_config(config: Config, path: str = CONFIG_FILE) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(config), f, indent=2)
    except Exception as e:
        print(f"[Config] Error saving {path}: {e}")
