# Architecture: D^it

```
User (Global Hotkey: Ctrl+Shift+D)
               │
               ▼
       [dit.hotkey / Listener]
               │ triggers
               ▼
       [dit.engine / DictationEngine]
        │              │             │
        ▼              ▼             ▼
 [dit.feedback]  [dit.audio]  [dit.overlay]
   (Chime In)    (16kHz Mic)   (Status Pill)
                       │
             User speaks & releases/toggles
                       │
                       ▼
            [dit.transcriber]
     (faster-whisper Small/Tiny on CUDA)
                       │
                       ▼
            [dit.injector]
     (Clipboard + Ctrl+V / Direct Write)
                       │
                       ▼
            Active Windows Target App
```

## Components
1. **Audio Recorder (`dit/audio.py`):**
   - Streams 16000Hz mono float32 audio via `sounddevice`.
   - In-memory collection avoids disk I/O latency.
   - Computes RMS volume to discard pure silence.

2. **Transcriber (`dit/transcriber.py`):**
   - Initialized once at startup (keeps Whisper in GPU VRAM).
   - Fast inference: `faster-whisper` with `small` model (cached in `~/.cache/huggingface/hub/models--Systran--faster-whisper-small`).
   - Hallucination suppression via `no_speech_prob` thresholding.

3. **Injector (`dit/injector.py`):**
   - Stores current clipboard state.
   - Clears pending modifier keys (Ctrl/Shift/Alt) to avoid shortcut collision.
   - Writes text to clipboard and issues `Ctrl+V`.
   - Restores previous clipboard with debounce.

4. **Hotkey Hook (`dit/hotkey.py`):**
   - Hooks `ctrl+shift+d` globally using `keyboard`.
   - Handles key press and key release with debounce.

5. **Audio Feedback (`dit/feedback.py`):**
   - Uses `winsound.Beep` in non-blocking daemon threads for low overhead.
