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

## 8. Windows Script Host / VBScript errors on Windows Startup — verified
**What:** On Windows boot, a Windows Script Host popup error appeared ("Can not find script file...").
**Why:** An earlier shortcut script escaped quotes with backticks inside a single-quoted PowerShell string, baking literal backticks into the shortcut argument path. Furthermore, routing startup through `wscript.exe` is fragile and depends on deprecated VBScript subsystem.
**Do:** Point the Windows Startup shortcut (`DictateIt.lnk`) directly to `pythonw.exe` with arguments `main.py` and `WorkingDirectory` set to the project root. `pythonw.exe` natively launches headless with zero console window and completely bypasses Windows Script Host.
**Refs:** `dit/startup.py`

## 9. Whisper model download hangs forever on HuggingFace's "xet" path — verified (Nov 2026)
**What:** DictateIt sat at `Loading Whisper 'small'...` for two days; the tray never appeared. The cache held four 0-byte `*.incomplete` blobs and the running `pythonw main.py` kept them locked.
**Why:** `huggingface_hub` 1.x downloads through `hf_xet` by default; on this machine it stalled with no error and no timeout. The plain HTTPS path (`HF_HUB_DISABLE_XET=1`) downloaded the 483 MB model normally.
**Do:** `dit/transcriber.py` sets `HF_HUB_DISABLE_XET=1` before importing faster-whisper. If it ever hangs again: stop the running instance, delete `~/.cache/huggingface/hub/models--Systran--faster-whisper-small/blobs/*.incomplete`, relaunch.
**Refs:** `dit/transcriber.py`

## 10. OpenRouter free tier: tiny quota, congested models, reasoning eats the answer — verified
**What:** Intent calls took 4–11s, some returned empty `content`, Gemma 4 free returned 429 "Provider returned error", and one route answered HTTP 400 "Reasoning is mandatory".
**Why:** Free models are 50 requests/day **per account** (1000 after $10 lifetime credit). Popular free models are rate-limited upstream. Free routing often picks reasoning models, which spend `max_tokens` thinking and return `content: null`.
**Do:** Send `"reasoning": {"enabled": false}` (~1s, clean JSON); on the "mandatory" 400 retry once with `{"effort": "low", "exclude": true}`. Keep a fallback `models` list. Never block capture on the AI: rules apply instantly, the AI refines in the background. Count attempts, and sync with `GET /api/v1/key` at startup.
**Refs:** `dit/ai/openrouter.py`, `dit/tasks/manager.py` (`handle_command`, `_refine`)

## 11. Layered windows: premultiplied alpha, and clicks must not activate — known Win32 rule, applied up front
**What:** Without these, cards show dark fringes / wrong colours, and clicking a card button steals focus from the user's editor.
**Why:** `UpdateLayeredWindow` with `AC_SRC_ALPHA` expects premultiplied BGRA (Pillow gives straight RGBA). `WS_EX_NOACTIVATE` alone doesn't stop activation on click.
**Do:** Premultiply in numpy (`premultiplied_bgra`). Return `MA_NOACTIVATE` from `WM_MOUSEACTIVATE`; show with `SW_SHOWNOACTIVATE`. Fully transparent pixels are click-through, so the window can be bigger than the cards.
**Refs:** `dit/ui/win32.py`

## 12. Window titles are messy, and that's all the watcher gets — verified
**What:** Context labels contained "Microsoft​ Edge" (with a zero-width space), "(3) Inbox", "and 2 more pages", "●" unsaved markers; VS Code gives only the folder *name*.
**Why:** Each app formats its title differently; we deliberately read titles only (no URLs, no screenshots).
**Do:** Normalise in `build_context` (strip `​`, counters, app suffix segments). For git branch detection, set VS Code `"window.title": "${activeEditorShort} - ${rootPath}"` so the workspace segment is a full path. Incognito/InPrivate titles and `private_apps` become "Private window" and are never linked or sent to the AI.
**Refs:** `dit/watch/context.py`

## 13. Layered cards are invisible to screen readers — inherited — verify applies
**What:** Narrator/NVDA can't read the cards (no UI Automation tree on a layered popup).
**Do:** When `SPI_GETSCREENREADER` is on, each card's `announce` text is spoken via SAPI (`dit/ui/a11y.py`). Every card action is also reachable from the tray menu (keyboard: Win+B, arrows) and by voice.
**Refs:** `dit/ui/a11y.py`, `dit/tray.py`

## 14. Ctrl+Alt+<letter> is AltGr on many non-US layouts — inherited — verify applies
**What:** On German/Polish/etc. layouts, Ctrl+Alt+Q types `@` and similar.
**Do:** If a user reports stray characters, move `task_hotkey` / `peek_hotkey` in `config.json` (e.g. `ctrl+alt+space`, `f9`).
**Refs:** `dit/config.py`

