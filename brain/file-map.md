# File Map: D^it

```
D^it\
├── brain\                     # Project brain (architecture, landmines, operations...)
├── assets\animations\         # Lottie: logo.json (brand mark) + optional card icons (README inside)
├── assets\brand\              # Static logo SVGs (dark/light backgrounds)
├── dit\
│   ├── config.py              # Settings (config.json); tasks/watcher/AI knobs
│   ├── env.py                 # .env + user-env secret loading (OPENROUTER_API_KEY)
│   ├── audio.py               # SoundDevice capture + live level
│   ├── transcriber.py         # faster-whisper wrapper (CUDA/CPU), hotwords, xet download guard
│   ├── cloud_stt.py           # Groq Whisper large-v3 client + VAD gate
│   ├── injector.py            # Clipboard / keystroke injection
│   ├── feedback.py            # winsound chimes (dictation + task cues)
│   ├── overlay.py             # Legacy tkinter dictation pill (off by default)
│   ├── hotkey.py              # Global hotkeys: dictate, task, peek
│   ├── engine.py              # Orchestrator; routes transcripts to injector or tasks; timing telemetry
│   ├── tray.py                # pystray menu incl. Tasks submenu, watcher/AI toggles
│   ├── startup.py             # Start-with-Windows (delegates to launcher)
│   ├── launcher.py            # --install: bin/DictateIt.exe, Start Menu entry, logon task
│   ├── selftest.py            # Task self-test (--test) and card demo (--demo-ui)
│   ├── tasks\
│   │   ├── models.py          # Task, statuses, queue ordering
│   │   ├── store.py           # SQLite persistence
│   │   ├── text.py            # Local word matching
│   │   ├── intents.py         # Spoken command -> Intent (rules + AI validation)
│   │   ├── manager.py         # All task state changes, watcher callbacks, nudges
│   │   ├── presenter.py       # Card wording
│   │   └── system.py          # Wiring
│   ├── watch\
│   │   ├── window.py          # Win32 foreground/idle/notification state
│   │   ├── browser.py         # Active-tab URL via UI Automation
│   │   ├── context.py         # Title (+URL) -> Context
│   │   ├── sessionizer.py     # Samples -> segments
│   │   └── watcher.py         # 1s polling thread
│   ├── ai\
│   │   ├── groq.py            # Groq chat client + provider chain (Groq -> OpenRouter)
│   │   ├── openrouter.py      # Client, budget, fallbacks
│   │   ├── prompts.py         # Everything sent to the AI
│   │   └── linker.py          # Context -> task linking tiers
│   └── ui\
│       ├── win32.py           # Layered window
│       ├── paper.py           # Paper & cogs card skin (default)
│       ├── cards.py           # Glass card renderer
│       ├── host.py            # Card stack + animation loop
│       ├── anim.py            # Easing + springs
│       ├── theme.py           # Light/dark/high-contrast/reduced-motion
│       ├── lottie.py          # Optional Lottie icons
│       └── a11y.py            # Screen-reader announcements
├── tools\stt_bench.py         # STT word-error bench (local vs Groq, with/without vocabulary)
├── main.py                    # CLI + launcher
├── .env.example               # OPENROUTER_API_KEY template (.env is git-ignored)
└── requirements.txt
```
