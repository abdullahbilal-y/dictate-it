# Landmines

The key page. Non-obvious traps in this repo, each capturing the WHY. Add an entry whenever you hit something non-obvious — always include the WHY.

---

## 1. Fast text injection via simulated typing can miss chars or trigger hotkeys — verified
**What:** Typing long transcribed strings via individual synthetic keystrokes (`keyboard.write` or `pynput`) can drop characters, take seconds to type, or accidentally trigger editor hotkeys if modifier keys are still pressed.
**Why:** Synthetic keydown/keyup events rely on the target application's message pump processing each character sequentially at system speed.
**Do:** Use the clipboard + `Ctrl+V` paste pattern: backup previous clipboard, write transcribed text to clipboard, simulate `Ctrl+V` (ensuring modifier keys are released first), wait a tiny debounce (50ms), then optionally restore the previous clipboard.
**Refs:** `dit/injector.py`

## 2. Windows hotkey modifiers sticking on release — verified
**What:** When using `Ctrl+Shift+D` to trigger dictation, synthetic `Ctrl+V` pasting might see `Shift` or `Ctrl` still held down by the user, resulting in `Ctrl+Shift+V` or corrupted keystrokes.
**Why:** The global hotkey triggers while physical keys are pressed down. If text injection happens immediately upon release, OS key state may lag.
**Do:** Wait briefly (e.g. 50-100ms) or explicitly simulate releasing modifiers before triggering `Ctrl+V`.
**Refs:** `dit/hotkey.py`, `dit/injector.py`

## 3. If audio capture or VAD fails, fail loud — inherited — verify applies
**What:** Dictation utility sits quietly in the background without transcribing, making user think their mic or whisper is broken.
**Why:** VAD or sound device stream exceptions swallowed in background threads lead to silent death.
**Do:** Play distinct auditory feedback cues (high pitch beep on start, descending chime on success, low error double-buzz on failure/silence) and log clear error output.
**Refs:** `dit/audio.py`, `dit/feedback.py`, [../lessons/one-vad-fail-loud.md](../lessons/one-vad-fail-loud.md)

## 4. Endpointing silence is a fixed tax on every turn — inherited — verify applies
**What:** Auto-stop / VAD dictation feels sluggish if silence duration is too long.
**Why:** The VAD end-of-speech silence wait is added to every utterance before Whisper STT even starts.
**Do:** Default to hotkey-controlled toggle/push-to-talk (instant stop on hotkey release/toggle), and when using VAD, tune silence threshold (e.g. 600-800ms) with pre-buffering.
**Refs:** `dit/recorder.py`, [../lessons/endpointing-is-a-fixed-latency-tax.md](../lessons/endpointing-is-a-fixed-latency-tax.md)

## 5. Instrument every stage before optimizing — inherited — verify applies
**What:** Guessing whether latency comes from mic buffer, Whisper model, or text injection.
**Why:** Multi-stage pipeline (record -> preprocess -> faster-whisper STT -> clipboard/paste).
**Do:** Log exact per-turn timing breakdown: `[Timing] Audio: 2.10s | Transcribe: 0.28s (CUDA float16) | Inject: 0.04s | Total: 2.42s`.
**Refs:** `dit/engine.py`, [../lessons/instrument-stages-before-optimizing.md](../lessons/instrument-stages-before-optimizing.md)

## 6. Whisper hallucination on silence or background noise — verified
**What:** Whisper generates repetitive phrases ("Thank you", "Subtitles by...", etc.) on empty or whisper-quiet audio.
**Why:** Sequence-to-sequence autoregressive models hallucinate text when fed pure silence or low SNR noise.
**Do:** Filter audio with an RMS energy threshold or Whisper's `no_speech_prob` (> 0.6) before attempting to paste text.
**Refs:** `dit/transcriber.py`
