# Operations & Runbook: D^it

## Prerequisites
- Windows 10/11, Python 3.10+
- `pip install -r requirements.txt` (faster-whisper, sounddevice, numpy, pyperclip, keyboard, pystray, pillow, requests, pywin32, rlottie-python, comtypes)
- Microphone input device.
- Optional: `.env` with `OPENROUTER_API_KEY=...` (copy `.env.example`). The key is also read from the user environment (`setx`). Never put it in `config.json`.

## Running D^it
```powershell
python main.py --install       # build bin/DictateIt.exe, Start Menu entry, start at sign-in (logon task)
python main.py                 # dictation + tasks + context watcher, tray icon
python main.py --mode ptt      # Push-to-Talk for both dictation and task keys
python main.py --no-watch      # tasks by voice, no app-context watching
python main.py --no-tasks      # plain dictation only
python main.py --test          # REQUIRED before committing: Whisper, mic, chimes, task logic, context parsing, nudge simulation, card render
python main.py --demo-ui       # plays every card animation on screen (use to check Lottie files)
python main.py --task "add finish the november report"   # task command as text, real cards, no voice
python tools/stt_bench.py [--groq]   # STT word-error bench on real task phrases (SAPI-synthesised audio)
```

Hotkeys (configurable in `config.json`): `Ctrl+Alt+D` dictate · `Ctrl+Alt+T` task command · `Ctrl+Alt+Q` show queue.

## Data
- Task DB: `%LOCALAPPDATA%\DictateIt\dictateit.db` (SQLite, WAL). Segments older than 30 days are pruned on startup.
- To test without touching the real DB, point `LOCALAPPDATA` at a temp folder for that process.
- Audio leaves the machine only with `GROQ_API_KEY` set, only for routes in `stt_cloud_routes` (default: task commands; tray toggles), and only if local Silero VAD detects speech (trimmed to the speech span).
- What leaves the machine (only with a key): the task-command transcript, open task titles/projects/status, and for linking the app name + cleaned window title + editor folder name + browser tab address without query/fragment. Never dictation audio/text (unless "Groq speech for dictation" is ticked), screenshots, page/file contents, private/incognito windows or `private_apps`. All payloads are built in `dit/ai/prompts.py`. Set `read_browser_urls: false` in `config.json` to keep addresses out entirely.

## Observability
- Tray/startup launches (`pythonw`, no console) log to `%LOCALAPPDATA%\DictateIt\dictateit.log`, with `faulthandler` on so native crashes leave a trace. The file resets past 5 MB. Console launches print to the terminal as before.
- `[D^it Turn #n]` timing: `Audio | STT | Inject` (dictation) or `Audio | STT | Intent` (task route).
- `[Tasks]` intent + source (`rules`, `ai (...)`, `+ ai refining`), status changes with `via` (voice/card/tray/context).
- `[Context] -> App: label [linked #id via words/ai/user]`, `[AI] purpose: model ms -> ok (used/budget)`.
- `[AI] OpenRouter free tier: x/50 used today` at startup (synced from `/api/v1/key`).

## Troubleshooting
1. **Stuck at "Loading Whisper"** — see landmine #9 (stop the instance, delete `*.incomplete` blobs).
2. **CUDA / CTranslate2 device error** — falls back to CPU int8 automatically.
3. **Hotkey not triggering in elevated windows** — UAC blocks hooks into elevated apps; run as Administrator if needed.
4. **Empty transcription** — check default mic; `python -m sounddevice`.
5. **AI says "budget" / "rate limited"** — free tier exhausted or upstream congested; rules keep working. Tray shows calls left.
6. **No nudges** — they're suppressed during full-screen apps, presentations and Focus; at most one per `nudge_cooldown_s`.
