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

## Tasks & context recovery (since Nov 2026)
D^it also works as a quiet task tracker that lives in the tray:
- **Voice capture** — `Ctrl+Alt+T`, then say "add finish the November report", "that's done", "pause the report", "what's next". The transcript is parsed by local rules instantly; OpenRouter (optional, free tier) cleans the title, infers a project and resolves vague references in the background.
- **Cards, not windows** — a top-right card stack confirms everything: queued (check draws in), done (strike-through, particle burst, dissolve), removed (collapse), "wrapped up?" questions with buttons, "picking up" when you return to interrupted work, and a queue peek (`Ctrl+Alt+Q`).
- **Context awareness** — the watcher reads only the foreground app and window title each second, turns them into working segments, and links segments to tasks (word overlap first, AI only for windows you stay in). Staying in a task's context makes it Active; moving away and not coming back prompts one calm question. It never completes a task on its own.
- **Check-in** — when nothing is Active and you settle into a window no task is linked to, one "Working on this?" card asks; Yes links that window to the task (no AI needed) so leaving it later triggers "Wrapped up?".
- **Forgiving commands** — "DP World done" matches "Dpworld EIRs" (spacing/spelling tolerant), "done that" means the latest task, "all X tasks are done" completes every match, ambiguous ones become "Which one?" capsules, "undo" reverts.
- **States** — Ready, Active, Paused, Waiting, Completed (plus soft-deleted Removed).
