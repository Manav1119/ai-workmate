"""Provider-agnostic LLM interface with structured JSON output, timeouts and retry limits."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from app.config import Settings, get_settings

log = logging.getLogger("workmate.llm")


class LLMError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class LLMResult:
    data: dict
    input_tokens: int
    output_tokens: int
    latency_ms: int
    model: str


@dataclass
class UsageTracker:
    calls: list[dict] = field(default_factory=list)

    def record(self, step: str, r: LLMResult | None, error: str | None = None) -> None:
        self.calls.append({
            "step": step, "model": r.model if r else None,
            "input_tokens": r.input_tokens if r else 0, "output_tokens": r.output_tokens if r else 0,
            "latency_ms": r.latency_ms if r else 0, "error": error,
        })

    def summary(self, s: Settings | None = None) -> dict:
        s = s or get_settings()
        it = sum(c["input_tokens"] for c in self.calls)
        ot = sum(c["output_tokens"] for c in self.calls)
        return {
            "llm_calls": len(self.calls), "input_tokens": it, "output_tokens": ot,
            "estimated_cost_usd": round(it / 1e6 * s.llm_input_cost_per_mtok + ot / 1e6 * s.llm_output_cost_per_mtok, 6),
            "calls": self.calls,
        }


class LLMProvider(Protocol):
    name: str
    model: str

    def complete_json(self, *, system: str, user: str, schema: dict, schema_name: str,
                      max_tokens: int = 2000) -> LLMResult: ...


RETRYABLE = {408, 409, 429, 500, 502, 503, 504, 529}


def post_with_retries(client: httpx.Client, url: str, *, headers: dict, payload: dict, retries: int) -> httpx.Response:
    attempt = 0
    while True:
        try:
            resp = client.post(url, headers=headers, json=payload)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            if attempt >= retries:
                raise LLMError("llm_unavailable", f"LLM provider request failed: {type(e).__name__}") from e
            attempt += 1
            time.sleep(min(2 ** attempt * 0.5, 8))
            continue
        if resp.status_code in RETRYABLE and attempt < retries:
            attempt += 1
            ra = resp.headers.get("retry-after")
            time.sleep(min(float(ra) if ra and ra.replace(".", "").isdigit() else 2 ** attempt * 0.5, 10))
            continue
        if resp.status_code == 401 or resp.status_code == 403:
            raise LLMError("llm_auth_failed", "The LLM provider rejected the configured API key.")
        if resp.status_code >= 400:
            log.warning("LLM provider HTTP %s", resp.status_code)
            raise LLMError("llm_error", f"LLM provider returned HTTP {resp.status_code}.")
        return resp


def parse_json_text(text: str) -> dict:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end < start:
        raise LLMError("llm_bad_output", "LLM did not return JSON.")
    try:
        return json.loads(t[start : end + 1])
    except json.JSONDecodeError as e:
        raise LLMError("llm_bad_output", "LLM returned malformed JSON.") from e
