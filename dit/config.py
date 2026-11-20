import json
import os
from dataclasses import dataclass, asdict, field

@dataclass
class Config:
    hotkey: str = "ctrl+alt+d"        # Conflict-free: does not collide with Chrome bookmark or IDE shortcuts
    mode: str = "toggle"              # "toggle" (press to start, press to stop) or "ptt" (hold)
    model_name: str = "small"         # "small", "tiny", "base", "medium"
    device: str = "auto"              # "auto", "cuda", "cpu"
    compute_type: str = "auto"        # "auto", "float16", "int8"
    paste_mode: str = "clipboard"     # "clipboard" (instant Ctrl+V) or "type" (keystrokes)
    restore_clipboard: bool = False   # Keep text in clipboard so app has full time to read & user has copy
    restore_delay_ms: int = 1000      # if true, wait 1000ms before restoring
    audio_cues: bool = True           # auditory chimes for start/stop/dictate
    gui_overlay: bool = False         # Disabled by default so focus is NEVER stolen from target editor
    tray_enabled: bool = True         # Runs in Windows System Tray (icon tray)
    samplerate: int = 16000           # 16kHz for Whisper
    language: str = "en"              # "en" or None for multilingual auto-detect
    beam_size: int = 1                # 1 is greedy & ultra fast, 5 is higher accuracy
    energy_threshold: float = 0.00005 # Minimal threshold; let Whisper's built-in Silero VAD handle speech gating
    task_beam_size: int = 5
    max_task_record_s: int = 45       # forgot to stop? task recordings stop on their own after this
    max_dictate_record_s: int = 300   # ...and dictation after this           # Task commands are short and must be exact: spend ~100ms more on accuracy

    # --- Speech-to-text engine ---
    # Groq hosts Whisper large-v3 (free tier: 2,000 requests/day). Used when GROQ_API_KEY is set, for the routes
    # listed here; local Whisper is the fallback whenever Groq fails. Remove "task" to keep everything local.
    stt_cloud_routes: list = field(default_factory=lambda: ["task"])   # add "dictate" to send dictation too
    groq_stt_model: str = "whisper-large-v3"
    custom_vocabulary: list = field(default_factory=list)   # names Whisper keeps getting wrong, e.g. ["DP World", "EIR"]

    # --- Tasks: voice capture + queue cards ---
    tasks_enabled: bool = True
    task_hotkey: str = "ctrl+alt+t"   # Speak a task command ("add…", "that's done", "pause the report")
    peek_hotkey: str = "ctrl+alt+q"   # Show the queue card
    animations_dir: str = "assets/animations"  # Lottie icons + logo.json (see assets/animations/README.md)
    card_style: str = "paper"         # "paper" (mechanical: plate with a gear rack on a cog) or "glass"
    paper_theme: str = "graphite"     # graphite, blueprint, kraft, ivory, paper (tray: Look)
    startup_card: bool = True         # "DictateIt is ready" card with the logo when the app starts

    # --- Context watcher (app name + window title + browser tab address; no screenshots or content) ---
    watcher_enabled: bool = True
    read_browser_urls: bool = True    # active tab address via UI Automation (query strings are always dropped)
    settle_s: int = 8                 # A new window must hold focus this long to count as a context switch
    idle_after_s: int = 120           # No keyboard/mouse input this long = away (not "working on" anything)
    activate_after_s: int = 20        # Dwell in a task's context this long before it becomes Active
    nudge_after_s: int = 120          # Away from the last focused task this long -> ask "wrapped up?"
    checkin_after_s: int = 90         # No active task + unlinked window this long -> ask "working on <task>?"
    checkin_cooldown_s: int = 600     # At most one "working on?" question per this many seconds
    nudge_min_focus_s: int = 60       # Only ask about tasks you actually spent time on
    nudge_cooldown_s: int = 600       # At most one nudge per this many seconds
    resume_after_s: int = 600         # Returning to a paused task after this long shows a "picking up" card
    private_apps: list = field(default_factory=lambda: [
        "keepass.exe", "keepassxc.exe", "1password.exe", "bitwarden.exe", "lastpass.exe",
    ])

    # --- AI (OpenRouter). Key comes from OPENROUTER_API_KEY env var or .env, never config.json ---
    ai_enabled: bool = True
    ai_models: list = field(default_factory=lambda: [   # tried in order; free models come and go
        "nvidia/nemotron-3.5-lightning:free",
        "google/gemma-4-31b-it:free",
        "openrouter/free",
    ])
    ai_daily_budget: int = 45         # Free tier allows 50 req/day; keep headroom
    ai_link_share: float = 0.4        # Context linking may use at most this share of the daily budget
    ai_refine_share: float = 0.6      # Tidying new task titles stops here; the rest is kept for understanding commands
    ai_link_min_dwell_s: int = 45     # Only ask the AI about windows you stayed in this long
    ai_timeout_s: float = 12.0
    # Groq chat models (free tier: 1,000 requests/day each), tried before OpenRouter when GROQ_API_KEY is set.
    groq_models: list = field(default_factory=lambda: [
        "openai/gpt-oss-20b",
        "qwen/qwen3.8-27b",
        "openai/gpt-oss-120b",
    ])
    groq_daily_budget: int = 900

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
