"""Top-right card stack. One UI thread owns the layered window; other threads talk to it via a queue.

Choreography:
  enter    slide in from the screen edge + fade (ease-out-expo), cards below spring down to make room
  morph    same card changes state (listening -> thinking -> queued): height springs, content cross-fades
  slide    leave toward the edge (queued, info)
  dissolve fade + shrink + drift up after a particle burst (done)
  collapse fold to zero height while sliding away (removed)
  group    several cards shown/hidden as one (queue peek capsules): cascade in, cascade out, shared timer
Reduced-motion: opacity fades only. Hover pauses the auto-dismiss timer."""
import itertools
import queue
import threading
import time
import traceback
from typing import Callable, Optional

from PIL import Image

from .anim import Spring, clamp, progress, ease_out_expo, ease_out_cubic, ease_in_cubic
from .cards import CardContent, CardRenderer, MARGIN
from .lottie import LottieLibrary
from .theme import detect_theme
from .a11y import Announcer
from . import win32

GAP = 10
TOP_OFFSET = 4
MAX_CARDS = 4           # individual cards; groups (queue peek) don't count toward this
GROUP_STAGGER_IN = 0.06
GROUP_STAGGER_OUT = 0.035
SAFETY_HOLD_S = 90      # listening/thinking cards never outlive this, even if a caller forgets them
EXIT_DURATIONS = {"slide": 0.34, "dissolve": 0.55, "collapse": 0.42}


class Card:
    def __init__(self, card_id, content, now, payload=None, level_fn=None):
        self.id = card_id
        self.content = content
        self.payload = payload
        self.level_fn = level_fn
        self.born = now
        self.enter_t0 = now
        self.content_t0 = now
        self.exit_t0 = None
        self.exit_style = content.exit_style
        self.exit_reason = None
        self.hold_until = None
        self.hold_total = None
        self.y = Spring(0)
        self.h = Spring(0)
        self.prev_layer = None
        self.prev_t0 = 0.0
        self.last_content = None
        self.hovered = False
        self.hover_button = None
        self.button_rects = []
        self.particles = []
        self.particles_t0 = 0.0
        self.group = None
        self.set_hold(now)

    def set_hold(self, now):
        hold = self.content.hold_s
        self.hold_total = hold if hold else None
        self.hold_until = now + (hold if hold else SAFETY_HOLD_S)

    @property
    def hold_fraction(self) -> Optional[float]:
        if not self.hold_total:
            return None
        return (self.hold_until - time.time()) / self.hold_total


