"""Card content model + Pillow renderer. Everything is drawn in physical pixels (scale = dpi / 96)."""
import math
import random
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageChops

from .anim import clamp, progress, ease_out_cubic, ease_out_back, ease_in_out_cubic, pulse, mix, with_alpha

FONT_DIR = "C:/Windows/Fonts/"
GLYPHS = {"mic": "\uE720", "pause": "\uE769", "play": "\uE768", "clock": "\uE823", "history": "\uE81C",
          "list": "\uE8FD", "question": "\uE897", "info": "\uE946", "stopwatch": "\uE916"}

# Logical layout (multiplied by scale)
CARD_W = 356
MARGIN = 22         # transparent room around the card for the shadow
RADIUS = 14
PAD_X = 16
PAD_TOP = 15
PAD_BOTTOM = 15
BADGE = 36
TEXT_X = PAD_X + BADGE + 13
EYEBROW_H = 13
TITLE_LH = 20
META_LH = 17
BUTTON_H = 30
LEVEL_BARS_W = 30
# Capsules (queue peek): fully rounded pills, one per task
CAP_H = 54
CAP_H_SLIM = 40
CAP_BADGE = 30
CAP_PAD_X = 12


@dataclass
class CardContent:
    kind: str                       # queued, done, removed, listening, thinking, nudge, resume, paused, waiting, active, info, peek
    eyebrow: str
    title: str
    meta: str = ""
    icon: str = "check"             # check, x, mic, spinner, or a GLYPHS key
    buttons: tuple = ()             # ((action, label, primary), ...)
    capsule: bool = False           # compact pill (queue peek): badge, title, one meta line, status tag
    tag: str = ""                   # capsule: status tag on the right ("Now", "Paused 15m")
    tag_kind: str = ""              # capsule: colour of the tag/badge (defaults to kind)
    pulse: bool = False             # capsule: breathing halo around the badge (the task in progress)
    click_action: str = ""          # clicking the card body dispatches this action instead of just closing
    hold_s: Optional[float] = 3.2   # None = stays until replaced/dismissed
    exit_style: str = "slide"       # slide | dissolve | collapse
    strike: bool = False            # animate a strike-through across the title (done)
    fade_title: bool = False        # title fades to muted (removed)
    shimmer: bool = False           # light sweep across the title (thinking)
    title_muted: bool = False
    level_bars: bool = False        # live mic level (listening)
    celebrate: bool = False         # particle burst when the check lands (done)
    announce: str = ""              # screen-reader text
    instant: bool = False           # update in place: cross-fade text, don't replay entrance/badge animations
    _layout: dict = field(default=None, repr=False, compare=False)


def _load_font(file, size, variation=None):
    try:
        font = ImageFont.truetype(FONT_DIR + file, size)
        if variation:
            font.set_variation_by_name(variation)
        return font
    except Exception:
        fallback = {"Semibold Text": "seguisb.ttf", "Semibold Small": "seguisb.ttf"}.get(variation, "segoeui.ttf")
        return ImageFont.truetype(FONT_DIR + fallback, size)


class Fonts:
    def __init__(self, s):
        self.eyebrow = _load_font("SegUIVar.ttf", round(10.5 * s), "Semibold Small")
        self.title = _load_font("SegUIVar.ttf", round(15 * s), "Semibold Text")
        self.meta = _load_font("SegUIVar.ttf", round(12.5 * s), "Regular")
        self.button = _load_font("SegUIVar.ttf", round(12.5 * s), "Semibold Text")
        self.cap_title = _load_font("SegUIVar.ttf", round(14 * s), "Semibold Text")
        self.cap_meta = _load_font("SegUIVar.ttf", round(11.5 * s), "Regular")
        self.icon_mid = _load_font("SegoeIcons.ttf", round(13 * s))
        self.small = _load_font("SegUIVar.ttf", round(11.5 * s), "Regular")
        self.icon = _load_font("SegoeIcons.ttf", round(15 * s))
        self.icon_small = _load_font("SegoeIcons.ttf", round(11 * s))


