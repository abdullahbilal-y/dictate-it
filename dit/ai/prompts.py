"""Prompts. Everything sent to OpenRouter is built here, so it's easy to audit what leaves the machine."""
import json

INTENT_SYSTEM = """You turn one short spoken command into an action on a personal task queue.
Reply with ONLY a JSON object, no prose:
{"action": "add|complete|remove|pause|wait|start|peek|none",
 "task_id": <id of an existing task, or null>,
 "title": <for add: short imperative task title, else null>,
 "project": <for add: short project name or null>,
 "priority": "low|normal|high|urgent"}

Rules:
- add: something new to do. Make the title concise and imperative using the user's own verb, only drop
  filler words ("I need to finish the November financial report" -> "Finish November financial report").
  Keep names, dates and numbers. Fix obvious speech-to-text casing (oauth -> OAuth, q3 -> Q3).
- project: reuse one of the existing project names when it fits; otherwise invent a 1-3 word name
  (e.g. "Financial reporting"); null when there's no clear project.
- complete / remove / pause / wait / start refer to an existing task: choose its task_id from open_tasks.
  "it", "that", "yes", "yeah it's done" refer to pending_question_task_id, else to active_task_id.
- pause also covers "not yet", "later", "park it". wait = blocked / waiting on someone.
- start = "working on X now", "switch to X", "back to X".
- peek = asking what's next, what's in the queue, what am I doing.
- priority is normal unless urgency ("urgent", "asap", "important") or low importance is said.
- none = not a task command at all.
- user_context shows what the user has been doing (recent windows with minutes spent, tasks finished today,
  phrases they've used for tasks before). Use it to resolve vague references like "the one I was just doing"."""

LINK_SYSTEM = """You decide whether the window the user is currently working in belongs to one of their open tasks.
Reply with ONLY a JSON object, no prose: {"task_id": <id from open_tasks, or null>, "confidence": <0.0-1.0>}

Be strict: return null unless the window shares something SPECIFIC with the task: a name, company, customer,
document, ticket/PR number, repo or product that appears in both. Being the only open task is not evidence.
Games, chat apps, email inboxes, social media, news, video sites, AI chat assistants, search pages and settings
are always null unless their title names the task's specific subject. When in doubt, null."""


def _task_brief(task):
    brief = {"id": task.id, "title": task.title, "project": task.project, "status": task.status}
    if getattr(task, "aliases", ""):
        brief["user_calls_it"] = task.aliases.split(" | ")[:6]
    return brief


def intent_user_message(command, open_tasks, projects, pending_task_id, active_task_id, context=None) -> str:
    return json.dumps({
        "command": command,
        "user_context": context or {},
        "open_tasks": [_task_brief(t) for t in open_tasks[:25]],
        "existing_projects": projects[:15],
        "pending_question_task_id": pending_task_id,
        "active_task_id": active_task_id,
    }, ensure_ascii=False)


def link_user_message(ctx, recent_contexts, open_tasks) -> str:
    return json.dumps({
        "window": {"app": ctx.app, "title": ctx.label, "workspace": ctx.workspace, "url": ctx.url,
                   "git_branch": ctx.branch},
        "recent_windows": recent_contexts[-4:],
        "open_tasks": [_task_brief(t) for t in open_tasks[:25]],
    }, ensure_ascii=False)
