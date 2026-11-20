"""SQLite persistence for tasks, context segments, context->task links and AI budget. Local only."""
import os
import re
import sqlite3
import threading
import time
from datetime import date
from typing import List, Optional

from .models import Task, OPEN_STATUSES, ACTIVE, PAUSED, COMPLETED, queue_sort_key

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    project TEXT,
    priority TEXT NOT NULL DEFAULT 'normal',
    status TEXT NOT NULL DEFAULT 'ready',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    completed_at REAL,
    source_text TEXT,
    last_context TEXT,
    last_app TEXT,
    last_active_at REAL,
    focus_seconds REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    app TEXT NOT NULL,
    label TEXT NOT NULL,
    workspace TEXT,
    ctx_key TEXT NOT NULL,
    start_ts REAL NOT NULL,
    end_ts REAL,
    task_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_segments_start ON segments(start_ts);
CREATE TABLE IF NOT EXISTS context_links (
    ctx_key TEXT PRIMARY KEY,
    task_id INTEGER,
    source TEXT NOT NULL,
    confidence REAL,
    tasks_sig INTEGER,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS aliases (
    task_id INTEGER NOT NULL,
    phrase TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (task_id, phrase)
);
CREATE TABLE IF NOT EXISTS vocab (
    term TEXT PRIMARY KEY,
    count INTEGER NOT NULL DEFAULT 1,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_usage (
    day TEXT PRIMARY KEY,
    count INTEGER NOT NULL DEFAULT 0
);
"""

TASK_COLUMNS = ("id, title, project, priority, status, created_at, updated_at, completed_at, source_text, "
                "last_context, last_app, last_active_at, focus_seconds, last_url")

# Columns added after the first release; existing databases get them via ALTER TABLE on open.
MIGRATIONS = [("tasks", "last_url", "TEXT"), ("segments", "url", "TEXT")]


def default_db_path() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "DictateIt", "dictateit.db")


class TaskStore:
    def __init__(self, path: Optional[str] = None):
        self.path = path or default_db_path()
        if self.path != ":memory:":
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)
        for table, column, kind in MIGRATIONS:
            existing = {row[1] for row in self._db.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
        self._db.commit()

    # ---------------- tasks ----------------
    def _row_to_task(self, row) -> Task:
        return Task(*row)

    def add_task(self, title: str, project: Optional[str] = None, priority: str = "normal",
                 source_text: Optional[str] = None) -> Task:
        now = time.time()
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO tasks (title, project, priority, status, created_at, updated_at, source_text) "
                "VALUES (?, ?, ?, 'ready', ?, ?, ?)",
                (title, project, priority, now, now, source_text),
            )
            task_id = cur.lastrowid
            self._event(task_id, "created", source_text)
            self._db.commit()
        return self.get_task(task_id)

    def get_task(self, task_id: int) -> Optional[Task]:
        with self._lock:
            row = self._db.execute(f"SELECT {TASK_COLUMNS} FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def open_tasks(self) -> List[Task]:
        marks = ",".join("?" * len(OPEN_STATUSES))
        with self._lock:
            rows = self._db.execute(
                f"SELECT {TASK_COLUMNS} FROM tasks WHERE status IN ({marks})", OPEN_STATUSES
            ).fetchall()
            alias_rows = self._db.execute("SELECT task_id, phrase FROM aliases").fetchall()
        aliases = {}
        for tid, phrase in alias_rows:
            aliases.setdefault(tid, []).append(phrase)
        tasks = [self._row_to_task(r) for r in rows]
        for t in tasks:
            t.aliases = " | ".join(aliases.get(t.id, []))
        return sorted(tasks, key=queue_sort_key)

    # ---------------- learning ----------------
    def add_alias(self, task_id: int, phrase: str, source: str) -> bool:
        phrase = re.sub(r"\s+", " ", (phrase or "").strip().lower())[:80]
        if len(phrase) < 2:
            return False
        with self._lock:
            cur = self._db.execute("INSERT OR IGNORE INTO aliases (task_id, phrase, source, created_at) "
                                   "VALUES (?, ?, ?, ?)", (task_id, phrase, source, time.time()))
            self._db.commit()
            return cur.rowcount > 0

    def all_titles(self):
        with self._lock:
            return self._db.execute("SELECT title, project FROM tasks").fetchall()

    def alias_count(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM aliases").fetchone()[0]

    def bump_vocab(self, terms) -> None:
        now = time.time()
        with self._lock:
            for term in terms:
                self._db.execute("INSERT INTO vocab (term, count, updated_at) VALUES (?, 1, ?) "
                                 "ON CONFLICT(term) DO UPDATE SET count = count + 1, updated_at = excluded.updated_at",
                                 (term, now))
            self._db.commit()

    def top_vocab(self, limit: int = 30) -> List[str]:
        with self._lock:
            rows = self._db.execute("SELECT term FROM vocab ORDER BY count DESC, updated_at DESC LIMIT ?",
                                    (limit,)).fetchall()
        return [r[0] for r in rows]

    def recent_segments(self, limit: int = 6):
        """(app, label, minutes) of the latest finished working segments, newest first."""
        with self._lock:
            rows = self._db.execute(
                "SELECT app, label, COALESCE(end_ts, start_ts) - start_ts FROM segments "
                "WHERE end_ts IS NOT NULL AND end_ts - start_ts >= 20 ORDER BY start_ts DESC LIMIT ?",
                (limit,)).fetchall()
        return [(a, l, round(d / 60, 1)) for a, l, d in rows]

    def recent_completed(self, limit: int = 10) -> List[Task]:
        with self._lock:
            rows = self._db.execute(
                f"SELECT {TASK_COLUMNS} FROM tasks WHERE status = ? ORDER BY completed_at DESC LIMIT ?",
                (COMPLETED, limit),
            ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def active_task(self) -> Optional[Task]:
        with self._lock:
            row = self._db.execute(
                f"SELECT {TASK_COLUMNS} FROM tasks WHERE status = ? ORDER BY last_active_at DESC LIMIT 1",
                (ACTIVE,),
            ).fetchone()
        return self._row_to_task(row) if row else None

    def projects(self) -> List[str]:
        with self._lock:
            rows = self._db.execute(
                "SELECT project, MAX(updated_at) m FROM tasks WHERE project IS NOT NULL AND project != '' "
                "GROUP BY project ORDER BY m DESC LIMIT 20"
            ).fetchall()
        return [r[0] for r in rows]

    def max_task_id(self) -> int:
        with self._lock:
            row = self._db.execute("SELECT COALESCE(MAX(id), 0) FROM tasks").fetchone()
        return int(row[0])

    def queue_position(self, task_id: int):
        tasks = self.open_tasks()
        for i, t in enumerate(tasks):
            if t.id == task_id:
                return i + 1, len(tasks)
        return None, len(tasks)

    def set_status(self, task_id: int, status: str, detail: Optional[str] = None) -> Optional[Task]:
        """Change status. Making a task Active pauses whichever task was Active before."""
        now = time.time()
        with self._lock:
            current = self.get_task(task_id)
            if not current:
                return None
            if status == ACTIVE:
                for other in self._db.execute("SELECT id FROM tasks WHERE status = ? AND id != ?",
                                              (ACTIVE, task_id)).fetchall():
                    self._db.execute("UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                                     (PAUSED, now, other[0]))
                    self._event(other[0], "status:paused", f"switched to task {task_id}")
            completed_at = now if status == COMPLETED else None
            self._db.execute(
                "UPDATE tasks SET status = ?, updated_at = ?, completed_at = ?, "
                "last_active_at = CASE WHEN ? = 'active' THEN ? ELSE last_active_at END WHERE id = ?",
                (status, now, completed_at, status, now, task_id),
            )
            if current.status != status:
                self._event(task_id, f"status:{status}", detail)
            self._db.commit()
        return self.get_task(task_id)

    def update_task(self, task_id: int, title: str, project: Optional[str], priority: str) -> Optional[Task]:
        with self._lock:
            self._db.execute("UPDATE tasks SET title = ?, project = ?, priority = ?, updated_at = ? WHERE id = ?",
                             (title, project, priority, time.time(), task_id))
            self._event(task_id, "refined", title)
            self._db.commit()
        return self.get_task(task_id)

    def delete_task(self, task_id: int) -> None:
        """Hard delete. Only for a provisional task that turned out to be a misheard command."""
        with self._lock:
            self._db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            self._db.execute("DELETE FROM task_events WHERE task_id = ?", (task_id,))
            self._db.commit()

    def touch_context(self, task_id: int, label: str, app: str, focus_add: float = 0.0,
                      url: Optional[str] = None) -> None:
        now = time.time()
        with self._lock:
            self._db.execute(
                "UPDATE tasks SET last_context = ?, last_app = ?, last_active_at = ?, "
                "focus_seconds = focus_seconds + ?, last_url = COALESCE(?, last_url) WHERE id = ?",
                (label, app, now, focus_add, url, task_id),
            )
            self._db.commit()

    def add_event(self, task_id: int, kind: str, detail: Optional[str] = None) -> None:
        with self._lock:
            self._event(task_id, kind, detail)
            self._db.commit()

    def _event(self, task_id: int, kind: str, detail: Optional[str]) -> None:
        self._db.execute("INSERT INTO task_events (task_id, ts, kind, detail) VALUES (?, ?, ?, ?)",
                         (task_id, time.time(), kind, detail))

    # ---------------- context segments ----------------
    def open_segment(self, app: str, label: str, workspace: Optional[str], ctx_key: str, start_ts: float,
                     url: Optional[str] = None) -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO segments (app, label, workspace, ctx_key, start_ts, url) VALUES (?, ?, ?, ?, ?, ?)",
                (app, label, workspace, ctx_key, start_ts, url),
            )
            self._db.commit()
            return cur.lastrowid

    def close_segment(self, segment_id: int, end_ts: float, task_id: Optional[int]) -> None:
        with self._lock:
            self._db.execute("UPDATE segments SET end_ts = ?, task_id = ? WHERE id = ?",
                             (end_ts, task_id, segment_id))
            self._db.commit()

    def prune_segments(self, keep_days: int = 30) -> None:
        with self._lock:
            self._db.execute("DELETE FROM segments WHERE start_ts < ?", (time.time() - keep_days * 86400,))
            self._db.commit()

    # ---------------- context -> task links ----------------
    def get_link(self, ctx_key: str):
        with self._lock:
            return self._db.execute(
                "SELECT task_id, source, confidence, tasks_sig FROM context_links WHERE ctx_key = ?", (ctx_key,)
            ).fetchone()

    def set_link(self, ctx_key: str, task_id: Optional[int], source: str, confidence: float, tasks_sig: int) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO context_links (ctx_key, task_id, source, confidence, tasks_sig, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(ctx_key) DO UPDATE SET task_id = excluded.task_id, "
                "source = excluded.source, confidence = excluded.confidence, tasks_sig = excluded.tasks_sig, "
                "updated_at = excluded.updated_at",
                (ctx_key, task_id, source, confidence, tasks_sig, time.time()),
            )
            self._db.commit()

    # ---------------- AI budget ----------------
    @staticmethod
    def _usage_key(provider: str) -> str:
        day = date.today().isoformat()
        return day if provider == "openrouter" else f"{provider}:{day}"

    def ai_used_today(self, provider: str = "openrouter") -> int:
        with self._lock:
            row = self._db.execute("SELECT count FROM ai_usage WHERE day = ?", (self._usage_key(provider),)).fetchone()
        return int(row[0]) if row else 0

    def ai_increment(self, provider: str = "openrouter") -> int:
        with self._lock:
            self._db.execute("INSERT INTO ai_usage (day, count) VALUES (?, 1) "
                             "ON CONFLICT(day) DO UPDATE SET count = count + 1", (self._usage_key(provider),))
            self._db.commit()
        return self.ai_used_today(provider)

    def ai_set_used(self, used: int, provider: str = "openrouter") -> None:
        """Adopt OpenRouter's own count. It's authoritative: its day rolls over at midnight UTC, not local time,
        so keeping the higher local number blocked a fresh quota for hours (landmine #19)."""
        with self._lock:
            self._db.execute("INSERT INTO ai_usage (day, count) VALUES (?, ?) "
                             "ON CONFLICT(day) DO UPDATE SET count = excluded.count",
                             (self._usage_key(provider), used))
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()
