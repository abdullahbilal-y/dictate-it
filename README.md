# D^it (^⇧D it — Dictate It)

**D^it** is a lightning-fast, local Windows voice dictation utility powered by **OpenAI Whisper** via `faster-whisper` and NVIDIA CUDA acceleration.

Whenever you press **`Ctrl + Shift + D`** (`^⇧D`), D^it captures your voice, transcribes it locally with zero cloud latency (~75ms–200ms inference), and instantly injects the text into whatever application you are currently focused on (Notepad, VS Code, Browser, Slack, Word, Terminal, etc.).

---

## ⚡ Features

- **System Icon Tray Support:** Runs quietly in your Windows taskbar tray (near the clock). Right-click the icon to toggle modes, trigger dictation, or exit.
- **Dynamic Tray States:**
  - 🔵 Blue mic: Idle & ready
  - 🔴 Red circle: Actively recording your voice
  - 🟠 Orange star: Transcribing with Whisper
- **Focus-Locked Injection:** Automatically captures the active window handle before recording and restores focus right before sending native Windows `Ctrl+V`.
- **Sub-Second Local STT:** Runs Whisper entirely on your GPU (CUDA `float16`) using cached local models (`small` or `tiny`). No API keys, no monthly fees, and 100% private.
- **Two Trigger Modes:**
  - **Toggle Mode (Default):** Press `Ctrl+Shift+D` once to start speaking; press it again to finish and paste.
  - **Push-to-Talk (PTT):** Hold `Ctrl+Shift+D` while speaking; release to finish and paste.
- **Auditory Cues:** Non-blocking pleasant chimes (rising chirp when recording starts, descending confirmation chime when text is injected, low double-chime if silence/no speech is heard).

---

## 🚀 How to Run

### Option 1: Run in System Tray (Silent Background)
Double-click [**`run_silent_tray.vbs`**](file:///c:/Projects/D%5Eit/run_silent_tray.vbs).
It starts D^it directly in your Windows Icon Tray without keeping a console window open!

### Option 2: Run with Terminal Console
Double-click [**`run_dit.bat`**](file:///c:/Projects/D%5Eit/run_dit.bat) or run from PowerShell:

```powershell
python main.py
```

---

## 🎙️ How to Dictate
1. Click into any text field or editor (e.g. Notepad, VS Code, Google Chrome).
2. Press **`Ctrl + Shift + D`** (hear the chirp, tray icon turns red).
3. Speak naturally.
4. Press **`Ctrl + Shift + D`** again (or release if using PTT).
5. Hear the confirmation chime and watch your text appear instantly in your editor!

---

## 🛠️ CLI Options

```powershell
# Run with Push-to-Talk mode (hold hotkey to speak, release to paste)
python main.py --mode ptt

# Use ultra-fast 'tiny' model (~75ms)
python main.py --model tiny

# Change the global hotkey
python main.py --hotkey "ctrl+space"

# Run diagnostic self-test
python main.py --test
```
