"""Raw focus samples -> working segments. This is where "switched apps" is told apart from "switched work":
a window must hold focus for `settle_s` before it counts, so Alt-Tab blips never end a segment."""
from dataclasses import dataclass, field
from typing import Callable, Optional

from .context import Context


@dataclass
class Segment:
    ctx: Context
    start: float
    last_seen: float
    id: Optional[int] = None
    task_id: Optional[int] = None
    link_source: Optional[str] = None
    ai_checked: bool = False
    meta: dict = field(default_factory=dict)

    def dwell(self, now: float) -> float:
        return now - self.start


class Sessionizer:
    def __init__(self, settle_s: float, idle_after_s: float,
                 on_start: Callable[[Segment], None], on_end: Callable[[Segment], None],
                 on_tick: Callable[[Optional[Segment], bool, float, float], None]):
        self.settle_s = settle_s
        self.idle_after_s = idle_after_s
        self.on_start = on_start
        self.on_end = on_end
        self.on_tick = on_tick
        self.current: Optional[Segment] = None
        self._candidate = None   # (ctx, first_seen)
        self._last_now = None

    def tick(self, ctx: Optional[Context], idle_s: float, now: float) -> None:
        dt = 0.0 if self._last_now is None else min(5.0, now - self._last_now)
        self._last_now = now

        if idle_s >= self.idle_after_s:
            if self.current:
                # Close at the moment input stopped, not now: idle time isn't work time.
                self.current.last_seen = max(self.current.start, now - idle_s)
                self._end_current()
            self._candidate = None
            self.on_tick(None, True, now, dt)
            return

        if ctx is None:   # desktop/taskbar/our own cards: no change of context
            if self.current:
                self.current.last_seen = now
            self.on_tick(self.current, False, now, dt)
            return

        if self.current and ctx.key == self.current.ctx.key:
            self.current.last_seen = now
            self.current.ctx = ctx   # keep the freshest label (e.g. file changed inside the same workspace)
            self._candidate = None
        elif self._candidate and self._candidate[0].key == ctx.key:
            if now - self._candidate[1] >= self.settle_s:
                started = self._candidate[1]
                if self.current:
                    self.current.last_seen = started
                    self._end_current()
                self.current = Segment(ctx=ctx, start=started, last_seen=now)
                self._candidate = None
                self.on_start(self.current)
            else:
                self._candidate = (ctx, self._candidate[1])
        else:
            self._candidate = (ctx, now)
            if self.current is None and self.settle_s <= 0:
                self.current = Segment(ctx=ctx, start=now, last_seen=now)
                self.on_start(self.current)

        self.on_tick(self.current, False, now, dt)

    def _end_current(self) -> None:
        seg, self.current = self.current, None
        if seg:
            self.on_end(seg)

    def flush(self) -> None:
        self._end_current()
