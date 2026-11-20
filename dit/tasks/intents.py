"""Spoken command -> Intent. AI first when it's worth a call; deterministic rules as the always-on fallback."""
import re
from dataclasses import dataclass
from typing import Optional, List

from .models import Task, PRIORITIES
from .text import best_task_match, all_task_matches, ref_score, normalize_title, tokens, task_text

ACTIONS = ("add", "complete", "remove", "pause", "wait", "start", "peek", "undo", "none")


@dataclass
class Intent:
    action: str
    task_id: Optional[int] = None
    title: Optional[str] = None
    project: Optional[str] = None
    priority: str = "normal"
    source: str = "rules"
    task_ids: tuple = ()          # "all DP World tasks are done" -> several tasks at once
    candidates: tuple = ()        # unresolved reference: likely tasks to offer as "Which one?" capsules


PEEK_PATTERNS = [
    r"^what'?s next", r"^what is next", r"^(show|open)( me)?( my)? (queue|tasks|task list)",
    r"^what am i (doing|working on)", r"^(list|read)( my)? tasks", r"^queue$", r"^what'?s in (my|the) queue",
]
UNDO = r"^(undo|undo that|oops|wrong task|wrong one|not that one|that'?s wrong|that was wrong|go back)\b"
YES_DONE = r"^(yes|yeah|yep|yup|done|finished|all done|it'?s done|that'?s done|it is done|that is done|complete)\b"
NOT_YET = r"^(no|nope|not yet|not done|later|still (on it|working))\b"
REFERS_TO_CURRENT = {"", "it", "that", "this", "this one", "that one", "this task", "that task", "current task",
                     "last task", "the last task", "last one", "the last one", "previous task", "the previous one",
                     "previous one", "what i just added", "the one i just added", "just added"}

# Past-tense "it's finished" vocabulary. Imperatives ("finish X", "complete X", "check X") stay task-adds.
DONE_WORDS = (r"(?:done|finished|completed|wrapped up|closed out|shipped|submitted|fixed|sorted(?: out)?|"
              r"resolved|handled|checked|sent|paid|cleared|delivered|uploaded|taken care of|over with)")
# Statements about the future are new work even when they contain "done": "make sure X is done by Friday".
FUTURE_PREFIX = (r"^(?:i need to|i have to|i've got to|i got to|i should|i must|need to|have to|remind me|"
                 r"make sure|don't forget|do not forget|todo|to do|gotta|we need to|let's|please|"
                 r"finish|complete|check|fix|send|submit|pay)\b")
FUTURE_DONE = r"\b(get|gets|getting|have|has)\b.*\bdone\b|\bdone by\b|\bbefore\b|\buntil\b|\bby (monday|tuesday|" \
              r"wednesday|thursday|friday|saturday|sunday|tomorrow|tonight|eod|end of)\b"
REF_FILLER = (r"\b(yes|yeah|yep|yup|ok|okay|sure|i was|i am|i'm|i've|i have|i|we|is|are|was|were|has been|"
              r"have been|got|it's|that's|also|"
              r"already|just|now|and|with|the|my|mark|as|all|of|those|these|task|tasks|one|ones|"
              r"them|it|i mean|part)\b")

VERB_PATTERNS = [
    ("remove", r"^(?:remove|delete|cancel|drop|scratch|forget(?: about)?|never ?mind)(?P<ref>.*)$"),
    ("wait", r"^(?:i'?m )?(?:waiting (?:on|for)|blocked (?:on|by))(?P<ref>.*)$"),
    ("wait", r"^(?:mark )?(?P<ref>.+?) (?:as )?(?:waiting|blocked)$"),
    ("pause", r"^(?:pause|park|hold|put aside)(?P<ref>.*)$"),
    ("start", r"^(?:start|switch to|work on|working on|i'?m working on|resume|back to|focus on)(?P<ref>.*)$"),
]
ADD_PREFIX = (r"^(?:(?:please )?add(?: a)?(?: new)?(?: task)?(?: to)?(?: my queue)?(?: to)?|new task|"
              r"remind me to|i need to|i have to|i've got to|i got to|todo|to do|task)[:,]?\s+")


