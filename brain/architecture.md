# Architecture: D^it

Two voice routes share one audio + Whisper pipeline; a context watcher runs alongside.

```
Ctrl+Alt+D ─┐                                            ┌─► dit.injector      paste into focused app
            ├─► dit.hotkey ─► dit.engine ─► audio ─► STT ┤
Ctrl+Alt+T ─┘   (route)       (route)                    └─► TaskManager.handle_command
Ctrl+Alt+Q ───► TaskManager.show_peek                              │
                                                                   ├─ rules (instant) ─► store ─► card
                                                                   └─ OpenRouter (background refine / resolve)

dit.watch.watcher (1s poll: foreground exe + title, browser tab URL via UI Automation, idle time)
      └─► Sessionizer (settle 8s, idle 120s) ─► TaskManager.on_segment_start/end/tick
                                                     ├─ ContextLinker: cache ─► word overlap ─► AI (dwell ≥45s, cached)
                                                     ├─ linked task dwell ≥20s ─► Active (previous Active ─► Paused)
                                                     ├─ away from last task ≥150s ─► "Wrapped up?" nudge card
                                                     └─ back to a paused task after ≥10m ─► "Picking up" card

dit.ui.host (own thread, Win32 layered window, top-right) ◄── TaskManager via presenter (CardContent)
dit.tasks.store (SQLite in %LOCALAPPDATA%\DictateIt\dictateit.db)
```

## Dictation components (unchanged behaviour)
1. **Audio Recorder (`dit/audio.py`)** — 16 kHz mono float32 via `sounddevice`, in memory. Also keeps a smoothed `level` for the listening card's live bars.
2. **Speech routing (`DictationEngine._transcribe`)** — Groq Whisper large-v3 (`dit/cloud_stt.py`) for routes in `stt_cloud_routes` when `GROQ_API_KEY` is set; silent clips are dropped by local Silero VAD before upload; any Groq failure falls back to local. Both engines get a vocabulary (open/recent task titles, projects, `custom_vocabulary`): Groq as `prompt`, local as `hotwords`; task commands use `task_beam_size` 5. Timing log names the engine.
   **Transcriber (`dit/transcriber.py`)** — `faster-whisper` loaded once (CUDA float16, CPU int8 fallback). Forces `HF_HUB_DISABLE_XET=1` (landmine #9).
3. **Injector (`dit/injector.py`)** — clipboard + `Ctrl+V`, modifier flush, focus restore.
4. **Hotkeys (`dit/hotkey.py`)** — record bindings (dictate, task) follow toggle/PTT mode; action bindings (peek) just fire.
5. **Engine (`dit/engine.py`)** — `start_dictation(route)`. The route is captured at start and carried through `_process_utterance`; `task` hands the transcript to `TaskManager.handle_command` instead of injecting. Timing log adds `Intent:` for the task route.

## App shell
- **`dit/launcher.py`** — `--install`: branded `bin/DictateIt.exe`, Start Menu shortcut, Task Scheduler logon task; `main.SingleInstance` (named mutex + show event).

## Learning
- `aliases` table: phrases you used for a task (from "Which one?" picks and AI resolutions) — part of `text.task_text`, so they match by rules next time. `vocab` table: names from every task title (`text.vocabulary_terms`) → STT hints. `_user_context()` gives the intent AI recent windows/minutes, tasks finished today, current window.

## Task components
- **`dit/tasks/store.py`** — schema migrations via `MIGRATIONS` (ALTER TABLE on open); tasks (incl. `last_url` for reopening), task_events (history), segments (context timeline, pruned after 30 days), context_links (ctx_key → task, with source rule/ai/user and a `tasks_sig` so "no task" answers are re-asked after new tasks appear), ai_usage (daily counter).
- **`dit/tasks/intents.py`** — deterministic parser (add/complete/remove/pause/wait/start/peek, priority words, "yes it's done" → pending nudge task) + validation of AI JSON.
- **`dit/tasks/manager.py`** — the only place that changes task state. Rules first; `add` is applied instantly and refined by the AI in the background (or withdrawn if the AI says it was a command). Owns the watcher callbacks, sessions, nudge candidates and focus-time accounting.
- **`dit/tasks/presenter.py`** — all card wording; builds `CardContent`.
- **`dit/tasks/system.py`** — wires store, card host, AI client, manager and watcher.

## Context components
- **`dit/watch/window.py`** — `GetForegroundWindow`, title, class, exe (`QueryFullProcessImageNameW`), `GetLastInputInfo`, `SHQueryUserNotificationState` (no nudges during full-screen/presentation/Focus).
- **`dit/watch/browser.py`** — active-tab URL from the browser address bar via UI Automation (`comtypes`): first Edit control for Chromium, `urlbar-input` for Firefox; element cached per window (~0.2ms per read). `clean_url` keeps `scheme://host/path` only.
- **`dit/watch/context.py`** — title (+ URL) → `Context(app, label, workspace, branch, key, url, site, private)`. Browsers key by page address, editors by workspace, so a re-titled doc or a file switch inside a repo stays one context.
- **`dit/watch/sessionizer.py`** — tells "switched apps" from "switched work": a window must hold focus `settle_s` to start a segment; idle closes the segment at the moment input stopped.

## AI components
- **`dit/ai/groq.py`** — `GroqChatClient` (gpt-oss-20b → qwen → gpt-oss-120b, JSON mode, low reasoning, usage synced from `x-ratelimit-*` headers) and `ChainClient` (Groq first, OpenRouter second) which the manager/linker see as one client.
- **`dit/ai/openrouter.py`** — JSON-only chat, `reasoning` off, fallback model list, daily budget shared with OpenRouter's own count (`/api/v1/key`), 429 cooldown, bad key → disabled.
- **`dit/ai/prompts.py`** — every byte sent to OpenRouter is built here (auditable).
- **`dit/ai/linker.py`** — tiered linking; the AI tier may use at most `ai_link_share` of the daily budget so voice commands always have calls left.

## Card UI
- **`dit/ui/win32.py`** — layered popup (`WS_EX_LAYERED|TOPMOST|TOOLWINDOW|NOACTIVATE`), `UpdateLayeredWindow` with premultiplied BGRA, `MA_NOACTIVATE` on click, per-thread DPI awareness.
- **`dit/ui/paper.py`** — default mechanical skin (`card_style: "paper"`, palette `paper_theme`): a plate with a stub-tooth rack (20° pressure angle) on its straight bottom edge meshing with a spoked pinion under it. Rack pitch = cog circular pitch (2πR/N), a rack gap sits over the cog's top tooth at rest, and the cog turns by exactly travel/R. Art is anti-aliased at 4x but shaded at 1x (~16 ms per new card, built on the UI thread). Cog rolls in → rack drives the plate out → retract; done dispenses left; removed tears and drops; listening jiggles the rack with mic level. `handles_motion` tells the host not to slide/scale.
- **`dit/ui/cards.py`** — Pillow renderer: cached shadow/glass/border bases per height, supersampled badges with stroke animations, staggered text, strike-through, shimmer, level bars, particles, buttons.
- **`dit/ui/host.py`** — UI thread, command queue, stack with springs, enter/morph/exit choreography, hover-pauses-timer, click dispatch (off-thread). **Groups** (`show_group`): the queue peek is one capsule per task, cascading in/out, sharing one timer. Reduced motion → fades only.
- **`dit/ui/theme.py`** — dark/light, high contrast (system colours, 2px borders, no transparency), animation preference, screen-reader flag. **`dit/ui/a11y.py`** speaks card text via SAPI when a screen reader is on. **`dit/ui/lottie.py`** — optional icon animations from `assets/animations/`.
