"""TaskManager: voice commands, context awareness, nudges. The user always owns completion and priority:
the watcher can make a task Active or Paused, but only the user (voice, card button, tray) completes it."""
import os
import threading
import time
import traceback
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from . import presenter
from .intents import parse_rules, validate_ai_intent, is_trivial, reference_core, Intent
from .models import Task, ACTIVE, PAUSED, READY, WAITING, COMPLETED, REMOVED, OPEN_STATUSES
from .store import TaskStore
from .text import normalize_title, best_task_match, ref_score, vocabulary_terms
from ..ai.linker import ContextLinker
from ..ai.prompts import INTENT_SYSTEM, intent_user_message
from ..watch.window import notifications_welcome

TOUCH_EVERY_S = 15.0      # how often focus time / last context is written while you work


class TaskManager:
    def __init__(self, config, store: TaskStore, ui, feedback, ai_client=None):
        self.config = config
        self.store = store
        self.ui = ui
        self.feedback = feedback
        self.ai = ai_client
        self.linker = ContextLinker(store, ai_client, config.ai_link_share)
        self._lock = threading.RLock()
        self._ai_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="AILink")
        self._refine_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="AIRefine")
        self._listeners = []

        self._capture_card = None
        self._nudge = None                 # {"task_id", "card_id", "shown_at"}
        self._last_nudge_at = 0.0
        self._current = None               # current Segment
        self._session = None               # {"task_id", "focus", "since"} focus run on one task
        self._candidate = None             # {"task_id", "left_at", "focus", "nudged"} task you walked away from
        self._pending_focus = {}           # task_id -> seconds not yet written
        self._last_touch = 0.0
        self._recent = deque(maxlen=6)     # recent context descriptions, for the AI linker
        self._last_change = None           # (task_id, previous_status or None if it was just created) for "undo"
        self._checkin = None               # {"card_id", "seg", "task_id"} pending "working on X?" question
        self._last_checkin_at = 0.0
        self._checkin_asked = set()        # ctx keys already asked about this run

    # ------------------------------------------------------------------ change notifications (tray)
    def add_listener(self, fn):
        self._listeners.append(fn)

    def _changed(self):
        for fn in list(self._listeners):
            try:
                fn()
            except Exception as e:
                print(f"[Tasks] Listener error: {e}")

    # ------------------------------------------------------------------ voice capture hooks (engine)
    def capture_started(self, level_fn=None):
        content = presenter.listening(self.config.task_hotkey, self.config.mode)
        reuse = self._capture_card if self.ui.is_showing(self._capture_card) else None
        self._capture_card = self.ui.show(content, card_id=reuse, level_fn=level_fn)

    def capture_processing(self):
        if self._capture_card:
            self.ui.show(presenter.thinking(), card_id=self._capture_card)

    def capture_failed(self, reason: str):
        hk = "+".join(p.capitalize() for p in self.config.task_hotkey.split("+"))
        titles = {"silence": "Didn't catch that", "error": "Couldn't hear the mic"}
        self.ui.show(presenter.message("Nothing queued", titles.get(reason, "Didn't catch that"),
                                       f"Try again with {hk}", kind="info", icon="mic"),
                     card_id=self._capture_card)
        self._capture_card = None

    def handle_command(self, text: str) -> dict:
        """Transcript -> intent -> action -> card. Returns timing info for the engine's telemetry."""
        card = self._capture_card
        self._capture_card = None
        if card:
            self.ui.show(presenter.thinking(text), card_id=card)

        t0 = time.time()
        with self._lock:
            tasks = self.store.open_tasks()
            pending_id = self._nudge["task_id"] if self._nudge else None
        active = next((t for t in tasks if t.status == ACTIVE), None)
        active_id = active.id if active else None
        recent = max(tasks, key=lambda t: max(t.created_at, t.updated_at, t.last_active_at or 0), default=None)
        ai_ready = bool(self.ai and self.ai.available)

        # Rules first, always: capture must feel instant. The AI only refines (adds) or resolves (unclear refs).
        intent = parse_rules(text, tasks, pending_id, active_id, recent.id if recent else None)
        source_info = "rules"
        resolved = intent.action in ("add", "peek", "undo") or intent.task_id is not None
        if ai_ready and not resolved and not is_trivial(text, pending_id):
            obj, info = self.ai.chat_json(
                INTENT_SYSTEM, intent_user_message(text, tasks, self.store.projects(), pending_id, active_id,
                                                  self._user_context()),
                purpose="intent")
            ai_intent = validate_ai_intent(obj, tasks) if obj else None
            if ai_intent:
                intent, source_info = ai_intent, f"ai ({info})"
                if ai_intent.task_id and ai_intent.action != "add":
                    self._learn_alias(ai_intent.task_id, text, "ai")
            else:
                source_info = f"rules (ai: {info if obj is None else 'invalid reply'})"
        t_intent = time.time() - t0

        print(f"[Tasks] \"{text}\" -> {intent.action}"
              f"{f' #{intent.task_id}' if intent.task_id else ''}"
              f"{f' +{len(intent.task_ids) - 1} more' if len(intent.task_ids) > 1 else ''}"
              f"{f' ask {list(intent.candidates)}' if intent.candidates and not intent.task_id else ''}"
              f"{f' {intent.title!r}' if intent.title and intent.action == 'add' else ''} via {source_info}")
        try:
            task = self._apply_intent(intent, text, card)
            if intent.action == "add" and task and ai_ready and intent.source == "rules":
                self._refine_pool.submit(self._refine, text, task.id, card, tasks, pending_id, active_id)
                source_info += " + ai refining"
        except Exception as e:
            print(f"[Tasks] Failed to apply intent: {e}")
            traceback.print_exc()
            self.feedback.error()
            self.ui.show(presenter.message("Something went wrong", text, str(e)[:80]), card_id=card)
        return {"intent_ms": t_intent * 1000, "action": intent.action, "source": source_info}

    def _refine(self, text, task_id, card, tasks_before, pending_id, active_id):
        """Background: let the AI clean up the provisional task, or reveal it was really a command."""
        try:
            obj, info = self.ai.chat_json(
                INTENT_SYSTEM, intent_user_message(text, tasks_before, self.store.projects(), pending_id, active_id,
                                                  self._user_context()),
                purpose="refine", max_share=self.config.ai_refine_share)
            intent = validate_ai_intent(obj, tasks_before) if obj else None
            if not intent:
                return
            with self._lock:
                task = self.store.get_task(task_id)
                if not task or task.status != READY:
                    return   # the user already did something with it; don't second-guess them
                if intent.action == "add":
                    if (intent.title, intent.project, intent.priority) == (task.title, task.project, task.priority):
                        return
                    task = self.store.update_task(task_id, intent.title, intent.project or task.project,
                                                  intent.priority if intent.priority != "normal" else task.priority)
                    pos, total = self.store.queue_position(task_id)
                    print(f"[Tasks] Refined #{task_id}: {task.title!r} · {task.project} · {task.priority} ({info})")
                    self.store.bump_vocab(vocabulary_terms(f"{task.title} {task.project or ''}"))
                    if self.ui.is_showing(card):
                        content = presenter.queued(task, pos, total)
                        content.instant = True
                        self.ui.show(content, card_id=card, payload=task_id)
                    self._changed()
                    return
                # It was a command, not new work: withdraw the provisional task and do what was meant.
                self.store.delete_task(task_id)
                print(f"[Tasks] AI: \"{text}\" was a {intent.action} command, not a new task; withdrew #{task_id}")
            card_id = card if self.ui.is_showing(card) else None
            if intent.action == "peek":
                self.ui.dismiss(card_id)
                self.show_peek()
            elif intent.action == "none":
                self.ui.show(presenter.message("Not a task command", text, "Nothing queued"), card_id=card_id)
            elif intent.task_id:
                self.set_status(intent.task_id, {"complete": COMPLETED, "remove": REMOVED, "pause": PAUSED,
                                                 "wait": WAITING, "start": ACTIVE}[intent.action],
                                card_id=card_id, via="voice")
            self._changed()
        except Exception as e:
            print(f"[Tasks] Refinement failed (task kept as captured): {e}")
            traceback.print_exc()

    def _apply_intent(self, intent: Intent, text: str, card):
        if intent.action == "add":
            return self._add(intent, text, card)
        elif intent.action == "peek":
            self.ui.dismiss(card)
            self.show_peek()
        elif intent.action == "none":
            self.ui.show(presenter.message("Not a task command", text, "Nothing changed"), card_id=card)
            self.feedback.empty_or_silence()
        elif intent.action == "undo":
            self.undo(card)
        elif intent.task_id is None:
            # Never guess and never turn a "done" sentence into a new task: offer the likely ones to click.
            self.ui.dismiss(card)
            self.show_pick(intent.action, intent.candidates, text)
        else:
            status = {"complete": COMPLETED, "remove": REMOVED, "pause": PAUSED, "wait": WAITING, "start": ACTIVE}[intent.action]
            ids = intent.task_ids or (intent.task_id,)
            for i, tid in enumerate(ids):
                self.set_status(tid, status, card_id=card if i == 0 else None, via="voice")

    def show_pick(self, action: str, candidate_ids, heard: str = ""):
        tasks = [t for t in (self.store.get_task(i) for i in candidate_ids) if t and t.is_open]
        if not tasks:
            tasks = self.store.open_tasks()[:4]
        if not tasks:
            self.ui.show(presenter.message("Nothing open", heard or "Your queue is clear", "Nothing changed"))
            return
        self.feedback.nudge()
        self._last_pick_heard = heard
        self.ui.show_group("pick", presenter.pick(action, tasks, heard))

    def undo(self, card=None):
        with self._lock:
            change, self._last_change = self._last_change, None
        if not change:
            self.ui.show(presenter.message("Nothing to undo", "No recent change", ""), card_id=card)
            return
        task_id, previous = change
        task = self.store.get_task(task_id)
        if not task:
            return
        if previous is None:   # it was just created: take it back off the queue
            self.store.set_status(task_id, REMOVED, detail="undo")
            self.ui.show(presenter.removed(task), card_id=card)
        else:
            task = self.store.set_status(task_id, previous, detail="undo")
            self.ui.show(presenter.message("Undone", task.title, f"Back to {previous}", kind="info", icon="history"),
                         card_id=card)
        print(f"[Tasks] Undo #{task_id} -> {previous or 'removed'}")
        self.feedback.task_removed()
        self._changed()

    def _add(self, intent: Intent, text: str, card):
        title = intent.title or normalize_title(text)
        with self._lock:
            for t in self.store.open_tasks():
                if t.title.lower() == title.lower():
                    self.ui.show(presenter.already_queued(t), card_id=card)
                    self.feedback.empty_or_silence()
                    return None
            task = self.store.add_task(title, intent.project, intent.priority, source_text=text)
            self.store.bump_vocab(vocabulary_terms(f"{title} {intent.project or ''}"))
            self._last_change = (task.id, None)
            pos, total = self.store.queue_position(task.id)
        self.ui.show(presenter.queued(task, pos, total), card_id=card, payload=task.id)
        self.feedback.task_queued()
        self._changed()
        return task

    # ------------------------------------------------------------------ status changes (voice, cards, tray)
    def set_status(self, task_id: int, status: str, card_id=None, via: str = "user") -> Optional[Task]:
        with self._lock:
            task = self.store.get_task(task_id)
            if not task:
                return None
            # If a "wrapped up?" card is showing for this task, animate that card instead of a new one.
            if self._nudge and self._nudge["task_id"] == task_id:
                if card_id and card_id != self._nudge["card_id"]:
                    self.ui.dismiss(card_id, "slide")
                card_id = self._nudge["card_id"]
                self._nudge = None
                if self._candidate and self._candidate["task_id"] == task_id:
                    self._candidate["nudged"] = True
            prev_status = task.status
            if task.status != status:
                self._last_change = (task_id, task.status)
            task = self.store.set_status(task_id, status, detail=via)
            if status == ACTIVE and self._current and not self._current.ctx.private:
                # "I'm working on X" while in a window teaches that window -> X.
                self.store.set_link(self._current.ctx.key, task_id, "user", 1.0, self.store.max_task_id())
                self._current.task_id = task_id
                self._current.link_source = "user"
            if status in (COMPLETED, REMOVED, WAITING, PAUSED):
                if self._session and self._session["task_id"] == task_id:
                    self._session = None
                if self._candidate and self._candidate["task_id"] == task_id:
                    self._candidate = None

        if status == COMPLETED:
            self.ui.show(presenter.done(task), card_id=card_id, payload={"undo": (task_id, prev_status)})
            self.feedback.task_done()
        elif status == REMOVED:
            self.ui.show(presenter.removed(task), card_id=card_id, payload={"undo": (task_id, prev_status)})
            self.feedback.task_removed()
        else:
            self.ui.show(presenter.status(task, status), card_id=card_id, payload=task_id)
            self.feedback.transcribed()
        print(f"[Tasks] #{task_id} '{task.title}' -> {status} (via {via})")
        self._changed()
        return task

    def on_card_action(self, card_id, action, payload):
        """Clicks on card buttons (runs off the UI thread)."""
        if action == "undo" and isinstance(payload, dict) and payload.get("undo"):
            task_id, prev = payload["undo"]
            task = self.store.set_status(task_id, prev, detail="undo (card)")
            if task:
                self.ui.show(presenter.restored(task, prev), card_id=card_id, payload=task_id)
                self.feedback.task_removed()
                print(f"[Tasks] Undo (card) #{task_id} -> {prev}")
                with self._lock:
                    if self._last_change and self._last_change[0] == task_id:
                        self._last_change = None
                self._changed()
            return
        if action == "open_task":
            if payload is not None:
                self.open_task(int(payload))
            return
        if action.startswith("pick:"):
            act = action.split(":", 1)[1]
            if payload is not None and getattr(self, "_last_pick_heard", ""):
                self._learn_alias(int(payload), self._last_pick_heard, "you")
                self._last_pick_heard = ""
            if payload is not None:
                if act == "start":
                    self._accept_checkin(int(payload))
                else:
                    self.set_status(int(payload), {"complete": COMPLETED, "remove": REMOVED, "pause": PAUSED, "wait": WAITING, "start": ACTIVE}[act], via="pick")
            return
        if action in ("checkin_yes", "checkin_other", "checkin_no"):
            self._answer_checkin(card_id, action)
            return
        if action == "closed":
            with self._lock:
                if self._nudge and self._nudge["card_id"] == card_id:
                    print(f"[Tasks] Nudge for #{self._nudge['task_id']} closed unanswered; status unchanged.")
                    self._nudge = None
                if self._checkin and self._checkin["card_id"] == card_id:
                    self._checkin = None
            return
        if payload is None:
            return
        status = {"done": COMPLETED, "not_yet": PAUSED, "waiting": WAITING}.get(action)
        if status and not isinstance(payload, dict):
            self.set_status(int(payload), status, card_id=card_id, via=f"card:{action}")

    def vocabulary(self) -> list:
        """Words Whisper should spell right in task commands: open task titles, projects, recent completions."""
        terms = []
        for t in self.store.open_tasks()[:20]:
            terms.append(t.title)
            if t.project:
                terms.append(t.project)
        terms += [t.title for t in self.store.recent_completed(8)]
        terms += self.store.top_vocab(30)   # names learned from every task you've ever added
        return terms

    def _learn_alias(self, task_id: int, heard: str, source: str):
        """Remember what you called a task, so the same words match it instantly next time (no AI needed)."""
        phrase = reference_core(heard)
        task = self.store.get_task(task_id)
        if not task or not phrase or len(phrase.split()) > 8:
            return
        if ref_score(phrase, f"{task.title} {task.project or ''}") >= 0.99:
            return   # already matches perfectly; nothing to learn
        if self.store.add_alias(task_id, phrase, source):
            print(f"[Learn] \"{phrase}\" now means #{task_id} '{task.title}' (from {source}; "
                  f"{self.store.alias_count()} learned phrases)")

    def _user_context(self) -> dict:
        """What you've been doing, for the AI: recent windows (minutes), tasks finished today, where you are now."""
        today = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        ctx = {
            "now_in": (f"{self._current.ctx.app}: {self._current.ctx.describe()}"
                       if self._current and not self._current.ctx.private else None),
            "recent_windows": [f"{app}: {label} ({mins} min)" for app, label, mins in self.store.recent_segments(6)],
            "finished_today": [t.title for t in self.store.recent_completed(10) if (t.completed_at or 0) >= today][:6],
        }
        return {k: v for k, v in ctx.items() if v}

    def greet(self):
        cfg = self.config
        self.ui.show(presenter.hello(cfg.hotkey, cfg.task_hotkey, cfg.peek_hotkey, len(self.store.open_tasks())))

    def capture_cancelled(self):
        self.ui.show(presenter.cancelled(), card_id=self._capture_card)
        self._capture_card = None

    def peek_key(self, event):
        """Ctrl+Alt+Q: tap toggles the queue; hold shows it while held and hides it on release."""
        now = time.time()
        if event == "press":
            if now - getattr(self, "_last_peek_press", 0.0) < 0.15:
                return   # key chatter
            self._last_peek_press = now
            if self.ui.is_group_showing("peek"):
                self.ui.dismiss_group("peek")
                self._peek_by_press = False
            else:
                self._open_peek()
                self._peek_by_press = True
        elif isinstance(event, tuple) and event[0] == "release":
            from ..hotkey import HOLD_S
            if getattr(self, "_peek_by_press", False) and event[1] >= HOLD_S:
                self.ui.dismiss_group("peek")
            self._peek_by_press = False

    def _open_peek(self):
        tasks = self.store.open_tasks()
        today_start = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        done_today = sum(1 for t in self.store.recent_completed(50) if (t.completed_at or 0) >= today_start)
        self.ui.show_group("peek", presenter.peek(tasks, done_today))

    def show_error(self, summary: str):
        """Calm, rate-limited error card for unexpected failures (details go to the log)."""
        now = time.time()
        if now - getattr(self, "_last_error_card", 0.0) < 60:
            return
        self._last_error_card = now
        try:
            self.ui.show(presenter.error(summary))
            self.feedback.error()
        except Exception:
            pass

    def show_peek(self):
        tasks = self.store.open_tasks()
        today_start = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        done_today = sum(1 for t in self.store.recent_completed(50) if (t.completed_at or 0) >= today_start)
        if self.ui.is_group_showing("peek"):
            self.ui.dismiss_group("peek")   # same hotkey again closes it
            return
        self._open_peek()

    def open_task(self, task_id: int) -> bool:
        """Reopen the last web page this task was worked on. Only http(s), so a title can never launch a program."""
        task = self.store.get_task(task_id)
        url = task.last_url if task else None
        if not url or not url.startswith(("https://", "http://")):
            return False
        try:
            os.startfile(url)
            self.store.add_event(task_id, "reopened", url)
            print(f"[Tasks] Reopened #{task_id} '{task.title}' -> {url}")
            return True
        except OSError as e:
            print(f"[Tasks] Could not open {url}: {e}")
            return False

    # ------------------------------------------------------------------ watcher callbacks (watcher thread)
    def on_segment_start(self, seg):
        with self._lock:
            self._current = seg
            ctx = seg.ctx
            try:
                seg.id = self.store.open_segment(ctx.app, ctx.label, ctx.workspace, ctx.key, seg.start, ctx.url)
            except Exception as e:
                print(f"[Tasks] Could not record segment: {e}")
            if not ctx.private:
                self._link_now(seg)
            self._recent.append(ctx.describe() if not ctx.private else "Private window")
        print(f"[Context] -> {ctx.app}: {ctx.describe()}"
              f"{f' [linked #{seg.task_id} via {seg.link_source}]' if seg.task_id else ''}")

    def on_segment_end(self, seg):
        with self._lock:
            if seg.id:
                self.store.close_segment(seg.id, seg.last_seen, seg.task_id)
            if self._current is seg:
                self._current = None
        self._flush_focus()

    def _link_now(self, seg):
        """Cheap tiers only (cache + local words). The AI tier runs later, once the user has stayed a while."""
        tasks = self.store.open_tasks()
        if not tasks:
            return
        open_ids = {t.id for t in tasks}
        hit, task_id, source = self.linker.cached(seg.ctx, open_ids)
        if hit:
            seg.task_id, seg.link_source, seg.ai_checked = task_id, source, True
            return
        task_id, score = self.linker.local(seg.ctx, tasks)
        if task_id:
            seg.task_id, seg.link_source = task_id, f"words {score:.2f}"
            self.store.set_link(seg.ctx.key, task_id, "rule", score, self.store.max_task_id())

    def _link_ai_async(self, seg):
        seg.ai_checked = True
        tasks = self.store.open_tasks()
        recent = list(self._recent)[:-1]

        def job():
            asked, task_id, conf = self.linker.ai(seg.ctx, tasks, recent)
            if not asked:
                seg.ai_checked = False   # budget/no key: retry later if it frees up
                return
            with self._lock:
                self.store.set_link(seg.ctx.key, task_id, "ai", conf, self.store.max_task_id())
                if self._current is seg and task_id:
                    seg.task_id, seg.link_source = task_id, f"ai {conf:.2f}"
                    print(f"[Context] AI linked '{seg.ctx.describe()}' -> task #{task_id} ({conf:.2f})")
                elif self._current is seg:
                    print(f"[Context] AI: '{seg.ctx.describe()}' isn't part of an open task")
        self._ai_pool.submit(job)

    def on_tick(self, seg, idle: bool, now: float, dt: float):
        try:
            self._tick(seg, idle, now, dt)
        except Exception as e:
            print(f"[Tasks] Tick error: {e}")
            traceback.print_exc()

    def _tick(self, seg, idle, now, dt):
        cfg = self.config
        with self._lock:
            if idle or seg is None:
                return   # away from the keyboard is neither working on a task nor leaving it

            if (seg.task_id is None and not seg.ai_checked and not seg.ctx.private
                    and seg.dwell(now) >= cfg.ai_link_min_dwell_s and self.linker.client
                    and self.linker.client.available):
                if self.store.open_tasks():
                    self._link_ai_async(seg)
                else:
                    seg.ai_checked = True

            if seg.task_id is not None:
                self._in_task_context(seg, now, dt)
            else:
                self._outside_task_context(seg, now)
                self._maybe_checkin(seg, now)

            self._maybe_nudge(seg, now)
            if now - self._last_touch >= TOUCH_EVERY_S:
                self._flush_focus()

    def _in_task_context(self, seg, now, dt):
        tid = seg.task_id
        if self._session is None or self._session["task_id"] != tid:
            if seg.dwell(now) < self.config.activate_after_s:
                return
            task = self.store.get_task(tid)
            if not task or task.status not in OPEN_STATUSES:
                seg.task_id = None
                return
            self._leave_session(seg.start, seg)
            if self._candidate and self._candidate["task_id"] == tid:
                self._candidate = None   # came back: not done, just interrupted
            self._session = {"task_id": tid, "focus": seg.dwell(now), "since": seg.start}
            self._pending_focus[tid] = self._pending_focus.get(tid, 0.0) + seg.dwell(now)

            if task.status != ACTIVE:
                away = now - (task.last_active_at or now)
                was_paused = task.status in (PAUSED, WAITING)
                self.store.set_status(tid, ACTIVE, detail=f"context: {seg.ctx.describe()}")
                print(f"[Tasks] #{tid} '{task.title}' -> active (you're in {seg.ctx.app}: {seg.ctx.describe()})")
                if was_paused and away >= self.config.resume_after_s and notifications_welcome():
                    self.ui.show(presenter.resume(task), payload=tid)
                self._changed()
            self.store.touch_context(tid, seg.ctx.describe(), seg.ctx.app, url=seg.ctx.url)
            return
        self._session["focus"] += dt
        self._pending_focus[tid] = self._pending_focus.get(tid, 0.0) + dt

    def _outside_task_context(self, seg, now):
        if self._session and seg.dwell(now) >= 0:
            self._leave_session(seg.start, seg)

    def _leave_session(self, left_at, new_seg):
        s = self._session
        if not s:
            return
        self._session = None
        if s["focus"] >= self.config.nudge_min_focus_s:
            self._candidate = {"task_id": s["task_id"], "left_at": left_at, "focus": s["focus"],
                               "nudged": False, "moved_to": new_seg.ctx.app if new_seg else "another app"}

    def _maybe_nudge(self, seg, now):
        c = self._candidate
        cfg = self.config
        if not c or c["nudged"] or self._nudge:
            return
        if now - c["left_at"] < cfg.nudge_after_s or now - self._last_nudge_at < cfg.nudge_cooldown_s:
            return
        if not notifications_welcome():
            return   # full-screen / presenting / Focus: try again on a later tick
        task = self.store.get_task(c["task_id"])
        if not task or task.status not in OPEN_STATUSES:
            self._candidate = None
            return
        c["nudged"] = True
        self._last_nudge_at = now
        card = self.ui.show(presenter.nudge(task, c["focus"], c["moved_to"], cfg.task_hotkey), payload=task.id)
        self._nudge = {"task_id": task.id, "card_id": card, "shown_at": now}
        self.store.add_event(task.id, "nudge", f"away {now - c['left_at']:.0f}s in {c['moved_to']}")
        self.feedback.nudge()
        print(f"[Tasks] Nudge: wrapped up #{task.id} '{task.title}'? (away {now - c['left_at']:.0f}s)")

    def _maybe_checkin(self, seg, now):
        """Nothing is Active and you've settled in a window no task is linked to: ask once what you're on.
        A "Yes" links this window to the task (no AI needed) and makes it Active, so walking away later
        brings the "Wrapped up?" question."""
        cfg = self.config
        if (self._checkin or self._nudge or seg.ctx.private or seg.ctx.key in self._checkin_asked
                or seg.dwell(now) < cfg.checkin_after_s or now - self._last_checkin_at < cfg.checkin_cooldown_s):
            return
        if self._session or self.store.active_task():
            return
        row = self.store.get_link(seg.ctx.key)
        if row and row[1] == "user" and row[3] is not None and row[3] >= self.store.max_task_id():
            return   # you said "No" here and no new tasks have appeared since
        tasks = self.store.open_tasks()
        if not tasks or not notifications_welcome():
            return
        guess, score = best_task_match(f"{seg.ctx.label} {seg.ctx.workspace or ''}", tasks)
        if score < 0.34:
            guess = max(tasks, key=lambda t: max(t.created_at, t.updated_at, t.last_active_at or 0))
        self._checkin_asked.add(seg.ctx.key)
        self._last_checkin_at = now
        card = self.ui.show(presenter.checkin(guess, seg.ctx.app, seg.ctx.describe(), seg.dwell(now)),
                            payload=guess.id)
        self._checkin = {"card_id": card, "seg": seg, "task_id": guess.id}
        self.feedback.nudge()
        print(f"[Tasks] Check-in: working on #{guess.id} '{guess.title}' in {seg.ctx.app}?")

    def _answer_checkin(self, card_id, action):
        with self._lock:
            c = self._checkin
            if not c or c["card_id"] != card_id:
                return
        if action == "checkin_yes":
            self._accept_checkin(c["task_id"], card_id)
        elif action == "checkin_other":
            self.ui.dismiss(card_id)
            self.ui.show_group("pick", presenter.pick("start", self.store.open_tasks()[:5], ""))
        else:
            with self._lock:
                self._checkin = None
                seg = c["seg"]
                self.store.set_link(seg.ctx.key, None, "user", 1.0, self.store.max_task_id())
            self.ui.dismiss(card_id)
            print(f"[Tasks] Check-in: '{c['seg'].ctx.describe()}' isn't a task window (won't ask again)")

    def _accept_checkin(self, task_id, card_id=None):
        """You confirmed you're on task_id in the check-in window: link it and make the task Active."""
        with self._lock:
            c, self._checkin = self._checkin, None
            seg = c["seg"] if c else self._current
            if seg and not seg.ctx.private:
                self.store.set_link(seg.ctx.key, task_id, "user", 1.0, self.store.max_task_id())
                seg.task_id, seg.link_source = task_id, "user"
                seg.start = min(seg.start, time.time() - self.config.activate_after_s)  # count the time already spent
        self.set_status(task_id, ACTIVE, card_id=card_id or (c["card_id"] if c else None), via="check-in")

    def _flush_focus(self):
        with self._lock:
            pending, self._pending_focus = self._pending_focus, {}
            self._last_touch = time.time()
            for tid, secs in pending.items():
                if secs <= 0:
                    continue
                here = self._current if self._current and self._current.task_id == tid else None
                task = self.store.get_task(tid)
                if task:
                    self.store.touch_context(tid, here.ctx.describe() if here else task.last_context,
                                             here.ctx.app if here else task.last_app, secs,
                                             url=here.ctx.url if here else None)

    def shutdown(self):
        self._flush_focus()
        self._ai_pool.shutdown(wait=False, cancel_futures=True)
        self._refine_pool.shutdown(wait=False, cancel_futures=True)
