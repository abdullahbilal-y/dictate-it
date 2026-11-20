from dataclasses import dataclass
from typing import Optional

READY = "ready"
ACTIVE = "active"
PAUSED = "paused"
WAITING = "waiting"
COMPLETED = "completed"
REMOVED = "removed"   # soft delete: kept for history, never shown in the queue

OPEN_STATUSES = (ACTIVE, PAUSED, READY, WAITING)
PRIORITIES = ("low", "normal", "high", "urgent")
PRIORITY_RANK = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
# Queue order: what you're on, then what got interrupted, then fresh work, then blocked work.
STATUS_RANK = {ACTIVE: 0, PAUSED: 1, READY: 2, WAITING: 3}


@dataclass
class Task:
    id: int
    title: str
    project: Optional[str]
    priority: str
    status: str
    created_at: float
    updated_at: float
    completed_at: Optional[float] = None
    source_text: Optional[str] = None
    last_context: Optional[str] = None
    last_app: Optional[str] = None
    last_active_at: Optional[float] = None
    focus_seconds: float = 0.0
    last_url: Optional[str] = None   # last browser page worked on for this task (reopenable)
    aliases: str = ""                # learned spoken names for this task (from your corrections), space-joined

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES


def queue_sort_key(task: Task):
    recency = -(task.last_active_at or 0.0) if task.status == PAUSED else task.created_at
    return (STATUS_RANK.get(task.status, 9), PRIORITY_RANK.get(task.priority, 2), recency)


def format_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m" if minutes else f"{hours}h"
