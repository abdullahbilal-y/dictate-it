"""Task events -> card content. All user-facing wording for the cards lives here."""
import time

from ..ui.cards import CardContent
from .models import Task, format_duration, ACTIVE, PAUSED, READY, WAITING


def _hotkey(h: str) -> str:
    return "+".join(p.capitalize() for p in h.split("+"))


def _meta_for(task: Task) -> str:
    parts = [task.project or "Inbox"]
    if task.priority in ("high", "urgent"):
        parts.append(f"{task.priority.capitalize()} priority")
    return " · ".join(parts)


def hello(dictate_hotkey: str, task_hotkey: str, peek_hotkey: str, open_count: int) -> CardContent:
    queue = f"{open_count} open task{'s' if open_count != 1 else ''}" if open_count else "Queue is clear"
    return CardContent(kind="hello", eyebrow=f"DictateIt is ready \u00b7 {queue}",
                       title=f"{_hotkey(task_hotkey)} to add a task",
                       meta=f"{_hotkey(dictate_hotkey)} dictate \u00b7 {_hotkey(peek_hotkey)} queue",
                       icon="mic", hold_s=4.0, announce=f"DictateIt is ready. {queue}.")


def listening(task_hotkey: str, mode: str) -> CardContent:
    hint = "Release to finish" if mode == "ptt" else f"{_hotkey(task_hotkey)} again when you're done"
    return CardContent(kind="listening", eyebrow="Listening for a task", title="Say it naturally…",
                       meta=hint, icon="mic", hold_s=None, title_muted=True, level_bars=True,
                       announce="Listening for a task")


def thinking(transcript: str = "") -> CardContent:
    return CardContent(kind="thinking", eyebrow="Understanding", title=transcript or "One moment…",
                       icon="spinner", hold_s=None, shimmer=True)


def queued(task: Task, position, total) -> CardContent:
    where = f"#{position} of {total}" if position else "Added"
    return CardContent(kind="queued", eyebrow=f"Queued · {where}", title=task.title, meta=_meta_for(task),
                       icon="check", hold_s=3.4, exit_style="slide",
                       announce=f"Task queued: {task.title}. Position {position} of {total}.")


def already_queued(task: Task) -> CardContent:
    return CardContent(kind="info", eyebrow="Already in your queue", title=task.title, meta=_meta_for(task),
                       icon="info", hold_s=3.0, announce=f"Already queued: {task.title}")


def done(task: Task) -> CardContent:
    focused = f"{format_duration(task.focus_seconds)} focused" if task.focus_seconds >= 60 else "Nice work"
    return CardContent(kind="done", eyebrow="Done", title=task.title, meta=f"{focused} · {task.project or 'Inbox'}",
                       icon="check", hold_s=4.0, exit_style="dissolve", strike=True, celebrate=True,
                       buttons=(("undo", "Undo", False),),
                       announce=f"Done: {task.title}. Say undo to take it back.")


def removed(task: Task) -> CardContent:
    return CardContent(kind="removed", eyebrow="Removed", title=task.title, meta="Taken off your queue",
                       icon="x", hold_s=4.0, exit_style="collapse", fade_title=True,
                       buttons=(("undo", "Undo", False),),
                       announce=f"Removed: {task.title}. Say undo to take it back.")


def cancelled() -> CardContent:
    return CardContent(kind="info", eyebrow="Cancelled", title="Nothing was saved", meta="Esc throws a recording away",
                       icon="x", hold_s=1.8, announce="Cancelled")


def restored(task: Task, status: str) -> CardContent:
    return CardContent(kind="resume", eyebrow="Undone", title=task.title, meta=f"Back to {status}", icon="history",
                       hold_s=2.4, announce=f"Undone. {task.title} is back to {status}.")


def error(summary: str) -> CardContent:
    return CardContent(kind="removed", eyebrow="Something went wrong", title=summary[:80] or "Unexpected error",
                       meta="Nothing was lost · details in the log", icon="info", hold_s=5.0,
                       announce=f"Something went wrong: {summary}")


def status(task: Task, new_status: str) -> CardContent:
    if new_status == ACTIVE:
        meta = f"Last: {task.last_context}" if task.last_context else _meta_for(task)
        return CardContent(kind="active", eyebrow="Now working on", title=task.title, meta=meta, icon="play",
                           hold_s=2.6, announce=f"Now working on {task.title}")
    if new_status == PAUSED:
        meta = f"Place saved · {task.last_context}" if task.last_context else "Place saved"
        return CardContent(kind="paused", eyebrow="Paused", title=task.title, meta=meta, icon="pause",
                           hold_s=2.6, announce=f"Paused {task.title}")
    if new_status == WAITING:
        return CardContent(kind="waiting", eyebrow="Waiting on someone", title=task.title,
                           meta="Parked until you pick it back up", icon="clock", hold_s=2.6,
                           announce=f"{task.title} is waiting")
    return CardContent(kind="info", eyebrow=new_status.capitalize(), title=task.title, icon="info", hold_s=2.4)


def message(eyebrow: str, title: str, meta: str = "", kind: str = "info", icon: str = "info") -> CardContent:
    return CardContent(kind=kind, eyebrow=eyebrow, title=title, meta=meta, icon=icon, hold_s=2.8,
                       announce=f"{eyebrow}. {title}")


