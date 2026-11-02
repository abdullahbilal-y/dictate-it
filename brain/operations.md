# Operations & Runbook: D^it

## Prerequisites
- Windows 10/11
- Python 3.10+
- Installed packages: `faster-whisper`, `sounddevice`, `numpy`, `pyperclip`, `keyboard` (all pre-verified on host).
- Microphone input device.

## Running D^it
```powershell
# Default: Ctrl+Shift+D toggle mode, small model on CUDA
python main.py

# Push-to-Talk mode (hold Ctrl+Shift+D to dictate)
python main.py --mode ptt

# Use tiny model (even faster)
python main.py --model tiny

# Run self-test verification without hotkey loop
python main.py --test
```

## Troubleshooting
1. **CUDA / CTranslate2 device error:**
   If GPU is unavailable, D^it automatically falls back to CPU (`int8`).
2. **Hotkey not triggering in elevated windows:**
   Windows User Account Control (UAC) blocks global hotkey hooks from non-elevated apps targeting elevated apps. Run terminal as Administrator if typing into elevated cmd/PowerShell is required.
3. **Empty transcription:**
   Check default microphone in Windows Sound Settings. Verify device with `python -m sounddevice`.
