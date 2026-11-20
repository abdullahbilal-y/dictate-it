# Card animations (Lottie)

Drop Lottie `.json` files here to replace the built-in icon animation on the task cards.
Anything missing falls back to the drawn icon, so you can add them one at a time.

| File | Plays on | Loops |
| :--- | :--- | :---: |
| `logo.json` | **Brand mark.** Tray icon (last frame), the startup "DictateIt is ready" card, and the listening badge unless `listening.json` exists | no (plays once, holds) |
| `task_added.json` | "Queued" card (task captured) | no |
| `task_done.json` | "Done" card (strike-through + dissolve) | no |
| `task_removed.json` | "Removed" card (collapse) | no |
| `listening.json` | "Listening for a task" (while you speak) | yes |
| `thinking.json` | "Understanding" (while the transcript is parsed) | yes |
| `nudge.json` | "Wrapped up?" question | no |
| `resume.json` | "Picking up" (back to an interrupted task) | no |
| `paused.json`, `waiting.json`, `active.json` | status change cards | no |

## Format

- **Square artboard, transparent background.** Artwork is auto-cropped to its visible content (across all
  frames), so padding on the canvas is fine. It's shown in the card's 36×36 icon slot (×1.25–2 on scaled
  displays), so keep shapes bold enough to read small.
- **Plays from frame 0 the moment the card appears**, then holds the last frame. Keep one-shot clips to
  about 0.4–1s; the text starts fading in at ~0.05s.
- **Draw in the light palette** (`#7C3AED` violet, `#16A34A` green, `#D97706` amber, `#E11D48` rose,
  `#0284C7` sky, `#64748B` slate). On dark cards/taskbars those exact colours are swapped for the dark
  palette (`#A78BFA`, `#4ADE80`, `#FBBF24`, `#FB7185`, `#38BDF8`, `#94A3B8`); other colours are kept.
- Shapes, strokes, fills, trim paths and masks render fine (rlottie). Avoid image layers, expressions
  and text layers.
- Exporters that write `"ty"` as the last key of each object are fine: the loader reorders keys (rlottie
  otherwise renders such files as fully transparent; landmine #17).

## Brand

`assets/brand/logo-dark.svg` / `logo-light.svg` are the static logo for dark/light backgrounds (README,
docs, store listings). The app itself uses `logo.json`, so there's no SVG renderer dependency.

## Preview

```powershell
python main.py --demo-ui
```

The log prints `[UI] Loaded Lottie 'logo.json' for listening: 121 frames @ 120fps (dark palette)` for each
file it picks up, or a warning if a file fails to load.
