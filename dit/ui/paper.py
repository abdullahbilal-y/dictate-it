"""Mechanical card skin: a plate with a gear rack along its straight bottom edge, driven by a pinion (cog) under it.

A real gear train: a big drive gear whose centre sits on the card's bottom line turns a small pinion, and the
pinion drives the rack on the plate. All three share one module (tooth size), so the rack pitch equals the
pinion's circular pitch (2*pi*R/N), the pinion turns by exactly travel/R, and the big gear turns the other way
at Np/Nb of that. Rest phases are chosen so a pinion tooth sits in a rack gap and in a big-gear gap.

Motion: the cog rolls in from the screen edge, then drives the plate out. Exit retracts it (cog turns back) and
rolls the cog away. Done = ink strike + stamp, then the plate is dispensed to the left. Removed = scribble, then
the plate tears loose and drops. Listening = the plate trembles with your voice (the cog follows).

Themes (`paper_theme`): graphite (default), blueprint, kraft, ivory, paper. Same interface as cards.CardRenderer
plus handles_motion so the host doesn't also slide/scale."""
import math
from collections import OrderedDict

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageChops

from .anim import clamp, progress, ease_out_cubic, ease_in_cubic, ease_in_out_cubic, ease_out_back
from .cards import CARD_W, MARGIN, CardContent, ellipsize, _load_font, FONT_DIR

SS = 4   # supersampling for crisp teeth and outlines
ADD, DED = 0.8, 1.0   # stub-tooth proportions (in modules): chunkier, more "cog" than full-depth teeth

DARK_ACCENTS = {
    "queued": "A78BFA", "listening": "A78BFA", "thinking": "A78BFA", "hello": "A78BFA", "peek": "A78BFA",
    "active": "38BDF8", "resume": "38BDF8", "done": "4ADE80", "removed": "FB7185", "paused": "FBBF24",
    "nudge": "FBBF24", "waiting": "94A3B8", "info": "94A3B8",
}
LIGHT_ACCENTS = {
    "queued": "7C3AED", "listening": "7C3AED", "thinking": "7C3AED", "hello": "7C3AED", "peek": "7C3AED",
    "active": "0284C7", "resume": "0284C7", "done": "16A34A", "removed": "E11D48", "paused": "D97706",
    "nudge": "D97706", "waiting": "64748B", "info": "64748B",
}

THEMES = {
    "graphite": {"label": "Graphite & brass", "plate": (44, 45, 51), "plate_hi": (66, 67, 76), "edge": (12, 12, 14),
                 "ink": (242, 238, 228), "meta": (166, 162, 150), "grain": (255, 255, 255, 8),
                 "metal": (196, 156, 80), "metal_hi": (250, 226, 160), "metal_lo": (104, 74, 26),
                 "metal_edge": (46, 33, 10), "accents": DARK_ACCENTS, "outline": 1.3, "shadow": 120},
    "blueprint": {"label": "Blueprint", "plate": (25, 72, 136), "plate_hi": (42, 98, 172), "edge": (196, 220, 255),
                  "ink": (240, 246, 255), "meta": (166, 196, 238), "grain": (255, 255, 255, 7),
                  "metal": (206, 218, 236), "metal_hi": (255, 255, 255), "metal_lo": (112, 132, 164),
                  "metal_edge": (16, 36, 74), "accents": DARK_ACCENTS, "outline": 1.3, "shadow": 110},
    "kraft": {"label": "Kraft & steel", "plate": (186, 146, 100), "plate_hi": (210, 174, 128), "edge": (58, 38, 20),
              "ink": (34, 22, 10), "meta": (88, 60, 32), "grain": (80, 50, 15, 26),
              "metal": (158, 162, 170), "metal_hi": (232, 236, 242), "metal_lo": (78, 82, 92),
              "metal_edge": (30, 32, 36), "accents": LIGHT_ACCENTS, "outline": 1.5, "shadow": 100},
    "ivory": {"label": "Ivory & silver", "plate": (246, 243, 235), "plate_hi": (255, 255, 252), "edge": (44, 52, 70),
              "ink": (24, 32, 52), "meta": (100, 108, 126), "grain": (0, 0, 0, 7),
              "metal": (184, 190, 200), "metal_hi": (248, 250, 252), "metal_lo": (104, 112, 128),
              "metal_edge": (38, 44, 58), "accents": LIGHT_ACCENTS, "outline": 1.3, "shadow": 90},
    "paper": {"label": "Cream paper (original)", "plate": (253, 235, 176), "plate_hi": (255, 244, 205),
              "edge": (26, 22, 16), "ink": (26, 22, 16), "meta": (112, 92, 56), "grain": (120, 90, 30, 22),
              "metal": (253, 235, 176), "metal_hi": (255, 249, 225), "metal_lo": (214, 186, 118),
              "metal_edge": (26, 22, 16), "accents": LIGHT_ACCENTS, "outline": 2.4, "shadow": 70},
}
DEFAULT_THEME = "graphite"


