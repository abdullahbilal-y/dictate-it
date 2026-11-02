# D^it (Dictate It)

**D^it** is a lightning-fast, local Windows voice dictation utility powered by **OpenAI Whisper** via `faster-whisper` and NVIDIA CUDA acceleration.

Whenever you press **`Ctrl + Alt + D`** (or your chosen shortcut), D^it captures your voice, transcribes it locally with zero cloud latency (~75ms–200ms inference), and instantly injects the text into whatever application you are currently focused on (Notepad, VS Code, Browser, Slack, Word, Terminal, etc.).

---

## ⚡ Features

- **Conflict-Free Shortcut (`Ctrl + Alt + D`):** Unlike `Ctrl+Shift+D` (which collides with Chrome's "Bookmark All Tabs" and VS Code's "Debug View"), `Ctrl+Alt+D` is completely free across all major browsers, IDEs, and Windows apps.
- **System Icon Tray Support:** Runs quietly in your Windows taskbar notification area (near the clock). Right-click the icon to switch shortcuts, toggle modes, or exit.
- **Dynamic Tray States:**
  - 🔵 Blue mic: Idle & ready
  - 🔴 Red circle: Actively recording your voice
  - 🟠 Orange star: Transcribing with Whisper
- **Focus-Locked Injection:** Automatically captures the active window handle before recording and restores focus right before sending native Windows `Ctrl+V`.
- **Sub-Second Local STT:** Runs Whisper entirely on your GPU (CUDA `float16`) using cached local models (`small` or `tiny`). No API keys, no monthly fees, and 100% private.
- **Two Trigger Modes:**
  - **Toggle Mode (Default):** Press shortcut once to start speaking; press it again to finish and paste.
  - **Push-to-Talk (PTT):** Hold shortcut while speaking; release to finish and paste.
- **Auditory Cues:** Non-blocking pleasant chimes (rising chirp when recording starts, descending confirmation chime when text is injected).

---

## 🚀 How to Run

### Option 1: Run in System Tray (Silent Background)
Double-click [**`run_silent_tray.vbs`**](file:///c:/Projects/D%5Eit/run_silent_tray.vbs).  
It launches D^it straight into your Windows Icon Tray without keeping a console window open!

### Option 2: Run with Terminal Console
Double-click [**`run_dit.bat`**](file:///c:/Projects/D%5Eit/run_dit.bat) or run from PowerShell:

```powershell
python main.py
```

---

## 🔄 Start Automatically with Windows

To have D^it run automatically in the background when you turn on your computer:

- **Method A (Easiest):** Right-click the D^it tray icon and check **Start with Windows**.
- **Method B (1-Click):** Double-click [**`add_to_startup.bat`**](file:///c:/Projects/D%5Eit/add_to_startup.bat) (or run `remove_from_startup.bat` to undo).
- **Method C (CLI):** Run `python main.py --enable-startup`.

---

## ⌨️ Shortcut Key Presets

Right-click the icon in your system tray and choose **Shortcut Key** to switch between presets instantly:

1. **`Ctrl + Alt + D`** *(Default)* — Conflict-free, preserves "D for Dictate".
2. **`Ctrl + Alt + Space`** — Thumb-friendly combination.
3. **`F8`** — Single dedicated key for fast one-touch dictation.
4. **`Alt + \`** — Convenient symbol key shortcut.
5. **`Ctrl + Shift + D`** — Legacy option.

Your selected shortcut is automatically saved to `config.json` and remembered across reboots!

---

## 🎙️ How to Dictate
1. Click into any text field or editor (e.g. Notepad, VS Code, Google Chrome).
2. Press **`Ctrl + Alt + D`** (hear the chirp, tray icon turns red).
3. Speak naturally.
4. Press **`Ctrl + Alt + D`** again (or release if using PTT).
5. Hear the confirmation chime and watch your text appear instantly in your editor!