def nudge(task: Task, session_focus_s: float, moved_to: str, task_hotkey: str) -> CardContent:
    meta = f"{format_duration(session_focus_s)} on it · now in {moved_to}"
    return CardContent(kind="nudge", eyebrow="Wrapped up?", title=task.title, meta=meta, icon="question",
                       buttons=(("done", "Done", True), ("not_yet", "Not yet", False),
                                ("waiting", "Waiting", False)),
                       hold_s=30, exit_style="slide",
                       announce=f"Did you wrap up {task.title}? Say done, not yet, or waiting with "
                                f"{_hotkey(task_hotkey)}.")


def checkin(task: Task, app: str, where: str, dwell_s: float) -> CardContent:
    return CardContent(kind="active", eyebrow="Working on this?", title=task.title,
                       meta=f"{format_duration(dwell_s)} in {app} · {where}", icon="play",
                       buttons=(("checkin_yes", "Yes", True), ("checkin_other", "Other task", False),
                                ("checkin_no", "Not a task", False)),
                       hold_s=25, exit_style="slide",
                       announce=f"Are you working on {task.title}? Yes, other task, or not a task.")


PICK_TITLES = {"complete": "Which one is done?", "remove": "Which one should go?", "pause": "Which one to pause?",
               "wait": "Which one is waiting?", "start": "Which task are you on?"}


def pick(action: str, tasks, heard: str = ""):
    """'Which one?' capsules for a reference we couldn't pin down. Clicking a task capsule applies the action."""
    header = CardContent(kind="nudge", eyebrow="", title=PICK_TITLES.get(action, "Which task?"),
                         meta=f"Heard “{heard.strip()[:60]}”" if heard else "", icon="question",
                         capsule=True, tag="Click one", hold_s=14.0,
                         announce=f"{PICK_TITLES.get(action, 'Which task?')} "
                                  + "; ".join(t.title for t in tasks[:4]))
    items = [(header, None)]
    for t in tasks[:4]:
        items.append((CardContent(kind="peek", tag_kind=STATUS_KIND.get(t.status, "queued"), eyebrow="",
                                  title=t.title, meta=_capsule_meta(t), icon=STATUS_ICON.get(t.status, "list"),
                                  capsule=True, tag=STATUS_TAG.get(t.status, ""), hold_s=14.0,
                                  click_action=f"pick:{action}"), t.id))
    return items


def resume(task: Task) -> CardContent:
    ago = format_duration(time.time() - task.last_active_at) if task.last_active_at else ""
    where = task.last_context or task.last_app or ""
    meta = " · ".join(p for p in (f"You were on {where}" if where else "", f"{ago} ago" if ago else "") if p)
    return CardContent(kind="resume", eyebrow="Picking up", title=task.title, meta=meta, icon="history",
                       hold_s=5.0, announce=f"Picking up {task.title}")


STATUS_TAG = {ACTIVE: "Now", PAUSED: "Paused", READY: "Ready", WAITING: "Waiting"}
STATUS_KIND = {ACTIVE: "active", PAUSED: "paused", READY: "queued", WAITING: "waiting"}
STATUS_ICON = {ACTIVE: "play", PAUSED: "pause", READY: "list", WAITING: "clock"}
PEEK_MAX = 6


def _capsule_meta(t: Task) -> str:
    """Where this task lives / where you left it. A leading arrow means a click reopens that page."""
    from ..watch.browser import site_of
    if t.last_url:
        site = site_of(t.last_url)
        where = (t.last_context or t.project or "Inbox").removesuffix(f" \u00b7 {site}")
        return f"\u2197 {site} \u00b7 {where}"
    if t.last_context:
        return f"{t.last_app} \u00b7 {t.last_context}" if t.last_app else t.last_context
    return t.project or "Inbox"


def peek(tasks, completed_today: int):
    """Queue peek as a stack of capsules: a header, then one capsule per task (most relevant first).
    Returns [(CardContent, payload), ...] for TaskCardHost.show_group."""
    if not tasks:
        return [(CardContent(kind="peek", eyebrow="", title="Your queue is clear",
                             meta="Add one with your task hotkey", icon="check", capsule=True, hold_s=4.0,
                             tag="Empty", announce="Your queue is clear"), None)]
    counts = f"{len(tasks)} open" + (f" \u00b7 {completed_today} done today" if completed_today else "")
    spoken = "; ".join(f"{STATUS_TAG.get(t.status, '')}: {t.title}" for t in tasks[:PEEK_MAX])
    items = [(CardContent(kind="peek", eyebrow="", title="Your queue", icon="list", capsule=True,
                          tag=counts, hold_s=6.5, announce=f"{counts}. {spoken}"), None)]
    for t in tasks[:PEEK_MAX]:
        tag = STATUS_TAG.get(t.status, "")
        if t.status == PAUSED and t.last_active_at:
            tag = f"Paused {format_duration(time.time() - t.last_active_at)}"
        elif t.priority in ("high", "urgent") and t.status == READY:
            tag = t.priority.capitalize()
        items.append((CardContent(kind="peek", tag_kind=STATUS_KIND.get(t.status, "queued"), eyebrow="",
                                  title=t.title, meta=_capsule_meta(t), icon=STATUS_ICON.get(t.status, "list"),
                                  capsule=True, tag=tag, pulse=t.status == ACTIVE, hold_s=6.5,
                                  click_action="open_task"), t.id))
    more = len(tasks) - PEEK_MAX
    if more > 0:
        items.append((CardContent(kind="peek", tag_kind="info", eyebrow="", title=f"+{more} more",
                                  icon="list", capsule=True, tag="Tray menu", hold_s=6.5), None))
    return items