## 15. Browser URLs: read the address bar, never trust it blindly — verified (Edge), Chrome/Firefox inherited
**What:** Titles alone can't tell two Google Docs or two PRs apart reliably; but the address bar also holds half-typed searches, internal pages (`edge://settings`) and URLs with tokens in the query string.
**Why:** UI Automation exposes the omnibox as an Edit control whose value is whatever is in the box right now, including what the user is typing. The first UIA call in a process costs ~800ms (COM/UIA warm-up); later lookups ~10-30ms; cached element reads ~0.2ms. The watcher thread needs its own `CoInitialize`.
**Do:** `clean_url` rejects values with spaces or no dot and non-http(s) schemes, and keeps only `scheme://host/path`. Cache the ValuePattern per hwnd and re-find on COMError. Decide private windows from the title *before* touching UIA. Only `http(s)` URLs are ever passed to `os.startfile` (capsule click / tray "Reopen last page"). Chrome incognito detection relies on the title: verify on the Chrome version in use.
**Refs:** `dit/watch/browser.py`, `dit/watch/watcher.py`, `dit/tasks/manager.py::open_task`

## 16. Bash heredocs containing an apostrophe break in this environment — verified
**What:** `python - <<'EOF' ... EOF` scripts failed with "unexpected EOF while looking for matching `''" when the body contained `it's`/`you're`.
**Do:** Write multi-line patch scripts to a temp file with the file tool and run that instead.
**Refs:** (tooling)

## 17. rlottie renders some valid Lottie files as fully transparent — verified (Nov 2026, user's logo.json)
**What:** The logo animation (Bodymovin 5.9.4, 11 shape layers) rendered every frame blank. Adding sr/nm/bm, 4-component colours, 3D transforms, static transforms or `e` keyframe values changed nothing; a minimal hand-written file rendered fine.
**Why:** The exporter writes `"ty"` as the *last* key of every layer/shape object. rlottie parses in stream order and needs the type before the properties; otherwise it silently drops the object. No error, no warning.
**Do:** `dit/ui/lottie.py::load_lottie` reorders keys (`"ty"` first) before handing JSON to rlottie, and `LottieLibrary.clip` rejects clips whose last frames are fully transparent (falls back to the drawn icon with a log line) instead of showing an empty badge.
**Refs:** `dit/ui/lottie.py`

## 18. Real-use failure: "done" commands missed, completions became tasks, no nudges — verified (2026-11-18 log)
**What:** Of 48 spoken task commands, 9 "done" commands matched no task ("DP World done", "Dp World Task Done", "Last task was completed"), 6 completion statements were added as NEW tasks ("account is fixed", "I was done with..."), and 0 "Wrapped up?" nudges fired all day.
**Why:**
- Matching dropped words under 3 letters, so "DP World" never met the saved "Dpworld"; STT also wrote "TP World", "GDS6" for "GDA6".
- The rules only knew "X is done"-shaped sentences; "fixed", "checked", "I was done with" fell through to the default (add).
- "that" / "last task" only resolved to an Active task, and nothing was Active.
- Nudges need an Active task. In the morning the AI linker (confidence 0.6, "only open task" bias) linked a game, every Edge tab and VS Code to the one open task, so the user was never "away". In the afternoon nothing linked: titles shared no words with tasks and the free AI budget (45/day) was spent by 14:34, mostly on refining new task titles.
- Edge Workspaces keep the window title fixed to the workspace name ("Ibras95") on every tab, so every Edge page looked the same.
**Do:**
- Spoken references use `text.ref_score`: rejoins split words ("dp world" -> "dpworld"), fuzzy-matches STT spellings (ratio >= 0.8), ignores done-vocabulary. Close ties ask instead of guessing.
- Any statement containing past-tense done vocabulary (`DONE_WORDS`) is a completion unless it's explicitly an add or about the future ("make sure X is done by Friday"). Unresolved completions show "Which one is done?" capsules; they never create tasks. "undo" reverts the last change.
- "that" / "last task" fall back to the most recently added/touched task.
- No Active task + an unlinked window held for `checkin_after_s` -> one "Working on this?" card; Yes links the window (source=user) and activates the task, so the nudge works with zero AI.
- AI linking needs confidence >= 0.75 and specific shared evidence; refine may use at most `ai_refine_share` (60%) of the daily budget.
- Browser label = selected tab title from the UIA tab strip (read only when the URL changes, ~80ms with 75 tabs).
**Refs:** `dit/tasks/intents.py`, `dit/tasks/text.py`, `dit/tasks/manager.py` (`_maybe_checkin`, `show_pick`, `undo`), `dit/watch/browser.py`, `dit/ai/prompts.py`

