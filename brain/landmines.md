# Landmines

The key page. Non-obvious traps in this repo, each capturing the WHY. Add an entry whenever you hit something non-obvious — always include the WHY.

---

## 1. Fast text injection via simulated typing can miss chars or trigger hotkeys — verified
**What:** Typing long transcribed strings via individual synthetic keystrokes (`keyboard.write` or `pynput`) can drop characters, take seconds to type, or accidentally trigger editor hotkeys if modifier keys are still pressed.
**Why:** Synthetic keydown/keyup events rely on the target application's message pump processing each character sequentially at system speed.
**Do:** Use the clipboard + `Ctrl+V` paste pattern: backup previous clipboard, write transcribed text to clipboard, simulate `Ctrl+V` (ensuring modifier keys are released first), wait a tiny debounce (50ms).
**Refs:** `dit/injector.py`

## 2. Windows hotkey modifiers sticking on release — verified
**What:** When using `Ctrl+Shift+D` to trigger dictation, synthetic `Ctrl+V` pasting might see `Shift` or `Ctrl` still held down by the user, resulting in `Ctrl+Shift+V` or corrupted keystrokes.
**Why:** The global hotkey triggers while physical keys are pressed down. If text injection happens immediately upon release, OS key state may lag.
**Do:** Call native `keybd_event(VK, 0, KEYEVENTF_KEYUP, 0)` for `Shift`, `Ctrl`, `Alt`, and `Win` before dispatching `Ctrl+V`.
**Refs:** `dit/hotkey.py`, `dit/injector.py`

## 3. Popups/overlays stealing foreground focus from target window — verified
**What:** User presses hotkey in Notepad/VS Code/browser, speaks, but nothing gets pasted into the text field.
**Why:** Showing an on-screen GUI indicator or notification window transfers Windows foreground focus away from the target editor. When `Ctrl+V` fires, it pastes into nothing.
**Do:**
1. Capture `target_hwnd = user32.GetForegroundWindow()` at the exact moment dictation starts.
2. Call `user32.SetForegroundWindow(target_hwnd)` right before pasting.
3. If using any GUI window, set `WS_EX_NOACTIVATE` (0x08000000) so the OS never shifts keyboard focus.
**Refs:** `dit/engine.py`, `dit/injector.py`, `dit/overlay.py`

## 4. Setting artificial RMS silence thresholds lower than mic sensitivity — verified
**What:** User speaks clearly into microphone, but dictation discards the entire audio chunk as "silence".
**Why:** Many desktop USB/headset microphones output RMS levels around 0.0007–0.002 during normal speech. A hardcoded threshold like 0.003 silently drops all utterances.
**Do:** Keep RMS cutoff near zero (e.g. 0.00005) only to drop absolute hardware dead-silence, and let Whisper's built-in Silero neural VAD (`vad_filter=True`) accurately detect speech.
**Refs:** `dit/engine.py`, `dit/config.py`

## 5. Restoring clipboard before target application finishes reading it — verified
**What:** Text isn't pasted, or previous clipboard contents get pasted instead of dictated text.
**Why:** Target applications process Windows `WM_PASTE` messages asynchronously. If clipboard restoration runs after only 200–300ms, the app reads the restored clipboard instead of the dictated text.
**Do:** Leave dictated text in the clipboard by default (`restore_clipboard=False`), allowing the user to also re-paste manually if desired.
**Refs:** `dit/injector.py`, `dit/config.py`

## 6. Instrument every stage before optimizing — inherited — verify applies
**What:** Guessing whether latency comes from mic buffer, Whisper model, or text injection.
**Why:** Multi-stage pipeline (record -> preprocess -> faster-whisper STT -> clipboard/paste).
**Do:** Log exact per-turn timing breakdown: `[Timing] Audio: 2.10s | STT: 0.09s (CUDA float16) | Inject: 0.05s | Total: 2.24s`.
**Refs:** `dit/engine.py`, [../lessons/instrument-stages-before-optimizing.md](../lessons/instrument-stages-before-optimizing.md)

## 7. Ctrl+Shift+D collides with browser and IDE standard shortcuts — verified
**What:** Pressing `Ctrl+Shift+D` opens "Bookmark all tabs" in Chrome / Edge, opens Run & Debug view in VS Code, or duplicates lines in Sublime Text.
**Why:** `Ctrl+Shift+D` is heavily claimed by major applications.
**Do:** Use `Ctrl+Alt+D` (or `Ctrl+Alt+Space` / `F8`) which is universally unassigned across Chrome, VS Code, Office, and Windows. Provide 1-click preset switching in the tray menu.
**Refs:** `dit/config.py`, `dit/tray.py`, `dit/hotkey.py`
