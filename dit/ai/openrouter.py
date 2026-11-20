"""OpenRouter chat client tuned for the free tier: hard daily budget, 429 cooldown, JSON-only replies."""
import json
import re
import threading
import time
from typing import Optional, Tuple

import requests

API_URL = "https://openrouter.ai/api/v1/chat/completions"


def extract_json(text: str) -> Optional[dict]:
    """Models sometimes wrap JSON in prose or ``` fences; take the first decodable object."""
    if not text:
        return None
    text = re.sub(r"```(?:json)?", "", text)
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            obj, _ = decoder.raw_decode(text[match.start():])
            if isinstance(obj, dict):
                return obj
        except ValueError:
            continue
    return None


class OpenRouterClient:
    name = "OpenRouter"

    def __init__(self, api_key: str, models, store, daily_budget: int = 45, timeout_s: float = 12.0):
        self.api_key = api_key
        self.models = list(models)
        self.store = store
        self.daily_budget = daily_budget
        self.timeout_s = timeout_s
        self.enabled = bool(api_key)
        self._cooldown_until = 0.0
        self._last_sync = 0.0
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self.enabled and bool(self.api_key)

    def remaining_today(self) -> int:
        return max(0, self.daily_budget - self.store.ai_used_today())

    def status_text(self) -> str:
        if not self.api_key:
            return "AI: no OpenRouter key (rules only)"
        if not self.enabled:
            return "AI: off (rules only)"
        return f"AI: OpenRouter ({self.remaining_today()} calls left today)"

    def sync_usage(self) -> None:
        """The free quota is per account, not per machine: adopt OpenRouter's own count if it's higher."""
        if not self.api_key:
            return
        self._last_sync = time.time()
        try:
            resp = requests.get("https://openrouter.ai/api/v1/key", timeout=10,
                                headers={"Authorization": f"Bearer {self.api_key}"})
            if resp.status_code in (401, 403):
                self.enabled = False
                print(f"[AI] OpenRouter rejected the key (HTTP {resp.status_code}); running rules-only.")
                return
            info = resp.json().get("data", {})
            free = info.get("free_model_daily_requests") or {}
            if free.get("limit"):
                self.daily_budget = min(self.daily_budget, max(0, int(free["limit"]) - 5))
            if free.get("used") is not None:
                self.store.ai_set_used(int(free["used"]))
            print(f"[AI] OpenRouter free tier: {free.get('used', '?')}/{free.get('limit', '?')} used today "
                  f"-> {self.remaining_today()} calls available to DictateIt")
        except (requests.RequestException, ValueError) as e:
            print(f"[AI] Could not read OpenRouter usage ({e}); using local count.")

    def chat_json(self, system: str, user: str, purpose: str, max_share: float = 1.0) -> Tuple[Optional[dict], str]:
        """Returns (parsed_json_or_None, info). Never raises: callers always have a rules fallback."""
        if not self.available:
            return None, "unavailable"
        now = time.time()
        if now < self._cooldown_until:
            return None, f"cooldown {self._cooldown_until - now:.0f}s"
        with self._lock:
            used = self.store.ai_used_today()
            if used >= int(self.daily_budget * max_share) and time.time() - self._last_sync > 600:
                self.sync_usage()   # the quota may have rolled over (UTC midnight) since we last asked
                used = self.store.ai_used_today()
            if used >= int(self.daily_budget * max_share):
                return None, f"budget ({used}/{self.daily_budget} used, {purpose} share {max_share:.0%})"
            self.store.ai_increment()  # count attempts, not successes: the free tier does too

        payload = {
            "model": self.models[0],
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,
            "max_tokens": 600,
            # Free routing often lands on reasoning models; with thinking on they take 4-11s and can spend the
            # whole token budget before writing any content. Off: ~1s and clean JSON.
            "reasoning": {"enabled": False},
        }
        if len(self.models) > 1:
            payload["models"] = self.models
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/abdullahbilal-y/dictate-it",
            "X-Title": "DictateIt",
        }
        t0 = time.time()
        try:
            resp = requests.post(API_URL, headers=headers, json=payload, timeout=self.timeout_s)
            if resp.status_code == 400 and "reasoning is mandatory" in resp.text.lower():
                # Some free routes only serve thinking models: allow minimal, hidden reasoning and more tokens.
                payload["reasoning"] = {"effort": "low", "exclude": True}
                payload["max_tokens"] = 1500
                self.store.ai_increment()
                resp = requests.post(API_URL, headers=headers, json=payload, timeout=self.timeout_s)
        except requests.RequestException as e:
            print(f"[AI] {purpose}: network error {e}")
            return None, "network error"
        ms = (time.time() - t0) * 1000

        if resp.status_code == 429:
            self._cooldown_until = time.time() + 60
            print(f"[AI] {purpose}: rate limited (429) after {ms:.0f}ms, cooling down 60s")
            return None, "rate limited"
        if resp.status_code >= 400:
            print(f"[AI] {purpose}: HTTP {resp.status_code} after {ms:.0f}ms: {resp.text[:200]}")
            if resp.status_code in (401, 403):
                self.enabled = False  # bad key: stop burning attempts, fall back to rules
            return None, f"http {resp.status_code}"

        try:
            data = resp.json()
            message = data["choices"][0]["message"]
            content = message.get("content") or ""
            model_used = data.get("model", self.models[0])
        except (ValueError, KeyError, IndexError) as e:
            print(f"[AI] {purpose}: malformed response ({e}): {resp.text[:200]}")
            return None, "malformed"

        parsed = extract_json(content)
        used = self.store.ai_used_today()
        print(f"[AI] {purpose}: {model_used} {ms:.0f}ms -> {'ok' if parsed else 'unparseable'} "
              f"({used}/{self.daily_budget} used today)")
        if parsed is None:
            print(f"[AI] {purpose}: raw reply: {content[:200]!r}")
        return parsed, f"{model_used} {ms:.0f}ms"
