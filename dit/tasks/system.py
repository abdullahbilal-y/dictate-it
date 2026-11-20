"""Assembles everything beyond dictation: store, cards, AI client, manager, context watcher."""
import os

from ..env import get_secret


class TaskSystem:
    def __init__(self, config, feedback, project_dir: str, db_path=None, with_watcher=True):
        from .store import TaskStore
        from .manager import TaskManager
        from ..ui.host import TaskCardHost
        from ..ai.openrouter import OpenRouterClient

        self.store = TaskStore(db_path)
        self.store.prune_segments()
        if not self.store.top_vocab(1):   # first run with learning: seed names from every task you've added
            from .text import vocabulary_terms
            for title, project in self.store.all_titles():
                self.store.bump_vocab(vocabulary_terms(f"{title} {project or ''}"))
        self.ui = TaskCardHost(os.path.join(project_dir, config.animations_dir), style=config.card_style,
                               palette=config.paper_theme)
        self.ui.ready.wait(5)
        if self.ui.failed:
            raise RuntimeError(f"Task cards failed to start: {self.ui.failed}")

        from ..ai.groq import GroqChatClient, ChainClient
        or_key = get_secret("OPENROUTER_API_KEY") if config.ai_enabled else ""
        groq_key = get_secret("GROQ_API_KEY")
        openrouter = OpenRouterClient(or_key, config.ai_models, self.store, config.ai_daily_budget, config.ai_timeout_s)
        groq_chat = GroqChatClient(groq_key if config.ai_enabled else "", config.groq_models, self.store,
                                   config.groq_daily_budget) if groq_key else None
        self.ai = ChainClient([groq_chat, openrouter])
        self.groq_key = groq_key
        self.manager = TaskManager(config, self.store, self.ui, feedback, self.ai)
        self.ui.on_action = self.manager.on_card_action

        self.watcher = None
        if with_watcher and config.watcher_enabled:
            from ..watch.watcher import ContextWatcher
            self.watcher = ContextWatcher(config, self.manager.on_segment_start,
                                          self.manager.on_segment_end, self.manager.on_tick)
        print(f"[Tasks] Store: {self.store.path} ({len(self.store.open_tasks())} open tasks)")
        print(f"[Tasks] {self.ai.status_text()}")

    def start(self):
        import threading
        threading.Thread(target=self.ai.sync_usage, name="AIUsageSync", daemon=True).start()
        if self.manager.config.startup_card:
            self.manager.greet()
        if self.watcher:
            self.watcher.start()

    def stop(self):
        if self.watcher:
            self.watcher.stop()
        self.manager.shutdown()
        self.ui.stop()