def _rgb(hexstr):
    return tuple(int(hexstr[i:i + 2], 16) for i in (0, 2, 4))


def _bezier(p0, p1, p2, p3, n=40):
    out = []
    for i in range(n + 1):
        t = i / n
        a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2, t ** 3
        out.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return out


def _shift(mask, dx, dy):
    out = Image.new("L", mask.size, 0)
    out.paste(mask, (dx, dy))
    return out


def _shade(mask, base, hi, lo, edge, bevel, edge_w, vertical=False, ss=1):
    """Metal/plate look from a silhouette: gradient body, light top-left bevel, dark bottom-right bevel, edge line.
    `mask` may be supersampled by `ss`: it's anti-aliased down first and all shading happens at 1x (~15x faster
    than shading the supersampled image; card art is built on the UI thread)."""
    if ss > 1:
        mask = mask.resize((mask.width // ss, mask.height // ss), Image.LANCZOS)
        bevel = max(1, round(bevel / ss))
        edge_w = max(1, round(edge_w / ss)) if edge_w else 0
    w, h = mask.size
    if vertical:
        g = np.linspace(0, 1, h, dtype=np.float32)[:, None].repeat(w, 1)
    else:
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        g = (xx / max(1, w) + yy / max(1, h)) / 2
    base_a, hi_a, lo_a = (np.array(c[:3], np.float32) for c in (base, hi, lo))
    top = base_a * 0.55 + hi_a * 0.45
    bottom = base_a * 0.62 + lo_a * 0.38
    rgb = top[None, None, :] * (1 - g[..., None]) + bottom[None, None, :] * g[..., None]
    img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    img.putalpha(mask)
    if bevel:
        light = ImageChops.subtract(mask, _shift(mask, bevel, bevel))
        dark = ImageChops.subtract(mask, _shift(mask, -bevel, -bevel))
        for band, col, alpha in ((light, hi, 150), (dark, lo, 170)):
            layer = Image.new("RGBA", (w, h), tuple(col[:3]) + (0,))
            layer.putalpha(band.point(lambda v, a=alpha: v * a // 255))
            img.alpha_composite(layer)
    if edge_w:
        eroded = mask.filter(ImageFilter.MinFilter(edge_w * 2 + 1))
        ring = ImageChops.subtract(mask, eroded)
        layer = Image.new("RGBA", (w, h), tuple(edge[:3]) + (0,))
        layer.putalpha(ring)
        img.alpha_composite(layer)
    return img


class MechFonts:
    def __init__(self, s):
        self.eyebrow = _load_font("SegUIVar.ttf", round(10 * s), "Semibold Small")
        try:
            self.title = ImageFont.truetype(FONT_DIR + "segoeprb.ttf", round(14 * s))
            self.cap_title = ImageFont.truetype(FONT_DIR + "segoeprb.ttf", round(12.5 * s))
        except OSError:
            self.title = _load_font("SegUIVar.ttf", round(15 * s), "Semibold Text")
            self.cap_title = _load_font("SegUIVar.ttf", round(13.5 * s), "Semibold Text")
        self.meta = _load_font("SegUIVar.ttf", round(11.5 * s), "Regular")
        self.button = _load_font("SegUIVar.ttf", round(11.5 * s), "Semibold Text")


class Art:
    """Pre-rendered plate (rack, text, buttons, shadow) and where the cog centre (pivot) sits relative to it."""

    def __init__(self, image, pivot, buttons, button_defs, title_box, layout):
        self.image = image
        self.pivot = pivot
        self.buttons = buttons
        self.button_defs = button_defs
        self.title_box = title_box
        self.layout = layout


class PaperRenderer:
    handles_motion = True
    exit_durations = {"slide": 0.5, "dissolve": 0.5, "collapse": 0.6}
    gap = 0

    def __init__(self, theme, scale, lottie=None, palette: str = DEFAULT_THEME):
        self.theme = theme
        self.s = scale
        self.lottie = lottie
        self.palette_name = palette if palette in THEMES else DEFAULT_THEME
        self.pal = THEMES[self.palette_name]
        self.fonts = MechFonts(scale)
        self.w = round(CARD_W * scale)
        self.m = round(MARGIN * scale)
        self.img_w = self.w + 2 * self.m
        self._art_cache = OrderedDict()
        self._gear_cache = {}
        self._stamp = None
        rng = np.random.default_rng(7)
        self._grain = Image.fromarray((rng.random((600, 600)) * 255).astype(np.uint8))

    def px(self, v):
        return round(v * self.s)

    def accent(self, kind, alpha=255):
        acc = self.pal["accents"]
        return _rgb(acc.get(kind, acc["queued"])) + (alpha,)

    # ------------------------------------------------------------------ layout
    def layout(self, c: CardContent) -> dict:
        if c._layout and c._layout.get("mech_scale") == self.s and c._layout.get("pal") == self.palette_name:
            return c._layout
        px = self.px
        if c.capsule:
            R, N, NB = px(12), 9, 18          # pinion radius/teeth, big gear teeth (same module => RB = 2R)
            rows = [("title", px(19))] + ([("meta", px(15))] if c.meta else [])
            pad_t, pad_b = px(8), px(7)
        else:
            R, N, NB = px(16), 10, 20
            rows = ([("eyebrow", px(14))] if c.eyebrow else []) + [("title", px(22))] + \
                   ([("meta", px(15))] if c.meta else [])
            pad_t, pad_b = px(10), px(8)
        mg = 2 * R / N                                   # gear module: pitch diameter / teeth
        pitch = math.pi * 2 * R / N                      # circular pitch = rack tooth spacing
        Hb = pad_t + sum(h for _, h in rows) + pad_b
        y_root = -R - DED * mg                           # rack root line (the plate's straight bottom edge)
        y_top = y_root - Hb
        btn_h = px(24) if c.buttons else 0
        top_extent = -y_top + px(2)
        # Big drive gear: centre on the card's bottom line, meshing with the pinion. The contact direction is
        # snapped to one of the pinion's tooth angles so a pinion tooth points straight into a big-gear gap.
        RB = mg * NB / 2
        C = R + RB
        step = 360 / N
        ideal = math.degrees(math.asin(max(-1.0, y_root / C)))
        phi = -90 + round((ideal + 90) / step) * step
        bx, by = C * math.cos(math.radians(phi)), C * math.sin(math.radians(phi))
        bottom_extent = max(R + ADD * mg, by + RB + ADD * mg) + px(4)
        if btn_h:
            bottom_extent = max(bottom_extent, -R + ADD * mg + px(8) + btn_h + px(4))
        gx = self.img_w - px(10) - (RB + ADD * mg) - bx  # whole train on screen, big gear by the edge
        L = gx - (self.m + px(2))                        # cog centre -> plate tip
        x_end = self.img_w - gx + px(10)                 # plate runs past the screen edge
        L_ = {"mech_scale": self.s, "pal": self.palette_name, "R": R, "N": N, "mg": mg, "pitch": pitch,
              "Hb": Hb, "y_root": y_root, "y_top": y_top, "rows": rows, "pad_b": pad_b, "btn_h": btn_h,
              "top": top_extent, "height": int(top_extent + bottom_extent), "gx": gx, "L": L, "x_end": x_end,
              "radius": 0, "RB": RB, "NB": NB, "phi": phi, "bx": bx, "by": by}
        c._layout = L_
        return L_

    def height(self, c: CardContent) -> int:
        return self.layout(c)["height"]

    # ------------------------------------------------------------------ plate geometry
    def _plate_outline(self, L_):
        R, mg, pitch, L = L_["R"], L_["mg"], L_["pitch"], L_["L"]
        y_r, y_t, x_end = L_["y_root"], L_["y_top"], L_["x_end"]
        tip = (-L, y_r)
        rise = _bezier(tip, (-L + 0.04 * L, y_r - 0.62 * L_["Hb"]), (-L + 0.20 * L, y_t), (-L + 0.42 * L, y_t))
        top = rise + [(x_end, y_t)]
        # rack teeth (20 degree pressure angle) hanging below the root line; a gap is centred over the cog (x=0)
        tan20 = math.tan(math.radians(20))
        y_tip = y_r + (ADD + DED) * mg
        w_root = pitch / 2 + 2 * DED * mg * tan20
        w_tip = max(pitch * 0.15, pitch / 2 - 2 * ADD * mg * tan20)
        x_start = -L + 0.30 * L
        k = math.floor(x_end / pitch - 0.5)
        bottom = [(x_end, y_r)]
        while (k + 0.5) * pitch - w_root / 2 > x_start:
            c = (k + 0.5) * pitch
            if c + w_root / 2 < x_end:
                bottom += [(c + w_root / 2, y_r), (c + w_tip / 2, y_tip), (c - w_tip / 2, y_tip), (c - w_root / 2, y_r)]
            k -= 1
        bottom.append(tip)
        return top + bottom, rise

    def _row_spans(self, L_, rise):
        right = L_["x_end"] - (self.img_w - L_["gx"]) - self.px(14)   # stop short of the screen edge
        xs = np.linspace(-L_["L"], right, 240)
        pts = np.array(rise + [(L_["x_end"], L_["y_top"])])
        tops = np.interp(xs, pts[:, 0], pts[:, 1])
        spans, y = [], L_["y_root"] - L_["pad_b"]
        for name, h in reversed(L_["rows"]):
            y_top = y - h
            ok = np.nonzero(tops <= y_top - self.px(3))[0]
            x0 = xs[ok[0]] if len(ok) else right - self.px(60)
            spans.append((name, y_top, h, (x0, right)))
            y = y_top
        return list(reversed(spans))

    # ------------------------------------------------------------------ plate art
    def _art(self, c: CardContent) -> Art:
        key = (id(c), self.palette_name)
        if key in self._art_cache:
            self._art_cache.move_to_end(key)
            return self._art_cache[key][1]
        L_ = self.layout(c)
        px, f, pal = self.px, self.fonts, self.pal
        L, y_t = L_["L"], L_["y_top"]
        pad = px(8)
        y_bottom = -L_["R"] + ADD * L_["mg"] + (px(8) + L_["btn_h"] + px(4) if L_["btn_h"] else px(2))
        W = int(L + L_["x_end"] + 2 * pad)
        H = int(y_bottom - y_t + 2 * pad)
        pivot = (L + pad, -y_t + pad)
        outline, rise = self._plate_outline(L_)

        mask = Image.new("L", (W * SS, H * SS), 0)
        ImageDraw.Draw(mask).polygon([((x + pivot[0]) * SS, (y + pivot[1]) * SS) for x, y in outline], fill=255)
        plate = _shade(mask, pal["plate"], pal["plate_hi"], pal["plate"], pal["edge"], bevel=SS,
                       edge_w=max(1, round(pal["outline"] * self.s * SS)), vertical=True, ss=SS)
        grain = self._grain.crop((0, 0, W, H)) if W <= 600 and H <= 600 else self._grain.resize((W, H))
        gr = pal["grain"]
        tex = Image.new("RGBA", (W, H), gr[:3] + (0,))
        tex.putalpha(ImageChops.multiply(grain.point(lambda v, a=gr[3]: v * a // 255), plate.getchannel("A")))
        plate.alpha_composite(tex)

        d = ImageDraw.Draw(plate)
        title_box = None
        for name, y_top, h, (x0, x1) in self._row_spans(L_, rise):
            X0, Y, width = x0 + pivot[0], y_top + pivot[1], x1 - x0
            if name == "eyebrow":
                self._tracked(d, X0, Y + px(1), c.eyebrow.upper(), self.accent(c.tag_kind or c.kind))
            elif name == "title":
                font = f.cap_title if c.capsule else f.title
                text = ellipsize(c.title, font, width)
                if c.capsule and c.tag and not c.meta:
                    tag = c.tag.upper()
                    tw = self._tracked_w(tag)
                    text = ellipsize(c.title, font, width - tw - px(10))
                    self._tracked(d, X0 + font.getlength(text) + px(10), Y + h / 2 - px(6), tag,
                                  self.accent(c.tag_kind or c.kind))
                d.text((X0, Y + h / 2), text, font=font, fill=pal["meta"] if c.title_muted else pal["ink"], anchor="lm")
                title_box = (x0, y_top + h / 2, x0 + font.getlength(text))
            elif name == "meta":
                x = X0
                if c.capsule and c.tag:
                    tag = c.tag.upper() + "  "
                    self._tracked(d, x, Y + h / 2 - px(6), tag, self.accent(c.tag_kind or c.kind))
                    x += self._tracked_w(tag)
                d.text((x, Y + h / 2), ellipsize(c.meta, f.meta, x1 + pivot[0] - x), font=f.meta, fill=pal["meta"],
                       anchor="lm")

        buttons = []
        if c.buttons:
            bx, by = -L * 0.70, -L_["R"] + ADD * L_["mg"] + px(8)
            for action, label, primary in c.buttons:
                bw = int(f.button.getlength(label)) + px(20)
                buttons.append((action, (bx, by, bx + bw, by + L_["btn_h"]), label, primary))
                bx += bw + px(6)
            for action, (x0, y0, x1, y1), label, primary in buttons:
                self._tag(d, (x0 + pivot[0], y0 + pivot[1], x1 + pivot[0], y1 + pivot[1]), label, primary, c, False)

        sh = plate.getchannel("A").filter(ImageFilter.GaussianBlur(max(1, self.s * 1.6)))
        shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        shadow.putalpha(sh.point(lambda v, a=pal["shadow"]: v * a // 255))
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        img.alpha_composite(shadow, (px(2), px(3)))
        img.alpha_composite(plate)

        art = Art(img, pivot, [(a, r) for a, r, _, _ in buttons], buttons, title_box, L_)
        self._art_cache[key] = (c, art)   # holding c keeps id(c) unique while cached
        if len(self._art_cache) > 48:
            self._art_cache.popitem(last=False)
        return art

    def _tracked(self, d, x, y, text, fill):
        for ch in text:
            d.text((x, y), ch, font=self.fonts.eyebrow, fill=fill)
            x += self.fonts.eyebrow.getlength(ch) + 0.9 * self.s

    def _tracked_w(self, text):
        return sum(self.fonts.eyebrow.getlength(ch) + 0.9 * self.s for ch in text)

    def _tag(self, d, box, label, primary, c, hovered):
        x0, y0, x1, y1 = box
        pal = self.pal
        fill = pal["ink"] if primary else pal["plate_hi"]
        text = pal["plate"] if primary else pal["ink"]
        if hovered:
            fill, text = self.accent(c.tag_kind or c.kind), (20, 20, 22)
        d.rounded_rectangle([x0, y0, x1, y1], radius=(y1 - y0) / 2, fill=fill, outline=pal["edge"],
                            width=max(1, round(1.2 * self.s)))
        d.text(((x0 + x1) / 2, (y0 + y1) / 2), label, font=self.fonts.button, fill=text, anchor="mm")

    # ------------------------------------------------------------------ cog
    def _gear(self, R, N, kind, windows_ok=True, collar_on=True):
        key = (R, N, kind, self.palette_name, windows_ok, collar_on)
        if key in self._gear_cache:
            return self._gear_cache[key]
        pal = self.pal
        mg = 2 * R / N
        ro, rr = R + ADD * mg, R - DED * mg
        size = int(2 * ro + self.px(10))
        c0 = size / 2 * SS
        k = SS
        tan20 = math.tan(math.radians(20))
        pitch = math.pi * 2 * R / N
        h_pitch = (pitch / 4) / R
        h_tip = max(0.02, (pitch / 2 - 2 * ADD * mg * tan20) / 2 / ro)
        h_root = (pitch / 2 + 2 * DED * mg * tan20) / 2 / rr
        pts = []
        for i in range(N):
            a = math.radians(-90) + i * 2 * math.pi / N   # a tooth points straight up at rest (into a rack gap)
            for ang, rad in ((a - h_root, rr), (a - h_pitch, R)):
                pts.append((c0 + rad * k * math.cos(ang), c0 + rad * k * math.sin(ang)))
            for t in np.linspace(-h_tip, h_tip, 4):
                pts.append((c0 + ro * k * math.cos(a + t), c0 + ro * k * math.sin(a + t)))
            for ang, rad in ((a + h_pitch, R), (a + h_root, rr)):
                pts.append((c0 + rad * k * math.cos(ang), c0 + rad * k * math.sin(ang)))
            nxt = a + 2 * math.pi / N
            for t in np.linspace(a + h_root, nxt - h_root, 4)[1:-1]:
                pts.append((c0 + rr * k * math.cos(t), c0 + rr * k * math.sin(t)))
        big = (size * SS, size * SS)
        mask = Image.new("L", big, 0)
        md = ImageDraw.Draw(mask)
        md.polygon(pts, fill=255)
        # spoke windows (see-through), rounded by blur + threshold
        windows = Image.new("L", big, 0)
        wd = ImageDraw.Draw(windows)
        r_out, r_in = (rr - 0.15 * R) * k, 0.36 * R * k
        n_spokes = 5 if R >= self.px(20) else 4
        span = 360 / n_spokes
        spoke_deg = math.degrees((0.24 * R) / ((r_out + r_in) / 2 / k))
        if windows_ok and r_out - r_in > 3 * k:
            for i in range(n_spokes):
                a0 = -90 + span / 2 + i * span + spoke_deg / 2
                a1 = -90 + span / 2 + (i + 1) * span - spoke_deg / 2
                wd.pieslice([c0 - r_out, c0 - r_out, c0 + r_out, c0 + r_out], a0, a1, fill=255)
            wd.ellipse([c0 - r_in, c0 - r_in, c0 + r_in, c0 + r_in], fill=0)
            windows = windows.filter(ImageFilter.GaussianBlur(0.07 * R * k)).point(lambda v: 255 if v > 128 else 0)
            mask = ImageChops.subtract(mask, windows)
        # bore with keyway
        bore = 0.12 * R * k
        md2 = ImageDraw.Draw(mask)
        md2.ellipse([c0 - bore, c0 - bore, c0 + bore, c0 + bore], fill=0)
        md2.rectangle([c0 - bore * 0.35, c0 - bore * 1.45, c0 + bore * 0.35, c0], fill=0)
        gear = _shade(mask, pal["metal"], pal["metal_hi"], pal["metal_lo"], pal["metal_edge"],
                      bevel=max(2, round(1.2 * self.s * k)), edge_w=max(1, round(pal["outline"] * self.s * k * 0.8)),
                      ss=k)
        # hub collar in the card's colour (drawn supersampled, then merged)
        collar = Image.new("RGBA", big, (0, 0, 0, 0))
        gd = ImageDraw.Draw(collar)
        rc = 0.36 * R * k
        if collar_on:
            gd.ellipse([c0 - rc, c0 - rc, c0 + rc, c0 + rc], outline=self.accent(kind),
                       width=max(2, round(0.08 * R * k)))
        gear.alpha_composite(collar.resize((size, size), Image.LANCZOS))
        sh = gear.getchannel("A").filter(ImageFilter.GaussianBlur(max(1, self.s * 1.4)))
        out = Image.new("RGBA", (size + self.px(4), size + self.px(5)), (0, 0, 0, 0))
        shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        shadow.putalpha(sh.point(lambda v, a=pal["shadow"]: v * a // 255))
        out.alpha_composite(shadow, (self.px(2), self.px(3)))
        out.alpha_composite(gear)
        self._gear_cache[key] = (out, size / 2)
        return self._gear_cache[key]

    def _stamp_img(self):
        if self._stamp is None:
            px = self.px
            size = px(46)
            big = Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))
            d = ImageDraw.Draw(big)
            col = self.accent("done", 235)
            lw = max(2, round(2.2 * self.s * SS))
            d.ellipse([lw, lw, size * SS - lw, size * SS - lw], outline=col, width=lw)
            inner = lw * 3
            d.ellipse([inner, inner, size * SS - inner, size * SS - inner], outline=col, width=max(1, lw // 2))
            font = ImageFont.truetype(FONT_DIR + "segoeprb.ttf", round(10.5 * self.s * SS))
            d.text((size * SS / 2, size * SS / 2), "DONE", font=font, fill=col, anchor="mm")
            img = big.resize((size, size), Image.LANCZOS).rotate(14, resample=Image.BICUBIC)
            rng = np.random.default_rng(3)
            a = np.asarray(img.getchannel("A"), dtype=np.float32) * (0.75 + 0.25 * rng.random((size, size)))
            img.putalpha(Image.fromarray(a.astype(np.uint8)))
            self._stamp = img
        return self._stamp

    # ------------------------------------------------------------------ motion
    def _motion(self, card, now, L_):
        """(plate_dx, drop, tilt, alpha, cog_dx). plate_dx > 0 = pulled back toward the edge."""
        c = card.content
        reduce = self.theme.reduce_motion
        R, mg = L_["R"], L_["mg"]
        travel = L_["L"] + (self.img_w - L_["gx"]) + self.px(8)
        cog_travel = (self.img_w - L_["gx"]) + R + ADD * mg + self.px(8)   # pinion is the leftmost gear
        if reduce:
            p = progress(now, card.enter_t0, 0.16)
            dx, alpha, cog_dx = 0.0, ease_out_cubic(p), 0.0
        else:
            roll = progress(now, card.enter_t0, 0.22)
            cog_dx = (1 - ease_out_cubic(roll)) * cog_travel
            p = progress(now, card.enter_t0 + 0.14, 0.6)
            e = ease_out_back(p, 0.7) if p < 1 else 1.0
            dx, alpha = (1 - e) * travel, clamp(p * 6)
            if c.level_bars and card.level_fn:            # the plate trembles with your voice; the cog follows
                lvl = clamp(card.level_fn() * 10)
                dx += self.px(5) * lvl * math.sin(now * 23)
            elif c.icon == "spinner":                     # thinking: a slow back-and-forth
                dx += self.px(3) * math.sin(now * 7)
        drop = tilt = 0.0
        if card.exit_t0 is not None:
            dur = self.exit_durations.get(card.exit_style, 0.5) if not reduce else 0.16
            p = progress(now, card.exit_t0, dur)
            if reduce:
                alpha *= 1 - p
            elif card.exit_style == "collapse":           # torn loose: falls and tilts
                drop = 0.5 * 2600 * self.s * (p * dur) ** 2
                tilt = 20 * ease_in_cubic(p)
                alpha *= 1 - ease_in_cubic(p)
            elif card.exit_style == "dissolve":           # done: dispensed out to the left
                dx -= ease_in_cubic(clamp(p / 0.8)) * self.px(110)
                alpha *= 1 - clamp((p - 0.2) / 0.6)
                cog_dx += ease_in_cubic(clamp((p - 0.6) / 0.4)) * cog_travel
            else:                                         # pulled back in, then the cog rolls away
                dx += ease_in_cubic(clamp(p / 0.75)) * travel
                alpha *= 1 - clamp((p - 0.8) * 5)
                cog_dx += ease_in_cubic(clamp((p - 0.6) / 0.4)) * cog_travel
        return dx, drop, tilt, alpha, cog_dx

    # ------------------------------------------------------------------ render
    def render(self, card, now: float) -> Image.Image:
        c = card.content
        L_ = self.layout(c)
        h = max(0, int(round(card.h.value)))
        img = Image.new("RGBA", (self.img_w, h + 2 * self.m), (0, 0, 0, 0))
        if h <= 4:
            return img
        R, N = L_["R"], L_["N"]
        gx, gy = L_["gx"], self.m + L_["top"]
        dx, drop, tilt, alpha, cog_dx = self._motion(card, now, L_)
        t = now - card.content_t0 + (10.0 if c.instant else 0.0)
        motion = not self.theme.reduce_motion

        art = self._art(c)
        squash = 1.0
        if isinstance(card.prev_layer, Art):
            fp = progress(now, card.prev_t0, 0.28)
            if fp >= 1 or not motion:
                card.prev_layer = None
            else:
                squash = abs(math.cos(math.pi * fp))
                if fp < 0.5:
                    art = card.prev_layer
        card.last_content = self._art(c)

        plate = art.image
        if art is card.last_content and self._needs_decor(card):
            plate = self._decorate(plate.copy(), art, card, t, motion)
        if squash < 0.999:   # flip: the plate folds to a line and opens with the new content
            nh = max(1, int(plate.height * squash))
            folded = plate.resize((plate.width, nh), Image.BILINEAR)
            plate = Image.new("RGBA", plate.size, (0, 0, 0, 0))
            plate.alpha_composite(folded, (0, (plate.height - nh) // 2))
        if alpha < 0.999:
            if plate is art.image:
                plate = plate.copy()   # never fade the cached art in place
            plate.putalpha(plate.getchannel("A").point(lambda v, a=alpha: int(v * a)))
        if tilt:
            plate = plate.rotate(-tilt, resample=Image.BICUBIC, center=art.pivot, expand=False)

        # gears first, plate on top (the rack sits over the pinion; the plate covers the big gear's top half)
        kind = c.tag_kind or c.kind
        RB, NB, phi = L_["RB"], L_["NB"], L_["phi"]
        mesh = 0.0 if drop else dx                       # once torn off, the plate no longer drives the train
        a_pin = math.degrees(mesh / R) + math.degrees(cog_dx / (R + ADD * L_["mg"]))   # clockwise, screen coords
        a_big = -a_pin * N / NB
        big_rest = phi + 270 + 180 / NB                  # a big-gear gap faces the pinion at rest
        bxg, byg = gx + L_["bx"], gy + L_["by"]
        for (R_, N_, cx, cy, ang, win, collar) in ((RB, NB, bxg, byg, big_rest + a_big, True, False),
                                                    (R, N, gx, gy, a_pin, False, True)):
            gear, half = self._gear(R_, N_, kind, windows_ok=win, collar_on=collar)
            g = gear.rotate(-ang, resample=Image.BICUBIC, center=(half, half)) if abs(ang % 360) > 0.01 else gear
            if self.theme.reduce_motion and alpha < 0.999:
                g = g.copy()
                g.putalpha(g.getchannel("A").point(lambda v, a=alpha: int(v * a)))
            self._paste(img, g, int(round(cx - half + cog_dx)), int(round(cy - half)))
        self._paste(img, plate, int(round(gx - art.pivot[0] + dx)), int(round(gy - art.pivot[1] + drop)))
        if cog_dx < 1 and abs(dx) < 0.5:
            self._hub_timer(img, card, gx, gy, R * 0.5)   # on the pinion: always fully visible

        card.button_rects = []
        if c.buttons and abs(dx) < 1 and not drop:
            for action, (x0, y0, x1, y1) in art.buttons:
                card.button_rects.append((action, (x0 + gx, y0 + gy, x1 + gx, y1 + gy)))
        return img

    def _needs_decor(self, card):
        c = card.content
        return bool(c.strike or c.fade_title or (c.buttons and card.hover_button))

    def _decorate(self, plate, art, card, t, motion):
        c = card.content
        d = ImageDraw.Draw(plate)
        px, (pvx, pvy) = self.px, art.pivot
        if art.title_box and (c.strike or c.fade_title):
            x0, ym, x1 = art.title_box
            p = ease_in_out_cubic(progress(t, 0.18, 0.45)) if motion else 1.0
            col = self.accent("done" if c.strike else "removed")
            if p > 0 and c.strike:
                xe = x0 + (x1 - x0 + px(4)) * p
                pts = [(pvx + x, pvy + ym + px(1.2) * math.sin((x - x0) / px(9)))
                       for x in np.linspace(x0 - px(2), xe, max(2, int((xe - x0) / 3)))]
                d.line(pts, fill=col, width=max(2, round(2.2 * self.s)), joint="curve")
            elif p > 0:
                n, pts = 7, []
                for i in range(int(n * p) + 1):
                    pts.append((pvx + x0 + (x1 - x0) * i / n, pvy + ym + (px(5) if i % 2 else -px(5))))
                if len(pts) > 1:
                    d.line(pts, fill=col, width=max(2, round(2 * self.s)), joint="curve")
        if c.strike:
            sp = progress(t, 0.5, 0.22) if motion else 1.0
            if sp > 0:
                stamp = self._stamp_img()
                k = 1.6 - 0.6 * ease_out_cubic(sp)
                sz = max(1, int(stamp.width * k))
                st = stamp.resize((sz, sz), Image.BICUBIC)
                st.putalpha(st.getchannel("A").point(lambda v, a=clamp(sp * 2): int(v * a)))
                cx = pvx + self.px(34)                  # right end of the plate, above the gear train
                cy = pvy + art.layout["y_root"] - self.px(24)
                plate.alpha_composite(st, (int(cx - sz / 2), int(cy - sz / 2)))
        if c.buttons and card.hover_button:
            for action, (x0, y0, x1, y1), label, primary in art.button_defs:
                if action == card.hover_button:
                    self._tag(d, (x0 + pvx, y0 + pvy, x1 + pvx, y1 + pvy), label, primary, c, hovered=True)
        return plate

    def _hub_timer(self, img, card, gx, gy, r):
        frac = card.hold_fraction
        if frac is None or card.exit_t0 is not None:
            return
        ImageDraw.Draw(img).arc([gx - r, gy - r, gx + r, gy + r], -90, -90 + 360 * clamp(frac),
                                fill=self.pal["metal_hi"][:3] + (230,), width=max(1, round(1.6 * self.s)))

    @staticmethod
    def _paste(canvas, img, x, y):
        left, top = max(0, -x), max(0, -y)
        right, bottom = min(img.width, canvas.width - x), min(img.height, canvas.height - y)
        if right > left and bottom > top:
            canvas.alpha_composite(img.crop((left, top, right, bottom)), (x + left, y + top))

    def spawn_particles(self, card):
        pass
