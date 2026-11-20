"""Renders the README media from the real card renderer (no screen capture):

    docs/media/cards.gif    the gear train feeding cards out: listening -> queued, the queue stack, done + stamp
    docs/media/themes.png   the five mechanical themes

    python tools/make_media.py
"""
import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from dit.tasks import presenter
from dit.tasks.models import Task
from dit.ui.host import Card
from dit.ui.paper import PaperRenderer, THEMES
from dit.ui.theme import detect_theme

OUT = os.path.join(ROOT, "docs", "media")
FPS = 25
W, H = 620, 400
T0 = 1_000_000.0


def backdrop(w, h, dark=True, accent=(124, 58, 237)):
    top, bottom = ((22, 23, 29), (34, 36, 44)) if dark else ((236, 238, 243), (222, 225, 232))
    g = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    rgb = np.array(top, np.float32) * (1 - g) + np.array(bottom, np.float32) * g
    img = Image.fromarray(np.repeat(rgb, w, axis=1).astype(np.uint8), "RGB").convert("RGBA")
    glow = Image.new("L", (w, h), 0)
    ImageDraw.Draw(glow).ellipse([-w * 0.2, h * 0.35, w * 0.5, h * 1.3], fill=40 if dark else 24)
    tint = Image.new("RGBA", (w, h), accent + (0,))
    tint.putalpha(glow.filter(ImageFilter.GaussianBlur(70)))
    img.alpha_composite(tint)
    return img


def tasks():
    now = T0
    report = Task(1, "Finish November financial report", "Financial reporting", "high", "ready", now, now,
                  focus_seconds=1520)
    eir = Task(2, "Check DP World EIRs and Jebel Ali port", "Port ops", "normal", "paused", now, now,
               last_active_at=time.time() - 900, last_context="Container status")   # card text uses the real clock
    amer = Task(3, "Call Amer about the EIR OCR model", None, "normal", "active", now, now, last_app="WhatsApp",
                last_context="Amer")
    deck = Task(4, "Draft Q4 roadmap deck", "Planning", "normal", "waiting", now, now)
    return report, eir, amer, deck


def make_gif(renderer):
    report, eir, amer, deck = tasks()
    level = lambda: 0.05 * abs(math.sin(TIME[0] * 9))

    # scene 1: listening -> understanding -> queued (same card, flips between states)
    c1 = Card(1, presenter.listening("ctrl+alt+t", "toggle"), T0 + 0.2, level_fn=level)
    c1.h.snap(renderer.height(c1.content))
    morphs = [(1.5, presenter.thinking("finish the november financial report, it's important")),
              (2.4, presenter.queued(report, 2, 4))]
    c1_exit = 4.6

    # scene 2: the queue (Ctrl+Alt+Q) as a column of gear-driven tickets
    peek = [Card(10 + i, content, T0 + 5.2 + i * 0.09) for i, (content, _) in
            enumerate(presenter.peek([amer, eir, report, deck], 2))]
    for c in peek:
        c.h.snap(renderer.height(c.content))
    peek_exit = 8.4

    # scene 3: done -> stamp -> dispensed
    c3 = Card(30, presenter.done(report), T0 + 9.3)
    c3.h.snap(renderer.height(c3.content))
    c3_exit = 11.7
    end = 12.6

    frames = []
    bg = backdrop(W, H)
    n = int(end * FPS)
    for i in range(n):
        t = i / FPS
        TIME[0] = t
        now = T0 + t
        frame = bg.copy()
        live = []
        if t >= 0.2 and t < c1_exit + 0.6:
            for at, content in morphs:
                if t >= at and c1.content is not content and (at, content) == max(
                        ((a, c) for a, c in morphs if t >= a), key=lambda ac: ac[0]):
                    c1.prev_layer, c1.prev_t0 = c1.last_content, now
                    c1.content, c1.content_t0 = content, now
                    c1.set_hold(now)
                    c1.h.snap(renderer.height(content))
            if t >= c1_exit and c1.exit_t0 is None:
                c1.exit_t0, c1.exit_style = T0 + c1_exit, "slide"
            live.append((c1, 18))
        if 5.0 <= t < peek_exit + 1.0:
            y = 8
            for k, c in enumerate(peek):
                if t >= peek_exit and c.exit_t0 is None:
                    c.exit_t0, c.exit_style = T0 + peek_exit + k * 0.06, "slide"
                live.append((c, y))
                y += int(c.h.value)
        if t >= 9.3:
            if t >= c3_exit and c3.exit_t0 is None:
                c3.exit_t0, c3.exit_style = T0 + c3_exit, "dissolve"
            live.append((c3, 18))
        for c, y in live:
            img = renderer.render(c, now)
            frame.alpha_composite(img, (W - img.width, y))
        frames.append(frame.convert("RGB"))
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "cards.gif")
    pal_frames = [f.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for f in frames]
    pal_frames[0].save(path, save_all=True, append_images=pal_frames[1:], duration=int(1000 / FPS), loop=0,
                       optimize=True, disposal=1)
    print(f"{path}: {len(frames)} frames, {os.path.getsize(path) / 1e6:.1f} MB")


def make_themes():
    report, *_ = tasks()
    theme = detect_theme()
    tiles = []
    for name, spec in THEMES.items():
        r = PaperRenderer(theme, 1.0, palette=name)
        c = presenter.queued(report, 2, 4)
        card = Card(1, c, T0 - 3)
        card.h.snap(r.height(c))
        img = r.render(card, T0)
        dark = sum(spec["plate"]) < 380 and name != "kraft"
        tile = backdrop(img.width + 20, img.height + 26, dark=dark)
        tile.alpha_composite(img, (20, 26))
        ImageDraw.Draw(tile).text((16, 8), spec["label"], fill=(200, 200, 210) if dark else (70, 72, 84))
        tiles.append(tile)
    from dit.ui.cards import CardRenderer
    r = CardRenderer(theme, 1.0)
    c = presenter.queued(report, 2, 4)
    card = Card(1, c, T0 - 3)
    card.h.snap(r.height(c))
    img = r.render(card, time.time())
    tile = backdrop(tiles[0].width, tiles[0].height, dark=True)
    tile.alpha_composite(img, (tile.width - img.width, 26 + (tiles[0].height - 26 - img.height) // 2))
    ImageDraw.Draw(tile).text((16, 8), "Glass (follows Windows light/dark)", fill=(200, 200, 210))
    tiles.append(tile)
    cols = 2
    tw, th = tiles[0].width, max(t.height for t in tiles)
    sheet = Image.new("RGBA", (tw * cols, th * math.ceil(len(tiles) / cols)), (0, 0, 0, 0))
    for i, tile in enumerate(tiles):
        sheet.alpha_composite(tile, ((i % cols) * tw, (i // cols) * th))
    path = os.path.join(OUT, "themes.png")
    sheet.save(path, optimize=True)
    print(f"{path}: {os.path.getsize(path) / 1e3:.0f} KB")


TIME = [0.0]

if __name__ == "__main__":
    make_gif(PaperRenderer(detect_theme(), 1.0, palette="graphite"))
    make_themes()