class TaskCardHost:
    def __init__(self, animations_dir: str = "assets/animations",
                 on_action: Optional[Callable[[int, str, object], None]] = None, style: str = "paper",
                 palette: str = "graphite"):
        self.on_action = on_action
        self.style = style            # "paper" (mechanical: rack plate + cog) or "glass"
        self.palette = palette        # mechanical theme: graphite, blueprint, kraft, ivory, paper
        self.animations_dir = animations_dir
        self._cmds = queue.Queue()
        self._ids = itertools.count(1)
        self._ids_lock = threading.Lock()
        self._cards = []
        self._renderer = None
        self._origin = (0, 0)
        self._work = None
        self._win = None
        self._lottie = LottieLibrary(animations_dir)
        self._announcer = Announcer()
        self._stop = threading.Event()
        self.ready = threading.Event()
        self.failed = None
        self._last_frame_ms = 0.0
        self._thread = threading.Thread(target=self._run, name="TaskCards", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------- public, thread-safe
    def new_id(self) -> int:
        with self._ids_lock:
            return next(self._ids)

    def show(self, content: CardContent, card_id: Optional[int] = None, payload=None, level_fn=None) -> int:
        """Show a new card, or morph an existing one (same id) into new content."""
        card_id = card_id or self.new_id()
        self._cmds.put(("show", (card_id, content, payload, level_fn)))
        return card_id

    def show_group(self, group: str, items) -> list:
        """Show several cards as one block, in order, on top of the stack. items: [(content, payload), ...].
        Replaces any cards already showing for this group."""
        ids = [self.new_id() for _ in items]
        self._cmds.put(("group", (group, list(zip(ids, items)))))
        return ids

    def dismiss_group(self, group: str) -> None:
        self._cmds.put(("dismiss_group", group))

    def is_group_showing(self, group: str) -> bool:
        return any(c.group == group and c.exit_t0 is None for c in list(self._cards))

    def dismiss(self, card_id: Optional[int], style: Optional[str] = None) -> None:
        if card_id:
            self._cmds.put(("dismiss", (card_id, style)))

    def dismiss_kind(self, kind: str) -> None:
        self._cmds.put(("dismiss_kind", kind))

    def is_showing(self, card_id: Optional[int]) -> bool:
        return any(c.id == card_id and c.exit_t0 is None for c in list(self._cards))

    def stop(self):
        self._stop.set()

    # ------------------------------------------------------------- UI thread
    def _run(self):
        try:
            win32.make_thread_dpi_aware()
            self._win = win32.LayeredWindow("DictateIt tasks", self._on_click_ui)
            self.ready.set()
            print(f"[UI] Task cards ready (Lottie icons dir: {self.animations_dir})")
        except Exception as e:
            self.failed = e
            self.ready.set()
            print(f"[UI] Task cards FAILED to start: {e}")
            traceback.print_exc()
            return

        last = time.time()
        while not self._stop.is_set():
            try:
                self._win.pump()
                if not self._cards:
                    if self._win.visible:
                        self._win.hide()
                    try:
                        cmd = self._cmds.get(timeout=0.08)
                        self._apply(cmd)
                    except queue.Empty:
                        pass
                    last = time.time()
                    continue
                while True:
                    try:
                        self._apply(self._cmds.get_nowait())
                    except queue.Empty:
                        break
                now = time.time()
                dt = min(0.05, now - last)
                last = now
                busy = self._frame(now, dt)
                elapsed = time.time() - now
                time.sleep(max(0.001, (1 / 60 if busy else 1 / 30) - elapsed))
            except Exception as e:
                print(f"[UI] Frame error: {e}")
                traceback.print_exc()
                self._cards.clear()
                time.sleep(0.2)
        self._win.destroy()

    def _ensure_renderer(self):
        if self._cards:
            return
        work, dpi = win32.target_monitor()
        scale = dpi / 96.0
        theme = detect_theme()
        self._lottie.dark = theme.name != "light"
        r = self._renderer
        # Paper needs colour to read; high-contrast mode always gets the system-coloured glass cards.
        cls = CardRenderer
        if self.style == "paper" and not theme.high_contrast:
            from .paper import PaperRenderer
            cls = PaperRenderer
        if (r is None or type(r) is not cls or r.s != scale or r.theme.name != theme.name
                or r.theme.reduce_motion != theme.reduce_motion
                or getattr(r, "palette_name", self.palette) != self.palette):
            self._renderer = (cls(theme, scale, self._lottie, palette=self.palette) if cls is not CardRenderer
                              else cls(theme, scale, self._lottie))
        else:
            self._renderer.theme = theme
        self._work = work

    def _apply(self, cmd):
        kind, arg = cmd
        now = time.time()
        if kind == "show":
            card_id, content, payload, level_fn = arg
            self._ensure_renderer()
            r = self._renderer
            card = next((c for c in self._cards if c.id == card_id), None)
            if card:
                card.prev_layer = card.last_content
                card.prev_t0 = now
                card.content = content
                card.content_t0 = now
                card.exit_t0 = None
                card.exit_style = content.exit_style
                card.payload = payload if payload is not None else card.payload
                card.level_fn = level_fn or card.level_fn
                card.particles = []
                card.set_hold(now)
            else:
                card = Card(card_id, content, now, payload, level_fn)
                card.h.snap(r.height(content))
                self._cards.insert(0, card)
                self._enforce_limit(now)
            card.h.target = r.height(content)
            if content.celebrate:
                r.spawn_particles(card)
            if r.theme.screen_reader and content.announce:
                self._announcer.say(content.announce)
        elif kind == "group":
            group, items = arg
            self._exit_group(group, now, "replaced")
            self._ensure_renderer()
            r = self._renderer
            for i, (card_id, (content, payload)) in enumerate(items):
                card = Card(card_id, content, now, payload)
                card.group = group
                card.enter_t0 = card.content_t0 = now + i * GROUP_STAGGER_IN
                card.h.snap(r.height(content))
                self._cards.insert(i, card)
                if r.theme.screen_reader and content.announce:
                    self._announcer.say(content.announce)
        elif kind == "dismiss_group":
            self._exit_group(arg, now, "dismissed")
        elif kind == "dismiss":
            card_id, style = arg
            for c in self._cards:
                if c.id == card_id and c.exit_t0 is None:
                    self._begin_exit(c, now, style, "dismissed")
        elif kind == "dismiss_kind":
            for c in self._cards:
                if c.content.kind == arg and c.exit_t0 is None:
                    self._begin_exit(c, now, None, "dismissed")

    def _exit_group(self, group, now, reason):
        members = [c for c in self._cards if c.group == group and c.exit_t0 is None]
        for i, c in enumerate(members):
            self._begin_exit(c, now + i * GROUP_STAGGER_OUT, None, reason)

    def _enforce_limit(self, now):
        live = [c for c in self._cards if c.exit_t0 is None and c.group is None]
        for c in reversed(live[MAX_CARDS:]):
            self._begin_exit(c, now, "slide", "overflow")

    def _begin_exit(self, card, now, style=None, reason="timeout"):
        card.exit_t0 = now
        card.exit_style = style or card.content.exit_style
        card.exit_reason = reason
        if card.exit_style == "collapse":
            card.h.target = 0

    # ------------------------------------------------------------- frame
    def _frame(self, now, dt) -> bool:
        t_start = time.perf_counter()
        r = self._renderer
        s = r.s
        motion = not r.theme.reduce_motion
        busy = False

        # hold timers (paused while hovered; a group shares one timer) -> exits
        hovered_groups = {c.group for c in self._cards if c.hovered and c.group}
        for c in self._cards:
            if c.exit_t0 is None:
                if c.hovered or (c.group and c.group in hovered_groups):
                    c.hold_until += dt
                elif now >= c.hold_until:
                    if c.group:
                        self._exit_group(c.group, now, "timeout")
                    else:
                        self._begin_exit(c, now, None, "timeout")

        # retire finished exits
        alive = []
        for c in self._cards:
            if c.exit_t0 is not None and now - c.exit_t0 >= self._exit_duration(c, motion):
                if c.content.buttons and self.on_action:
                    self._dispatch(c.id, "closed", c.payload)   # unanswered question: let the owner know
                continue
            alive.append(c)
        self._cards = alive
        if not self._cards:
            self._win.hide()
            return False

        # stack layout: exiting cards give their space back as they leave
        y_acc = round(TOP_OFFSET * s)
        for c in self._cards:
            c.y.target = y_acc
            share = 1.0
            # Group members leave in place (cascade); the space closes once the whole group is gone.
            if c.exit_t0 is not None and c.exit_style != "collapse" and not c.group:
                share = 1 - ease_out_cubic(progress(now, c.exit_t0, self._exit_duration(c, motion)))
            y_acc += (c.h.value + getattr(r, "gap", GAP) * s) * share
            if motion:
                c.y.step(dt)
                c.h.step(dt)
            else:
                c.y.snap()
                c.h.snap()
            busy = busy or not (c.y.settled and c.h.settled)

        m = r.m
        canvas_w = r.img_w
        canvas_h = int(max(c.y.value + c.h.value for c in self._cards) + 2 * m + 2)
        canvas = Image.new("RGBA", (canvas_w, max(1, canvas_h)), (0, 0, 0, 0))

        hit_boxes = []
        for c in reversed(self._cards):           # bottom cards first, newest drawn on top
            img = r.render(c, now)
            opacity, dx, dy, scale = self._transform(c, now, motion, s)
            if c.exit_t0 is not None or now - c.enter_t0 < 0.6 or now - c.content_t0 < 0.9 \
                    or c.content.level_bars or c.content.shimmer or c.content.icon == "spinner" or c.particles:
                busy = True
            if scale != 1.0:
                nw, nh = max(1, int(img.width * scale)), max(1, int(img.height * scale))
                img = img.resize((nw, nh), Image.BILINEAR)
                dx += (r.img_w - nw) / 2
                dy += (img.height / scale - nh) / 2
            if opacity < 0.999:
                img.putalpha(img.getchannel("A").point(lambda v, o=opacity: int(v * o)))
            x, y = int(round(dx)), int(round(c.y.value + dy))
            self._paste(canvas, img, x, y)
            hit_boxes.append((c, x, y))

        wx = self._work[2] - canvas_w
        wy = self._work[1]
        self._origin = (wx, wy)
        self._win.present(canvas, wx, wy)
        self._update_hover(list(reversed(hit_boxes)))
        self._last_frame_ms = (time.perf_counter() - t_start) * 1000
        return busy

    def _exit_duration(self, c, motion):
        durations = getattr(self._renderer, "exit_durations", EXIT_DURATIONS)
        return durations.get(c.exit_style, 0.34) if motion else 0.16

    def _transform(self, c, now, motion, s):
        opacity, dx, dy, scale = 1.0, 0.0, 0.0, 1.0
        if getattr(self._renderer, "handles_motion", False):
            return opacity, dx, dy, scale   # the skin animates itself (paper: feeds out of / back into the cog)
        enter_p = progress(now, c.enter_t0, 0.5 if motion else 0.16)
        if enter_p < 1:
            opacity = ease_out_cubic(clamp(enter_p * 1.8))
            if motion:
                dx = (1 - ease_out_expo(enter_p)) * 64 * s
                scale = 0.97 + 0.03 * ease_out_cubic(enter_p)
        if c.exit_t0 is not None:
            p = progress(now, c.exit_t0, self._exit_duration(c, motion))
            if not motion:
                return opacity * (1 - p), dx, dy, scale
            if c.exit_style == "slide":
                dx += ease_in_cubic(p) * 80 * s
                opacity *= 1 - ease_in_cubic(p)
            elif c.exit_style == "dissolve":
                e = ease_out_cubic(p)
                opacity *= 1 - e
                scale *= 1 - 0.07 * e
                dy -= 10 * s * e
            elif c.exit_style == "collapse":
                dx += ease_in_cubic(p) * 36 * s
                opacity *= 1 - ease_in_cubic(p)
        return opacity, dx, dy, scale

    @staticmethod
    def _paste(canvas, img, x, y):
        # alpha_composite needs the source fully inside the canvas: crop whatever hangs off the edges.
        left, top = max(0, -x), max(0, -y)
        right = min(img.width, canvas.width - x)
        bottom = min(img.height, canvas.height - y)
        if right <= left or bottom <= top:
            return
        canvas.alpha_composite(img.crop((left, top, right, bottom)), (x + left, y + top))

    # ------------------------------------------------------------- input
    def _card_at(self, lx, ly):
        m = self._renderer.m
        for c, x, y in getattr(self, "_hits", []):
            if c.exit_t0 is not None:
                continue
            if x + m <= lx <= x + m + self._renderer.w and y + m <= ly <= y + m + c.h.value:
                return c, lx - x, ly - y
        return None, 0, 0

    def _update_hover(self, hits_top_first):
        self._hits = hits_top_first
        cx, cy = win32.cursor_pos()
        lx, ly = cx - self._origin[0], cy - self._origin[1]
        target, bx, by = self._card_at(lx, ly)
        hand = False
        for c, _, _ in hits_top_first:
            c.hovered = c is target
            c.hover_button = None
            if c is target:
                for action, (x0, y0, x1, y1) in c.button_rects:
                    if x0 <= bx <= x1 and y0 <= by <= y1:
                        c.hover_button = action
                        hand = True
                if not c.content.buttons:
                    hand = True
        self._win.hand_cursor = hand

    def _on_click_ui(self, lx, ly):
        card, bx, by = self._card_at(lx, ly)
        if not card:
            return
        now = time.time()
        for action, (x0, y0, x1, y1) in card.button_rects:
            if x0 <= bx <= x1 and y0 <= by <= y1:
                self._dispatch(card.id, action, card.payload)
                return
        if card.content.buttons:
            return
        if card.content.click_action:
            self._dispatch(card.id, card.content.click_action, card.payload)
        if card.group:
            self._exit_group(card.group, now, "clicked")
        else:
            self._begin_exit(card, now, "slide", "clicked")

    def _dispatch(self, card_id, action, payload):
        if not self.on_action:
            return

        def run():
            try:
                self.on_action(card_id, action, payload)
            except Exception as e:
                print(f"[UI] Card action '{action}' failed: {e}")
                traceback.print_exc()
        threading.Thread(target=run, daemon=True).start()
