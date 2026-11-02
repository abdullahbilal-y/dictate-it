# File Map: D^it

```
c:\Projects\D^it\
├── brain\                     # Project brain (inherited lessons, landmines, architecture)
│   ├── architecture.md
│   ├── file-map.md
│   ├── glossary.md
│   ├── landmines.md
│   ├── operations.md
│   ├── README.md
│   └── system-overview.md
├── dit\                       # Main Python package
│   ├── __init__.py
│   ├── config.py              # Configuration & settings management
│   ├── audio.py               # SoundDevice audio capture stream
│   ├── transcriber.py         # faster-whisper STT wrapper (CUDA/CPU)
│   ├── injector.py            # Windows clipboard / keyboard text injection
│   ├── feedback.py            # Audio cues (winsound chimes)
│   ├── overlay.py             # Floating Tkinter indicator
│   ├── hotkey.py              # Global keyboard hotkey listener
│   └── engine.py              # Central orchestrator with timing telemetry
├── main.py                    # Application CLI and daemon launcher
├── run_dit.bat                # Windows double-click runner
├── requirements.txt           # Python package requirements
├── AGENTS.md                  # Agent operating guide
└── README.md                  # User-facing guide & documentation
```