def wrap(text, font, width, max_lines):
    words = (text or "").split()
    lines, line = [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if font.getlength(trial) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1] + " …"
    return [ellipsize(l, font, width) for l in lines] or [""]


def ellipsize(text, font, width):
    if font.getlength(text) <= width:
        return text
    while text and font.getlength(text + "…") > width:
        text = text[:-1]
    return text.rstrip() + "…"


def _poly_partial(points, t):
    """Points along a polyline up to fraction t of its total length (for drawing strokes)."""
    segs = [(points[i], points[i + 1]) for i in range(len(points) - 1)]
    lengths = [math.dist(a, b) for a, b in segs]
    total = sum(lengths)
    remaining = total * clamp(t)
    out = [points[0]]
    for (a, b), length in zip(segs, lengths):
        if remaining <= 0:
            break
        f = min(1.0, remaining / length) if length else 1.0
        out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
        remaining -= length
    return out


class CardRenderer:
    def __init__(self, theme, scale, lottie=None):
        self.theme = theme
        self.s = scale
        self.fonts = Fonts(scale)
        self.lottie = lottie
        self.w = round(CARD_W * scale)
        self.m = round(MARGIN * scale)
        self.img_w = self.w + 2 * self.m
        self._base_cache = OrderedDict()
        self._pill_cache = {}

    def px(self, v):
        return round(v * self.s)

    # ------------------------------------------------------------------ layout
    def layout(self, c: CardContent) -> dict:
        if c._layout and c._layout.get("scale") == self.s:
            return c._layout
        if c.capsule:
            c._layout = self._capsule_layout(c)
            return c._layout
        f = self.fonts
        text_w = self.w - self.px(TEXT_X) - self.px(18) - (self.px(LEVEL_BARS_W) if c.level_bars else 0)
        y = self.px(PAD_TOP)
        L = {"scale": self.s, "text_x": self.px(TEXT_X), "text_w": text_w, "eyebrow_y": y,
             "badge_x": self.px(PAD_X), "badge_y": self.px(PAD_TOP), "badge": self.px(BADGE),
             "radius": self.px(RADIUS)}
        y += self.px(EYEBROW_H)
        y += self.px(5)
        L["title_lines"] = wrap(c.title, f.title, text_w, 2)
        L["title_y"] = y
        y += self.px(TITLE_LH) * len(L["title_lines"])
        if c.meta:
            y += self.px(3)
            L["meta_y"] = y
            L["meta"] = ellipsize(c.meta, f.meta, text_w)
            y += self.px(META_LH)
        if c.buttons:
            y += self.px(11)
            L["buttons_y"] = y
            y += self.px(BUTTON_H)
        y += self.px(PAD_BOTTOM)
        L["height"] = max(y, self.px(BADGE + PAD_TOP + PAD_BOTTOM))
        c._layout = L
        return L

    def _capsule_layout(self, c: CardContent) -> dict:
        f = self.fonts
        h = self.px(CAP_H if c.meta else CAP_H_SLIM)
        badge = self.px(CAP_BADGE)
        text_x = self.px(CAP_PAD_X) + badge + self.px(11)
        tag_w = 0
        if c.tag:
            tag_w = int(self._tracked_width(c.tag.upper(), f.eyebrow)) + self.px(16)
        right_pad = self.px(14)
        text_w = self.w - text_x - right_pad - (tag_w + self.px(10) if tag_w else 0)
        title_h = self.px(18)
        meta_h = self.px(15) if c.meta else 0
        top = (h - title_h - meta_h) // 2
        return {"scale": self.s, "capsule": True, "height": h, "radius": h // 2, "badge": badge,
                "badge_x": self.px(CAP_PAD_X), "badge_y": (h - badge) // 2, "text_x": text_x, "text_w": text_w,
                "title_y": top, "title": ellipsize(c.title, f.cap_title, text_w),
                "meta_y": top + title_h, "meta": ellipsize(c.meta, f.cap_meta, text_w) if c.meta else "",
                "tag_w": tag_w, "tag_x": self.w - right_pad - tag_w}

    def _tracked_width(self, text, font):
        return sum(font.getlength(ch) + 0.9 * self.s for ch in text)

    def height(self, c: CardContent) -> int:
        return self.layout(c)["height"]

    # ------------------------------------------------------------------ surfaces
    def _rounded_mask(self, w, h, r, ss=3):
        big = Image.new("L", (w * ss, h * ss), 0)
        ImageDraw.Draw(big).rounded_rectangle([0, 0, w * ss - 1, h * ss - 1], radius=r * ss, fill=255)
        return big.resize((w, h), Image.LANCZOS)

    def base(self, h, accent_kind, L):
        """Shadow + glass body + border + accent wash, cached per height. Returns (image, body_mask)."""
        radius = L["radius"]
        glow_c = (L["badge_x"] + L["badge"] / 2, L["badge_y"] + L["badge"] / 2)
        key = (h, accent_kind, radius, glow_c)
        if key in self._base_cache:
            self._base_cache.move_to_end(key)
            return self._base_cache[key]
        th, m, w, s = self.theme, self.m, self.w, self.s
        iw, ih = self.img_w, h + 2 * m
        r = min(radius, h // 2)
        out = Image.new("RGBA", (iw, ih), (0, 0, 0, 0))
        if h <= 2:
            self._base_cache[key] = (out, Image.new("L", (iw, ih), 0))
            return self._base_cache[key]

        if th.shadow_alpha:
            # Two shadows: a wide soft ambient one and a tight contact one. Reads as "floating", not "pasted".
            for blur, alpha, dy in ((12 * s, th.shadow_alpha, 7 * s), (2.5 * s, th.shadow_alpha // 2, 1.5 * s)):
                sh = Image.new("L", (iw, ih), 0)
                ImageDraw.Draw(sh).rounded_rectangle([m, m + dy, m + w, m + h + dy], radius=r, fill=alpha)
                sh = sh.filter(ImageFilter.GaussianBlur(blur))
                out.alpha_composite(Image.merge("RGBA", (Image.new("L", (iw, ih), 0),) * 3 + (sh,)))

        body_mask = Image.new("L", (iw, ih), 0)
        body_mask.paste(self._rounded_mask(w, h, r), (m, m))

        body = Image.new("RGBA", (iw, ih), th.surface)
        if th.sheen[3]:
            grad = np.zeros((ih, iw), dtype=np.uint8)
            fade = np.clip(1 - (np.arange(ih) - m) / max(1, h * 0.55), 0, 1)
            grad[:] = (fade * th.sheen[3]).astype(np.uint8)[:, None]
            sheen = Image.new("RGBA", (iw, ih), th.sheen[:3] + (0,))
            sheen.putalpha(Image.fromarray(grad))
            body.alpha_composite(sheen)
        if not th.high_contrast:
            # Soft accent glow behind the badge gives each card kind its own colour identity.
            glow = Image.new("L", (iw, ih), 0)
            cx, cy = m + glow_c[0], m + glow_c[1]
            rad = self.px(46) * L["badge"] / self.px(BADGE)
            ImageDraw.Draw(glow).ellipse([cx - rad, cy - rad, cx + rad, cy + rad],
                                         fill=34 if th.name == "dark" else 22)
            glow = glow.filter(ImageFilter.GaussianBlur(self.px(26)))
            tint = Image.new("RGBA", (iw, ih), th.accent(accent_kind)[:3] + (0,))
            tint.putalpha(glow)
            body.alpha_composite(tint)
        body_alpha = ImageChops.multiply(body.getchannel("A"), body_mask)
        body.putalpha(body_alpha)
        out.alpha_composite(body)

        bw = max(1, round(th.border_width * s)) if th.high_contrast else 1
        inner = Image.new("L", (iw, ih), 0)
        if w > 2 * bw and h > 2 * bw:
            inner.paste(self._rounded_mask(w - 2 * bw, h - 2 * bw, max(1, r - bw)), (m + bw, m + bw))
        ring = ImageChops.subtract(body_mask, inner)
        border = Image.new("RGBA", (iw, ih), th.border[:3] + (0,))
        border.putalpha(ImageChops.multiply(ring, Image.new("L", (iw, ih), th.border[3])))
        out.alpha_composite(border)

        self._base_cache[key] = (out, body_mask)
        if len(self._base_cache) > 96:
            self._base_cache.popitem(last=False)
        return self._base_cache[key]

    def _pill(self, w, h, color):
        key = (w, h, color)
        if key not in self._pill_cache:
            img = Image.new("RGBA", (w, h), color[:3] + (0,))
            img.putalpha(ImageChops.multiply(self._rounded_mask(w, h, self.px(8)), Image.new("L", (w, h), color[3])))
            if len(self._pill_cache) > 64:
                self._pill_cache.clear()
            self._pill_cache[key] = img
        return self._pill_cache[key]

    # ------------------------------------------------------------------ badge
    def badge(self, c: CardContent, t: float, now: float, level: float, size: int = None):
        th, B, ss = self.theme, size or self.px(BADGE), 4
        accent = th.accent(c.tag_kind or c.kind)
        motion = not th.reduce_motion

        if self.lottie is not None and not c.capsule:
            clip = self.lottie.clip(c.kind, B)
            if clip is not None:
                frame = clip.frame_at(t)
                if c.kind != "listening":
                    return frame
                under = Image.new("RGBA", (B, B), (0, 0, 0, 0))
                boost = clamp(level * 6)
                halo = 0.55 + 0.45 * pulse(now, 1.6) if motion else 0.8
                rad = B / 2 * (0.70 + 0.30 * max(boost, halo * 0.6))
                ImageDraw.Draw(under).ellipse([B / 2 - rad, B / 2 - rad, B / 2 + rad, B / 2 + rad],
                                              fill=with_alpha(accent, 0.12 + 0.26 * boost))
                under.alpha_composite(frame)
                return under

        S = B * ss
        img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        stroke = max(2, round(2.2 * self.s * ss))
        inset = stroke

        if c.icon == "mic":
            halo = 0.55 + 0.45 * pulse(now, 1.6) if motion else 0.8
            boost = clamp(level * 6)
            rad = S / 2 * (0.72 + 0.28 * max(boost, halo * 0.6))
            d.ellipse([S / 2 - rad, S / 2 - rad, S / 2 + rad, S / 2 + rad], fill=with_alpha(accent, 0.16 + 0.22 * boost))
            d.ellipse([S * 0.16, S * 0.16, S * 0.84, S * 0.84], fill=with_alpha(accent, 0.28))
        elif c.icon == "check" and c.kind == "done":
            p = ease_out_back(progress(t, 0.05, 0.38)) if motion else 1.0
            rad = S / 2 * clamp(p, 0, 1.15) * 0.98
            d.ellipse([S / 2 - rad, S / 2 - rad, S / 2 + rad, S / 2 + rad], fill=accent)
        else:
            d.ellipse([0, 0, S - 1, S - 1], fill=with_alpha(accent, 0.18))

        if c.icon in ("check", "x"):
            ring_p = ease_in_out_cubic(progress(t, 0.08, 0.36)) if motion else 1.0
            if c.kind != "done" and ring_p > 0:
                d.arc([inset, inset, S - inset, S - inset], -90, -90 + 360 * ring_p, fill=accent, width=stroke)
            mark_p = ease_out_cubic(progress(t, 0.34, 0.24)) if motion else 1.0
            mark_color = th.surface[:3] + (255,) if c.kind == "done" else accent
            if mark_p > 0:
                if c.icon == "check":
                    pts = [(S * 0.30, S * 0.52), (S * 0.44, S * 0.66), (S * 0.71, S * 0.38)]
                    seg = _poly_partial(pts, mark_p)
                    if len(seg) > 1:
                        d.line(seg, fill=mark_color, width=stroke + ss, joint="curve")
                else:
                    a = _poly_partial([(S * 0.35, S * 0.35), (S * 0.65, S * 0.65)], clamp(mark_p * 2))
                    b = _poly_partial([(S * 0.65, S * 0.35), (S * 0.35, S * 0.65)], clamp(mark_p * 2 - 1))
                    for seg in (a, b):
                        if len(seg) > 1:
                            d.line(seg, fill=mark_color, width=stroke + ss)
        elif c.icon == "spinner":
            d.arc([inset, inset, S - inset, S - inset], 0, 360, fill=with_alpha(accent, 0.22), width=stroke)
            start = (now * 300) % 360 if motion else 0
            sweep = 70 + 50 * pulse(now, 1.1) if motion else 90
            d.arc([inset, inset, S - inset, S - inset], start, start + sweep, fill=accent, width=stroke)

        img = img.resize((B, B), Image.LANCZOS)
        glyph = GLYPHS.get(c.icon)
        if glyph:
            gd = ImageDraw.Draw(img)
            font = self.fonts.icon if B >= self.px(BADGE) else self.fonts.icon_mid
            gd.text((B / 2, B / 2), glyph, font=font, fill=accent, anchor="mm")
        return img

    # ------------------------------------------------------------------ text helpers
    def _eyebrow(self, d, x, y, text, color):
        tracking = 0.9 * self.s
        for ch in text.upper():
            d.text((x, y), ch, font=self.fonts.eyebrow, fill=color)
            x += self.fonts.eyebrow.getlength(ch) + tracking

    def _shimmer_text(self, layer, x, y, text, font, base, highlight, now):
        d = ImageDraw.Draw(layer)
        d.text((x, y), text, font=font, fill=base)
        w = int(font.getlength(text)) + 4
        h = self.px(TITLE_LH) + 4
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).text((0, 0), text, font=font, fill=255)
        span = w + self.px(120)
        cx = (now * 260 * self.s) % span - self.px(60)
        xs = np.arange(w)
        band = np.exp(-((xs - cx) / (38 * self.s)) ** 2)
        m = (np.asarray(mask, dtype=np.float32) * band[None, :]).astype(np.uint8)
        hl = Image.new("RGBA", (w, h), highlight[:3] + (0,))
        hl.putalpha(Image.fromarray(m))
        layer.alpha_composite(hl, (int(x), int(y)))

    # ------------------------------------------------------------------ full card
    def render(self, card, now: float) -> Image.Image:
        """Base + previous content cross-fading out + current content staggering in. Clipped to the body."""
        c = card.content
        th, s, m = self.theme, self.s, self.m
        h = max(0, int(round(card.h.value)))
        base, body_mask = self.base(h, c.tag_kind or c.kind, self.layout(c))
        img = base.copy()
        if h <= 4:
            return img

        content = self.content_layer(card, now, h)
        card.last_content = content
        merged = content
        if card.prev_layer is not None:
            fade = 1 - ease_out_cubic(progress(now, card.prev_t0, 0.16))
            if fade <= 0:
                card.prev_layer = None
            else:
                prev = Image.new("RGBA", img.size, (0, 0, 0, 0))
                src = card.prev_layer
                prev.paste(src.crop((0, 0, min(src.width, img.width), min(src.height, img.height))), (0, 0))
                prev.putalpha(prev.getchannel("A").point(lambda v: int(v * fade)))
                merged = prev
                merged.alpha_composite(content)
        merged = merged.copy() if merged is content else merged
        merged.putalpha(ImageChops.multiply(merged.getchannel("A"), body_mask))
        img.alpha_composite(merged)
        self._particles(img, card, now)
        return img

    def content_layer(self, card, now, h):
        c = card.content
        th, s, m = self.theme, self.s, self.m
        L = self.layout(c)
        t = now - card.content_t0 + (10.0 if c.instant else 0.0)
        motion = not th.reduce_motion
        layer = Image.new("RGBA", (self.img_w, h + 2 * m), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        accent = th.accent(c.tag_kind or c.kind)

        def stagger(i):
            if not motion:
                return 1.0, 0
            p = ease_out_cubic(progress(t, 0.04 + i * 0.06, 0.32))
            return p, round((1 - p) * 6 * s)

        if c.capsule:
            self._capsule_content(layer, d, card, L, t, now, accent, stagger)
            card.button_rects = []
            return layer

        # badge
        level = card.level_fn() if (c.level_bars and card.level_fn) else 0.0
        badge = self.badge(c, t, now, level)
        layer.alpha_composite(badge, (m + L["badge_x"], m + L["badge_y"]))

        x = m + L["text_x"]
        a0, dy0 = stagger(0)
        self._eyebrow(d, x, m + L["eyebrow_y"] + dy0, c.eyebrow, with_alpha(accent, a0))

        a1, dy1 = stagger(1)
        strike_p = 0.0
        if c.strike:
            strike_p = ease_in_out_cubic(progress(t, 0.42, 0.5)) if motion else 1.0
        fade_p = ease_out_cubic(progress(t, 0.3, 0.5)) if (c.fade_title and motion) else (1.0 if c.fade_title else 0)
        base_col = th.muted if c.title_muted else th.text
        col = mix(base_col, th.muted, max(strike_p * 0.85, fade_p * 0.8))
        ty = m + L["title_y"] + dy1
        lines = L["title_lines"]
        if c.shimmer and motion:
            for i, line in enumerate(lines):
                self._shimmer_text(layer, x, ty + i * self.px(TITLE_LH), line, self.fonts.title,
                                   with_alpha(th.muted, a1), th.text, now)
        else:
            for i, line in enumerate(lines):
                d.text((x, ty + i * self.px(TITLE_LH)), line, font=self.fonts.title, fill=with_alpha(col, a1))
        if strike_p > 0:
            widths = [self.fonts.title.getlength(l) for l in lines]
            remaining = sum(widths) * strike_p
            for i, (line, lw) in enumerate(zip(lines, widths)):
                if remaining <= 0:
                    break
                seg = min(lw, remaining)
                remaining -= seg
                xb = self.fonts.title.getbbox("x")
                ly = ty + i * self.px(TITLE_LH) + (xb[1] + xb[3]) / 2
                d.line([(x - self.px(1), ly), (x + seg + self.px(1), ly)], fill=accent, width=max(1, round(1.6 * s)))
        if c.meta:
            a2, dy2 = stagger(2)
            d.text((x, m + L["meta_y"] + dy2), L["meta"], font=self.fonts.meta, fill=with_alpha(th.muted, a2))

        if c.level_bars:
            self._level_bars(d, card, now, level, h)

        card.button_rects = []
        if c.buttons:
            a3, dy3 = stagger(3)
            bx = x
            by = m + L["buttons_y"] + dy3
            for action, label, primary in c.buttons:
                bw = int(self.fonts.button.getlength(label)) + self.px(28)
                hovered = card.hover_button == action
                if primary:
                    fill = mix(accent, (255, 255, 255, 255), 0.18) if hovered else accent
                    text_col = th.surface[:3] + (255,) if not th.high_contrast else th.surface
                else:
                    fill = th.button_hover if hovered else th.button
                    text_col = th.text
                if th.high_contrast and hovered:
                    fill = th.accent("queued")
                pill = self._pill(bw, self.px(BUTTON_H), with_alpha(fill, a3))
                layer.alpha_composite(pill, (int(bx), int(by)))
                if th.high_contrast:
                    d.rounded_rectangle([bx, by, bx + bw, by + self.px(BUTTON_H)], radius=self.px(8),
                                        outline=th.text, width=max(1, round(s)))
                d.text((bx + bw / 2, by + self.px(BUTTON_H) / 2), label, font=self.fonts.button,
                       fill=with_alpha(text_col, a3), anchor="mm")
                card.button_rects.append((action, (bx, by, bx + bw, by + self.px(BUTTON_H))))
                bx += bw + self.px(8)

        # Remaining-time hairline: tells you the card will leave on its own, pauses while hovered.
        if card.hold_fraction is not None and card.exit_t0 is None and h > self.px(20) and not c.capsule:
            frac = clamp(card.hold_fraction)
            x0, x1 = m + self.px(RADIUS), m + self.w - self.px(RADIUS)
            yb = m + h - max(2, round(2 * s))
            d.line([(x0, yb), (x0 + (x1 - x0) * frac, yb)], fill=with_alpha(accent, 0.55), width=max(1, round(2 * s)))
        return layer

    def _capsule_content(self, layer, d, card, L, t, now, accent, stagger):
        c, th, m = card.content, self.theme, self.m
        bx, by, B = m + L["badge_x"], m + L["badge_y"], L["badge"]
        if c.pulse and not th.reduce_motion:
            breath = pulse(now, 1.8)
            halo = B / 2 + self.px(2 + 4 * breath)
            cx, cy = bx + B / 2, by + B / 2
            d.ellipse([cx - halo, cy - halo, cx + halo, cy + halo], fill=with_alpha(accent, 0.22 * (1 - breath * 0.5)))
        layer.alpha_composite(self.badge(c, t, now, 0.0, size=B), (bx, by))

        x = m + L["text_x"]
        a0, dy0 = stagger(0)
        d.text((x, m + L["title_y"] + dy0), L["title"], font=self.fonts.cap_title, fill=with_alpha(th.text, a0))
        if L["meta"]:
            a1, dy1 = stagger(1)
            d.text((x, m + L["meta_y"] + dy1), L["meta"], font=self.fonts.cap_meta, fill=with_alpha(th.muted, a1))
        if c.tag:
            a2, _ = stagger(1)
            tw, tag_h = L["tag_w"], self.px(20)
            tx, ty = m + L["tag_x"], m + (L["height"] - tag_h) // 2
            layer.alpha_composite(self._pill(tw, tag_h, with_alpha(accent, 0.16 * a2)), (int(tx), int(ty)))
            self._eyebrow(d, tx + self.px(8), ty + (tag_h - self.px(13)) / 2, c.tag, with_alpha(accent, a2))

    def _level_bars(self, d, card, now, level, h):
        th, s, m = self.theme, self.s, self.m
        accent = th.accent(card.content.kind)
        n, bw, gap = 4, max(2, round(3 * s)), max(2, round(3 * s))
        x0 = m + self.w - self.px(18) - (n * bw + (n - 1) * gap)
        cy = m + self.px(PAD_TOP + BADGE / 2)
        boost = clamp(level * 9)
        for i in range(n):
            wobble = 0.5 + 0.5 * math.sin(now * (7 + i * 2.3) + i * 1.7)
            if th.reduce_motion:
                wobble = 0.5
            bh = self.px(4) + self.px(18) * clamp(0.12 + boost * (0.45 + 0.55 * wobble))
            x = x0 + i * (bw + gap)
            d.rounded_rectangle([x, cy - bh / 2, x + bw, cy + bh / 2], radius=bw / 2,
                                fill=with_alpha(accent, 0.45 + 0.55 * boost))

    # ------------------------------------------------------------------ particles
    def spawn_particles(self, card):
        if self.theme.reduce_motion or self.theme.high_contrast:
            return
        L = self.layout(card.content)
        cx = self.m + L["badge_x"] + L["badge"] / 2
        cy = self.m + L["badge_y"] + L["badge"] / 2
        rng = random.Random(card.id)
        accent = self.theme.accent(card.content.kind)
        palette = [accent, mix(accent, (255, 255, 255, 255), 0.45), self.theme.accent("queued")]
        card.particles = [
            (cx, cy, rng.uniform(0, 2 * math.pi), self.px(rng.uniform(18, 40)), self.px(rng.uniform(1.6, 3.0)),
             palette[i % len(palette)], rng.uniform(0.0, 0.08))
            for i in range(14)
        ]
        card.particles_t0 = card.content_t0 + 0.5

    def _particles(self, img, card, now):
        if not card.particles:
            return
        t = now - card.particles_t0
        if t < 0:
            return
        if t > 0.9:
            card.particles = []
            return
        d = ImageDraw.Draw(img)
        for cx, cy, ang, dist, size, col, delay in card.particles:
            p = clamp((t - delay) / 0.75)
            if p <= 0:
                continue
            e = ease_out_cubic(p)
            px = cx + math.cos(ang) * dist * e
            py = cy + math.sin(ang) * dist * e + self.px(6) * p * p
            r = size * (1 - 0.5 * p)
            d.ellipse([px - r, py - r, px + r, py + r], fill=with_alpha(col, 1 - p))