def _clean(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[\"“”]", "", text)
    return re.sub(r"\s+", " ", text).strip(" .,!?;:")


def _strip_ref(ref: str) -> str:
    ref = ref.strip(" .,!?;:")
    ref = re.sub(r"^(the|my|that|this)\s+", "", ref)
    ref = re.sub(r"\s+(task|one)$", "", ref)
    return ref.strip()


def _priority_from(text: str):
    lowered = text.lower()
    if re.search(r"\b(urgent|asap|right away|immediately)\b", lowered):
        priority = "urgent"
    elif re.search(r"\b(high priority|important|top priority)\b", lowered):
        priority = "high"
    elif re.search(r"\b(low priority|whenever|someday|no rush)\b", lowered):
        priority = "low"
    else:
        return "normal", text
    stripped = re.sub(r"[,.]?\s*\b(it'?s |this is )?(urgent|asap|right away|immediately|high priority|important|"
                      r"top priority|low priority|whenever|someday|no rush)\b", "", text, flags=re.I)
    return priority, stripped


def _resolve(ref: str, tasks: List[Task], default_id):
    ref = _strip_ref(ref)
    if ref in REFERS_TO_CURRENT:
        return default_id
    task, score = best_task_match(ref, tasks)
    return task.id if task and score >= 0.34 else None


def _candidates(ref: str, tasks: List[Task], limit: int = 4):
    """Most likely tasks for a reference we couldn't pin down: best word match first, then most recent."""
    scored = sorted(tasks, key=lambda t: (-ref_score(ref, task_text(t)),
                                          -(t.last_active_at or t.updated_at or t.created_at)))
    return tuple(t.id for t in scored[:limit])


def is_completion(t: str) -> bool:
    """A statement that something is finished ("account is fixed", "I was done with X", "DP World done")."""
    if re.match(ADD_PREFIX, t) or re.match(FUTURE_PREFIX, t) or re.search(FUTURE_DONE, t):
        return False
    return re.search(rf"\b{DONE_WORDS}\b", t) is not None


def _completion(t: str, tasks: List[Task], default_id) -> Intent:
    ref = re.sub(rf"\b{DONE_WORDS}\b", " ", t)
    ref = re.sub(r"[.,!?;:]", " ", ref)
    wants_all = re.search(r"\ball\b", t) is not None
    core = re.sub(r"\s+", " ", re.sub(REF_FILLER, " ", ref)).strip()
    if (not core or _strip_ref(ref) in REFERS_TO_CURRENT or core in REFERS_TO_CURRENT
            or core in ("last", "latest", "previous", "recent", "that", "this")):
        if default_id:
            return Intent("complete", task_id=default_id)
        return Intent("complete", candidates=_candidates("", tasks))
    if wants_all:
        matches = all_task_matches(core, tasks)
        if matches:
            return Intent("complete", task_id=matches[0].id, task_ids=tuple(m.id for m in matches))
    scored = sorted(((ref_score(core, task_text(t)), t) for t in tasks),
                    key=lambda st: -st[0])
    if scored and scored[0][0] >= 0.34:
        top = scored[0][0]
        tied = [t for sc, t in scored if sc >= top - 0.05]
        if len(tied) == 1:
            return Intent("complete", task_id=tied[0].id)
        return Intent("complete", candidates=tuple(t.id for t in tied[:4]))   # two DP World tasks: ask
    return Intent("complete", candidates=_candidates(core, tasks))


def reference_core(text: str) -> str:
    """The part of a command that names the task ("DP World is done" -> "dp world"), for learning aliases."""
    t = _clean(text)
    t = re.sub(ADD_PREFIX, "", t)
    t = re.sub(rf"\b{DONE_WORDS}\b", " ", t)
    t = re.sub(r"^(?:remove|delete|cancel|drop|pause|park|start|switch to|work on|working on|resume|back to|"
               r"waiting (?:on|for)|blocked (?:on|by))\b", " ", t)
    t = re.sub(r"[.,!?;:]", " ", t)
    return re.sub(r"\s+", " ", re.sub(REF_FILLER, " ", t)).strip()


def is_trivial(text: str, pending_id) -> bool:
    """Commands the rules handle perfectly; don't spend a free-tier AI call on them."""
    t = _clean(text)
    if any(re.search(p, t) for p in PEEK_PATTERNS) or re.search(UNDO, t):
        return True
    if pending_id and (re.search(YES_DONE, t) or re.search(NOT_YET, t)) and len(t.split()) <= 5:
        return True
    return False


def parse_rules(text: str, tasks: List[Task], pending_id=None, active_id=None, recent_id=None) -> Intent:
    """recent_id: the most recently added/touched open task, so "done that" / "last task is done" resolve."""
    t = _clean(text)
    if not t:
        return Intent("none")
    if any(re.search(p, t) for p in PEEK_PATTERNS):
        return Intent("peek")
    if re.search(UNDO, t) and len(t.split()) <= 5:
        return Intent("undo")

    explicit_add = re.match(ADD_PREFIX, t) is not None
    target_default = pending_id or active_id or recent_id
    if not explicit_add and len(t.split()) <= 5:
        if re.search(NOT_YET, t) and (pending_id or active_id):
            return Intent("pause", task_id=pending_id or active_id)

    if not explicit_add and is_completion(t):
        return _completion(t, tasks, target_default)

    for action, pattern in ([] if explicit_add else VERB_PATTERNS):
        m = re.match(pattern, t)
        if m:
            task_id = _resolve(m.group("ref"), tasks, pending_id or active_id)
            if task_id:
                return Intent(action, task_id=task_id)
            # A verb we recognise but no task we can find: offer candidates rather than inventing a task.
            if action != "start":
                return Intent(action, candidates=_candidates(_strip_ref(m.group("ref")), tasks))

    priority, body = _priority_from(text)
    body = re.sub(ADD_PREFIX, "", body.strip(), flags=re.I)
    title = normalize_title(body)
    if not tokens(title) and len(title) < 3:
        return Intent("none")
    return Intent("add", title=title, priority=priority)


def validate_ai_intent(obj: dict, tasks: List[Task]) -> Optional[Intent]:
    if not isinstance(obj, dict):
        return None
    action = str(obj.get("action", "")).lower().strip()
    if action not in ACTIONS:
        return None
    priority = str(obj.get("priority") or "normal").lower()
    if priority not in PRIORITIES:
        priority = "normal"
    open_ids = {t.id for t in tasks}
    task_id = obj.get("task_id")
    try:
        task_id = int(task_id) if task_id is not None else None
    except (TypeError, ValueError):
        task_id = None
    if task_id not in open_ids:
        task_id = None

    if action == "add":
        title = normalize_title(str(obj.get("title") or ""))
        if not title:
            return None
        project = obj.get("project")
        project = normalize_title(str(project))[:40] if project else None
        return Intent("add", title=title[:160], project=project, priority=priority, source="ai")
    if action in ("complete", "remove", "pause", "wait", "start") and task_id is None:
        return None  # let the rules try to resolve the reference
    return Intent(action, task_id=task_id, priority=priority, source="ai")
