# Glossary: D^it

- **D^it**: Dictate It (^ = Ctrl, ⇧ = Shift, D = D key).
- **STT**: Speech-to-Text.
- **faster-whisper**: CTranslate2-based implementation of OpenAI's Whisper model, up to 4x faster with lower memory usage.
- **Injection**: Inserting transcribed text into the currently active target window.
- **Toggle Mode**: Single press starts recording; second press stops, transcribes, and injects.
- **Push-to-Talk (PTT)**: Holding hotkey records; releasing hotkey stops, transcribes, and injects.
- **VAD**: Voice Activity Detection.
- **Route**: what a recording is for — `dictate` (paste) or `task` (task command).
- **Context**: app + cleaned window title (+ editor workspace) of the foreground window.
- **Segment**: a stretch of time in one context, started only after it held focus for `settle_s`.
- **Session**: a focus run on one task (consecutive linked segments); its length decides whether leaving it earns a nudge.
- **Nudge**: the single "Wrapped up?" card asked after you leave a task's context for `nudge_after_s`.
- **Link**: ctx_key → task mapping, from `rule` (word overlap), `ai`, or `user` (you said "working on X" there).
- **Refine**: background AI pass that cleans a just-captured task, or withdraws it if it was really a command.
- **Card**: a top-right layered-window notification; `CardContent` describes it, `presenter.py` writes its words.
- **Capsule**: a compact, fully rounded card; the queue peek shows one per task as a card **group**.
