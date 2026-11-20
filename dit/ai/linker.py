"""Context -> task linking. Tiered so the free tier lasts: user/AI cache -> local word overlap -> AI (cached)."""
from typing import Optional, Tuple

from ..tasks.text import tokens, task_tokens, overlap, is_confident_link
from .prompts import LINK_SYSTEM, link_user_message

AI_MIN_CONFIDENCE = 0.75   # 0.6 linked a game, every Edge tab and VS Code to one task (Nov 2026 log)


class ContextLinker:
    def __init__(self, store, client, link_share: float = 0.6):
        self.store = store
        self.client = client
        self.link_share = link_share

    def cached(self, ctx, open_ids) -> Tuple[bool, Optional[int], Optional[str]]:
        """(hit, task_id, source). A cached 'no task' only counts if no tasks were added since it was decided."""
        row = self.store.get_link(ctx.key)
        if not row:
            return False, None, None
        task_id, source, _confidence, tasks_sig = row
        if task_id is not None:
            return (True, task_id, source) if task_id in open_ids else (False, None, None)
        if tasks_sig is not None and tasks_sig >= self.store.max_task_id():
            return True, None, source
        return False, None, None

    def local(self, ctx, tasks) -> Tuple[Optional[int], float]:
        url_path = ctx.url.split("://", 1)[-1] if ctx.url else ""
        ctx_toks = tokens(f"{ctx.label} {ctx.workspace or ''} {ctx.branch or ''} {url_path}")
        best_id, best_score = None, 0.0
        for task in tasks:
            t_toks = task_tokens(task.title, task.project)
            score, hits = overlap(t_toks, ctx_toks)
            if is_confident_link(score, hits, len(t_toks)) and score > best_score:
                best_id, best_score = task.id, score
        return best_id, best_score

    def ai(self, ctx, tasks, recent_contexts) -> Tuple[bool, Optional[int], float]:
        """(asked, task_id, confidence). asked=False means no AI call happened (budget/no key)."""
        if not self.client or not self.client.available or not tasks:
            return False, None, 0.0
        obj, info = self.client.chat_json(LINK_SYSTEM, link_user_message(ctx, recent_contexts, tasks),
                                          purpose="link", max_share=self.link_share)
        if obj is None:
            return info not in ("unavailable",) and not info.startswith(("budget", "cooldown")), None, 0.0
        open_ids = {t.id for t in tasks}
        try:
            task_id = int(obj["task_id"]) if obj.get("task_id") is not None else None
            confidence = float(obj.get("confidence", 0.0))
        except (TypeError, ValueError, KeyError):
            return True, None, 0.0
        if task_id not in open_ids or confidence < AI_MIN_CONFIDENCE:
            return True, None, confidence
        return True, task_id, confidence
