"""Anthropic Messages API over plain HTTPS (no SDK dependency)."""

import os
import time

import requests

from .base import Completion, Provider

URL = "https://api.anthropic.com/v1/messages"
RETRY_STATUS = {429, 500, 502, 503, 529}


class AnthropicProvider(Provider):
    def __init__(self, reviewer: dict, session: requests.Session | None = None):
        self.model = reviewer["model"]
        self.key = os.environ.get(reviewer["secret"], "")
        if not self.key:
            raise RuntimeError(f"environment variable {reviewer['secret']} is not set")
        self.session = session or requests.Session()

    def complete(self, system: str, messages: list[dict], max_output_tokens: int) -> Completion:
        payload = {"model": self.model, "max_tokens": max_output_tokens, "system": system, "messages": messages}
        headers = {"x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        for attempt in range(4):
            r = self.session.post(URL, json=payload, headers=headers, timeout=900)
            if r.status_code in RETRY_STATUS and attempt < 3:
                time.sleep(float(r.headers.get("retry-after", 10 * 2 ** attempt)))
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"Anthropic API {r.status_code}: {r.text[:500]}")
            data = r.json()
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            usage = data.get("usage", {})
            if data.get("stop_reason") == "max_tokens":
                text += "\n[harness note: reply stopped at max_tokens]"
            return Completion(text, usage.get("input_tokens", 0), usage.get("output_tokens", 0))
        raise RuntimeError("Anthropic API: retries exhausted")