## 19. Local AI counter vs OpenRouter's UTC day — verified
**What:** After the free quota reset, DictateIt still reported "0 calls left" while OpenRouter said 14/50 used.
**Why:** OpenRouter's free-model day rolls over at midnight UTC; the local counter is keyed by local date, and sync kept the higher of the two.
**Do:** `ai_set_used` overwrites with OpenRouter's count, and `chat_json` re-syncs (at most every 10 min) before refusing on budget.
**Refs:** `dit/tasks/store.py::ai_set_used`, `dit/ai/openrouter.py`

## 20. Whisper mishears names; give it the vocabulary — verified (bench, 2026-11-18)
**What:** "Absolomon's account is fixed" arrived as "Epsilon and the count is fixed"; "Jebel Ali" as "Jebel Alley"; "Amer" as "aimer"; "Ibras95" as "Iber's 95". Matching then failed or created junk tasks.
**Why:** Whisper `small` with greedy decoding has no idea which proper nouns exist in the user's world.
**Do:** Pass open/recent task titles + projects + `custom_vocabulary` as `hotwords` (local) / `prompt` (Groq), and use beam 5 for task commands. On SAPI-synthesised real phrases: WER 0.24 -> 0.06 for local small, +~50ms. Prompts can be echoed back on near-silence, so cloud uploads are VAD-gated and an output that is just a piece of the prompt is discarded. Re-run `python tools/stt_bench.py [--groq]` when changing models or hints.
**Refs:** `dit/engine.py::_transcribe`, `dit/cloud_stt.py`, `tools/stt_bench.py`

## 21. Untitled tabs leak their full URL through the tab title — verified (Nov 2026 log)
**What:** `appstoreconnect.apple.com/login?targetUrl=...&authResult=FAILED` appeared in the log as a context label, although URLs were cleaned everywhere else.
**Why:** A page without a `<title>` shows its address as the tab name; the tab-strip title bypassed `clean_url`.
**Do:** `clean_tab_title` runs anything URL-shaped through `clean_url` (host + path only). The existing log/DB rows were scrubbed.
**Refs:** `dit/watch/context.py::clean_tab_title`

## 22. "Doesn't start at startup": the app shut itself down, and Windows launched it late — verified
**What:** Several sessions logged "DictateIt stopped cleanly" seconds after starting; on other boots no start was logged before the user restarted 1-2 minutes later.
**Why:** (1) The main loop exited when `tray.visible` was False after 0.5s, but pystray sets it from a setup thread that runs late when the PC is busy at sign-in, so the app quit itself. (2) Explorer launches Startup-folder items with a delay that was 1-3+ minutes here.
**Do:** Exit only when the tray thread has ended (`Exit` in the menu). Start via a Task Scheduler logon task (5s delay, restart on failure) created by `python main.py --install`, which also builds `bin/DictateIt.exe` (pythonw copy + pyvenv.cfg + rebranded version/icon resources) so Task Manager and Startup apps show "DictateIt", and adds a Start Menu entry. A named mutex keeps one instance; a second launch signals the first to show its card.
**Refs:** `main.py` (`SingleInstance`, main loop), `dit/launcher.py`, `dit/startup.py`

## 24. Holding a hotkey = Windows auto-repeat = the action fires ~30x/s — verified
**What:** Holding Ctrl+Alt+Q toggled the queue open/closed continuously and lagged the machine.
**Why:** `keyboard.add_hotkey` fires on every repeated key-down, and its callbacks ran on the keyboard listener thread.
**Do:** `dit/hotkey.py` works on raw down/up events: repeats are ignored (a binding is "down" until its key-up; a key-down after 0.6s without repeats counts as a fresh press in case a key-up was missed), tap vs hold is decided on release (hold >= 0.4s = push-to-talk / peek-while-held), Esc cancels via the same ordered worker queue, and every action runs on one worker thread. Covered by the self-test.
**Refs:** `dit/hotkey.py`, `dit/selftest.py`

## 23. Card art is built on the UI thread: keep it cheap — verified
**What:** The first mechanical skin took ~200 ms to build each new card (shading a 4x-supersampled plate), i.e. a visible hitch every time a card appeared or morphed (listening -> understanding -> queued).
**Do:** Supersample only the silhouette, downsample it, then do gradients/bevels/edges at 1x (`_shade(..., ss=SS)`): ~16 ms per plate, ~8 ms per cog. Per-frame cost while moving is ~1.7 ms/card. Re-measure if you add effects.
**Refs:** `dit/ui/paper.py::_shade`
