"""Groq chat client (OpenAI-compatible) and the provider chain used by the task system.

Groq's free tier (Nov 2026) gives 1,000 requests/day per chat model at ~0.3-1s, vs OpenRouter free's 50/day,
so it goes first. Same contract as OpenRouterClient: chat_json never raises; callers always have rules."""
import threading
import time
from typing import Optional, Tuple

import requests

from .openrouter import extract_json

API_URL = "https://api.groq.com/openai/v1/chat/completions"
PROVIDER = "groq"


class GroqChatClient:
    name = "Groq"

    def __init__(self, api_key: str, models, store, daily_budget: int = 900, timeout_s: float = 10.0):
        self.api_key = api_key
        self.models = list(models)
        self.store = store
        self.daily_budget = daily_budget
        self.timeout_s = timeout_s
        self.enabled = bool(api_key)
        self._cooldown = {}          # model -> until
        self._plain = set()          # models that rejected the optional params below
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        now = time.time()
        return self.enabled and bool(self.api_key) and any(self._cooldown.get(m, 0) <= now for m in self.models)

    def remaining_today(self) -> int:
        return max(0, self.daily_budget - self.store.ai_used_today(PROVIDER))

    def status_text(self) -> str:
        return f"Groq ({self.remaining_today()} left)" if self.available else "Groq (off)"

    def sync_usage(self) -> None:
        pass   # Groq reports remaining requests in response headers; synced in chat_json

    def chat_json(self, system: str, user: str, purpose: str, max_share: float = 1.0) -> Tuple[Optional[dict], str]:
        if not self.available:
            return None, "unavailable"
        with self._lock:
            used = self.store.ai_used_today(PROVIDER)
            if used >= int(self.daily_budget * max_share):
                return None, f"budget ({used}/{self.daily_budget} used, {purpose} share {max_share:.0%})"
        last_info = "no model"
        for model in self.models:
            if self._cooldown.get(model, 0) > time.time():
                continue
            obj, info, retry_next = self._call(model, system, user, purpose)
            if obj is not None or not retry_next:
                return obj, info
            last_info = info
        return None, last_info

    def _call(self, model, system, user, purpose):
        """(obj, info, try_next_model)."""
        payload = {"model": model, "temperature": 0, "max_completion_tokens": 600,
                   "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if model not in self._plain:
            payload["response_format"] = {"type": "json_object"}
            if "gpt-oss" in model:
                payload["reasoning_effort"] = "low"
                payload["include_reasoning"] = False
            elif "qwen" in model:
                payload["reasoning_effort"] = "none"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        self.store.ai_increment(PROVIDER)
        t0 = time.time()
        try:
            resp = requests.post(API_URL, headers=headers, json=payload, timeout=self.timeout_s)
            if resp.status_code == 400 and model not in self._plain and "json_validate_failed" not in resp.text:
                self._plain.add(model)   # this model doesn't take one of the optional params: retry bare
                print(f"[AI] Groq {model}: optional params rejected ({resp.text[:120]}); retrying without them")
                return self._call(model, system, user, purpose)
        except requests.RequestException as e:
            print(f"[AI] {purpose}: Groq {model} network error {e}")
            return None, "network error", True
        ms = (time.time() - t0) * 1000
        self._sync_from_headers(resp)

        if resp.status_code == 429:
            wait = float(resp.headers.get("retry-after", "60") or 60)
            self._cooldown[model] = time.time() + min(wait, 3600)
            print(f"[AI] {purpose}: Groq {model} rate limited, cooling down {wait:.0f}s")
            return None, "rate limited", True
        if resp.status_code in (401, 403):
            self.enabled = False
            print(f"[AI] Groq rejected the key (HTTP {resp.status_code}); Groq chat disabled.")
            return None, f"http {resp.status_code}", False
        if resp.status_code in (404, 400):
            print(f"[AI] {purpose}: Groq {model} HTTP {resp.status_code}: {resp.text[:160]}")
            if resp.status_code == 404:
                self._cooldown[model] = time.time() + 24 * 3600   # model retired: skip it today
            return None, f"http {resp.status_code}", True
        if resp.status_code >= 500:
            return None, f"http {resp.status_code}", True
        try:
            content = resp.json()["choices"][0]["message"].get("content") or ""
        except (ValueError, KeyError, IndexError) as e:
            return None, f"malformed ({e})", True
        parsed = extract_json(content)
        print(f"[AI] {purpose}: groq {model} {ms:.0f}ms -> {'ok' if parsed else 'unparseable'} "
              f"({self.store.ai_used_today(PROVIDER)}/{self.daily_budget} used today)")
        return parsed, f"groq {model} {ms:.0f}ms", parsed is None

    def _sync_from_headers(self, resp):
        try:
            limit = int(resp.headers.get("x-ratelimit-limit-requests", ""))
            remaining = int(resp.headers.get("x-ratelimit-remaining-requests", ""))
            self.store.ai_set_used(max(0, limit - remaining), PROVIDER)
        except ValueError:
            pass


class ChainClient:
    """Tries providers in order (Groq, then OpenRouter). Looks like a single client to the rest of the app."""

    def __init__(self, clients):
        self.clients = [c for c in clients if c is not None]

    @property
    def api_key(self):
        return next((c.api_key for c in self.clients if c.api_key), "")

    @property
    def enabled(self):
        return any(c.enabled for c in self.clients)

    @enabled.setter
    def enabled(self, value):
        for c in self.clients:
            c.enabled = bool(value) and bool(c.api_key)

    @property
    def available(self):
        return any(c.available for c in self.clients)

    def remaining_today(self):
        return sum(c.remaining_today() for c in self.clients if c.available)

    def status_text(self):
        live = [c for c in self.clients if c.api_key]
        if not live:
            return "AI: no key (rules only)"
        if not self.enabled:
            return "AI: off (rules only)"
        parts = []
        for c in live:
            name = getattr(c, "name", "OpenRouter")
            parts.append(f"{name} {c.remaining_today()} left" if c.available else f"{name} off")
        return "AI: " + " · ".join(parts)

    def sync_usage(self):
        for c in self.clients:
            c.sync_usage()

    def chat_json(self, system, user, purpose, max_share=1.0):
        info = "unavailable"
        for c in self.clients:
            if not c.available:
                continue
            obj, info = c.chat_json(system, user, purpose, max_share)
            if obj is not None:
                return obj, info
        return None, info
