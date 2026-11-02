# D^it (^⇧D it — Dictate It)

**D^it** is a lightning-fast, local Windows voice dictation utility powered by **OpenAI Whisper** via `faster-whisper` and NVIDIA CUDA acceleration.

Whenever you press **`Ctrl + Shift + D`** (`^⇧D`), D^it captures your voice, transcribes it locally with zero cloud latency (~75ms–200ms inference), and instantly injects the text into whatever application you are currently focused on (Notepad, VS Code, Browser, Slack, Word, Terminal, etc.).

---

## ⚡ Features

- **Global Hotkey:** `Ctrl+Shift+D` triggers dictation from anywhere in Windows.
- **Sub-Second Local STT:** Runs Whisper entirely on your GPU (CUDA `float16`) using the cached local models (`small` or `tiny`). No API keys, no monthly fees, and 100% private.
- **Two Trigger Modes:**
  - **Toggle Mode (Default):** Press `Ctrl+Shift+D` once to start speaking; press it again to finish and paste.
  - **Push-to-Talk (PTT):** Hold `Ctrl+Shift+D` while speaking; release to finish and paste.
- **Instant Text Injection:** Uses Windows clipboard + simulated `Ctrl+V` with modifier clearance and automatic previous-clipboard restoration.
- **Auditory Cues:** Non-blocking pleasant chimes (rising chirp when recording starts, descending confirmation chime when text is injected, low double-chime if silence/no speech is heard).
- **Floating Status Badge:** Minimalist semi-transparent on-screen pill indicator (`🎙️ Listening`, `⚡ Transcribing`, `✓ Dictated`).
- **Telemetry & Logging:** Real-time per-turn stage breakdown (audio duration, STT latency, injection latency).

---

## 🚀 Quick Start

### 1. Launch D^it
Double-click `run_dit.bat`, or run from terminal:

```powershell
python main.py
```

### 2. Dictate Anywhere
1. Click into any text field or editor (e.g. Notepad, VS Code, Google Chrome).
2. Press **`Ctrl + Shift + D`**.
3. Hear the rising chirp and speak your message.
4. Press **`Ctrl + Shift + D`** again (or release if using PTT).
5. Hear the confirmation chime and watch your text instantly appear!

---

## 🛠️ CLI Options & Configuration

You can customize hotkey, model, mode, and behavior directly:

```powershell
# Run with Push-to-Talk (hold hotkey to speak, release to paste)
python main.py --mode ptt

# Use ultra-fast 'tiny' model (~75ms latency)
python main.py --model tiny

# Change the global hotkey
python main.py --hotkey "ctrl+space"

# Disable sound cues or GUI overlay
python main.py --no-cues --no-overlay

# Save current CLI flags to config.json as permanent defaults
python main.py --mode toggle --model small --save-config

# Run diagnostic self-test
python main.py --test
```

### Configuration File (`config.json`)
Settings can also be modified in `config.json`:
```json
{
  "hotkey": "ctrl+shift+d",
  "mode": "toggle",
  "model_name": "small",
  "device": "auto",
  "compute_type": "auto",
  "paste_mode": "clipboard",
  "restore_clipboard": true,
  "restore_delay_ms": 250,
  "audio_cues": true,
  "gui_overlay": true,
  "samplerate": 16000,
  "language": "en",
  "beam_size": 1,
  "energy_threshold": 0.003
}
```

---

## 🧠 Project Architecture & Playbooks

D^it was built following the lessons in [ai-playbooks](brain/landmines.md):
- **Stage Timing Telemetry:** Logs audio length, STT inference, and injection latency per turn.
- **Fail Loud:** Auditory and console alarms on mic or model errors rather than silent failure.
- **Modifier Clearance:** Avoids sticking Ctrl/Shift hotkey modifiers during automated paste.
- **Hallucination Guard:** Discards silence and repetitive autoregressive tokens.

For architectural details, check the `brain/` directory:
- [brain/system-overview.md](brain/system-overview.md)
- [brain/architecture.md](brain/architecture.md)
- [brain/landmines.md](brain/landmines.md)
- [brain/operations.md](brain/operations.md)

