"""Lottie JSON for card icons and the app logo. Drop files in assets/animations/ (see README there).

Loading normalises exporter quirks before rlottie sees the file:
  * "ty" first: rlottie parses in stream order and silently renders NOTHING when an object's "ty" comes after
    its other keys (some exporters write it last). Reordering fixes it without touching the source file.
  * palette: files drawn in the light accent palette get the matching dark accents on dark backgrounds.
  * crop: artwork that only fills part of its canvas is cropped to its content so it reads at icon size."""
import json
import os

from PIL import Image

# card kind -> candidate file names (first match wins). logo.json is the brand mark: it stands in for the
# listening badge and the startup card when no dedicated file exists.
SLOTS = {
    "listening": ("listening.json", "logo.json"),
    "hello": ("hello.json", "logo.json"),
    "thinking": ("thinking.json",),
    "queued": ("task_added.json", "queued.json"),
    "done": ("task_done.json", "done.json"),
    "removed": ("task_removed.json", "removed.json"),
    "nudge": ("nudge.json",),
    "resume": ("resume.json",),
    "paused": ("paused.json",),
    "waiting": ("waiting.json",),
    "active": ("active.json",),
}
LOOPING = {"listening", "thinking"}   # only for dedicated files; the logo always plays once and holds

# Light-palette accent -> dark-palette accent (mirrors theme.LIGHT_ACCENTS / DARK_ACCENTS).
LIGHT_TO_DARK = {"7c3aed": "a78bfa", "16a34a": "4ade80", "d97706": "fbbf24", "e11d48": "fb7185",
                 "0284c7": "38bdf8", "64748b": "94a3b8"}


def _ty_first(node):
    if isinstance(node, dict):
        return {k: _ty_first(node[k]) for k in sorted(node, key=lambda k: k != "ty")}
    if isinstance(node, list):
        return [_ty_first(x) for x in node]
    return node


def _hex(rgb):
    return "".join(f"{round(max(0.0, min(1.0, c)) * 255):02x}" for c in rgb[:3])


def _recolor(node, mapping):
    """Swap solid fill/stroke colours (`"c": {"k": [r, g, b(, a)]}`) whose hex is in mapping."""
    if isinstance(node, dict):
        if node.get("ty") in ("fl", "st") and isinstance(node.get("c"), dict):
            k = node["c"].get("k")
            if isinstance(k, list) and len(k) >= 3 and all(isinstance(v, (int, float)) for v in k):
                new = mapping.get(_hex(k))
                if new:
                    node["c"]["k"] = [int(new[i:i + 2], 16) / 255 for i in (0, 2, 4)] + list(k[3:])
        for v in node.values():
            _recolor(v, mapping)
    elif isinstance(node, list):
        for v in node:
            _recolor(v, mapping)


def load_lottie(path: str, dark: bool):
    from rlottie_python import LottieAnimation
    with open(path, encoding="utf-8") as f:
        data = _ty_first(json.load(f))
    if dark:
        _recolor(data, LIGHT_TO_DARK)
    return LottieAnimation.from_data(json.dumps(data))


def content_box(anim, probe=256):
    """Union of non-transparent pixels over the whole clip, as fractions of the canvas, squared and padded."""
    total = anim.lottie_animation_get_totalframe()
    box = None
    for i in range(0, total, max(1, total // 12)):
        bb = anim.render_pillow_frame(frame_num=i, width=probe, height=probe).getchannel("A").getbbox()
        if bb:
            box = bb if box is None else (min(box[0], bb[0]), min(box[1], bb[1]), max(box[2], bb[2]), max(box[3], bb[3]))
    if not box:
        return None
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    side = max(box[2] - box[0], box[3] - box[1]) * 1.06
    return tuple(v / probe for v in (cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2))


def render_frames(anim, size: int, crop=True, supersample=2):
    total = anim.lottie_animation_get_totalframe()
    box = content_box(anim) if crop else None
    if box:
        frac = box[2] - box[0]
        canvas = max(size, int(size * supersample / frac))
    else:
        canvas = size * supersample
    frames = []
    for i in range(total):
        img = anim.render_pillow_frame(frame_num=i, width=canvas, height=canvas).convert("RGBA")
        if box:
            img = img.crop(tuple(int(round(v * canvas)) for v in box))
        frames.append(img.resize((size, size), Image.LANCZOS))
    return frames


class LottieClip:
    def __init__(self, frames, fps, loop):
        self.frames = frames
        self.fps = fps
        self.loop = loop

    def frame_at(self, elapsed: float):
        if not self.frames:
            return None
        idx = int(max(0.0, elapsed) * self.fps)
        idx = idx % len(self.frames) if self.loop else min(idx, len(self.frames) - 1)
        return self.frames[idx]


class LottieLibrary:
    def __init__(self, directory: str):
        self.directory = directory
        self.dark = True
        self._clips = {}
        self._failed = set()
        try:
            from rlottie_python import LottieAnimation  # noqa: F401
            self._available = True
        except Exception as e:
            print(f"[UI] rlottie unavailable ({e}); Lottie icons disabled, using built-in icons.")
            self._available = False

    def path_for(self, kind: str):
        for name in SLOTS.get(kind, ()):
            path = os.path.join(self.directory, name)
            if os.path.isfile(path):
                return path
        return None

    def clip(self, kind: str, size_px: int):
        """Pre-rendered frames for this card kind at this pixel size, or None (fall back to drawn icon)."""
        key = (kind, size_px, self.dark)
        if key in self._clips:
            return self._clips[key]
        path = self.path_for(kind) if self._available and kind not in self._failed else None
        if not path:
            self._clips[key] = None
            return None
        try:
            anim = load_lottie(path, self.dark)
            fps = anim.lottie_animation_get_framerate() or 30
            frames = render_frames(anim, size_px)
            if not any(f.getchannel("A").getbbox() for f in frames[-3:]):
                raise ValueError("renders fully transparent")
            loop = kind in LOOPING and os.path.basename(path) != "logo.json"
            clip = LottieClip(frames, fps, loop)
            print(f"[UI] Loaded Lottie '{os.path.basename(path)}' for {kind}: {len(frames)} frames @ {fps:.0f}fps"
                  f"{' (dark palette)' if self.dark else ''}")
        except Exception as e:
            print(f"[UI] Lottie '{path}' failed to load ({e}); using built-in icon.")
            self._failed.add(kind)
            clip = None
        self._clips[key] = clip
        return clip


def render_logo(directory: str, size: int, dark: bool):
    """Final frame of logo.json as a still image (tray icon), or None if there's no usable logo."""
    path = os.path.join(directory, "logo.json")
    if not os.path.isfile(path):
        return None
    try:
        anim = load_lottie(path, dark)
        last = anim.lottie_animation_get_totalframe() - 1
        box = content_box(anim)
        canvas = size * 6
        img = anim.render_pillow_frame(frame_num=last, width=canvas, height=canvas).convert("RGBA")
        if box:
            img = img.crop(tuple(int(round(v * canvas)) for v in box))
        img = img.resize((size, size), Image.LANCZOS)
        return img if img.getchannel("A").getbbox() else None
    except Exception as e:
        print(f"[UI] Logo '{path}' failed to render ({e}); using the built-in tray icon.")
        return None
