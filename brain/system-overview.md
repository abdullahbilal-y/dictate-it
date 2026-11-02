# System Overview: D^it (^⇧D it — Dictate It)

## What it is
**D^it** (pronounced "Dictate It", hotkey `^⇧D` = `Ctrl+Shift+D`) is a blazing-fast, local Windows voice dictation utility powered by OpenAI's Whisper (via `faster-whisper` with CUDA GPU acceleration).

When triggered anywhere on Windows:
1. It listens to the microphone.
2. It transcribes the spoken speech with zero cloud latency using the local cached Whisper model (`small` or `tiny` on CUDA float16).
3. It instantly pastes or types the transcribed text directly into the active application (Notepad, VS Code, Browser, Slack, Word, Terminal, etc.).

## Key Capabilities
- **Global Hotkey:** `Ctrl+Shift+D` (`^⇧D`) works across all Windows applications.
- **Dual Trigger Modes:**
  - *Toggle Mode* (default): Press `Ctrl+Shift+D` to start recording, press `Ctrl+Shift+D` again to stop and paste.
  - *Push-to-Talk Mode*: Hold `Ctrl+Shift+D` while speaking, release to stop and paste.
- **Ultra-Fast Local Transcription:** Uses `faster-whisper` (CTranslate2) on CUDA with `float16`, transcribing 3-5 seconds of speech in < 300ms.
- **Reliable Text Injection:** Injects text via clipboard + `Ctrl+V` with modifier clearance and fallback to direct typing.
- **Audio Feedback:** Subtle audio chimes (rising chime on start, descending chime on paste, error chime on empty audio) so you never have to take your eyes off your work.
- **Floating Status Pill:** Unobtrusive on-screen indicator displaying `[● REC]`, `[⚡ Transcribing]`, and `[✓ Dictated]`.
- **Instrumentation:** Structured timing telemetry for audio capture, transcription, and injection.
