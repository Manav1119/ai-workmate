"""Concrete providers (HTTP, server-side only). Keys never leave the backend."""

from __future__ import annotations

import time

import httpx

from app.config import Settings, get_settings
from app.llm.base import LLMError, LLMProvider, LLMResult, parse_json_text, post_with_retries


class AnthropicProvider:
    """Anthropic Messages API. Structured output via a forced tool call whose input_schema is our JSON schema."""

    name = "anthropic"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.model = settings.resolved_llm_model
        self._key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
        self._base = (settings.llm_base_url or "https://api.anthropic.com").rstrip("/")
        self._retries = settings.llm_max_retries
        self._client = client or httpx.Client(timeout=settings.llm_timeout_s)

    def complete_json(self, *, system: str, user: str, schema: dict, schema_name: str, max_tokens: int = 2000) -> LLMResult:
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": 0,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": [{"name": schema_name, "description": f"Return the {schema_name} object.", "input_schema": schema}],
            "tool_choice": {"type": "tool", "name": schema_name},
        }
        headers = {"x-api-key": self._key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        t0 = time.perf_counter()
        resp = post_with_retries(self._client, f"{self._base}/v1/messages", headers=headers, payload=payload,
                                 retries=self._retries)
        body = resp.json()
        data = None
        for block in body.get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == schema_name:
                data = block.get("input")
            elif block.get("type") == "text" and data is None:
                try:
                    data = parse_json_text(block.get("text", ""))
                except LLMError:
                    pass
        if not isinstance(data, dict):
            raise LLMError("llm_bad_output", "LLM response did not contain the structured object.")
        usage = body.get("usage", {})
        return LLMResult(data, int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0)),
                         int((time.perf_counter() - t0) * 1000), body.get("model", self.model))


class OpenAIProvider:
    """OpenAI-compatible Chat Completions with JSON-schema response_format."""

    name = "openai"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.model = settings.resolved_llm_model
        self._key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
        self._base = (settings.llm_base_url or "https://api.openai.com/v1").rstrip("/")
        self._retries = settings.llm_max_retries
        self._client = client or httpx.Client(timeout=settings.llm_timeout_s)

    def complete_json(self, *, system: str, user: str, schema: dict, schema_name: str, max_tokens: int = 2000) -> LLMResult:
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": schema_name, "schema": schema, "strict": False}},
        }
        headers = {"authorization": f"Bearer {self._key}", "content-type": "application/json"}
        t0 = time.perf_counter()
        resp = post_with_retries(self._client, f"{self._base}/chat/completions", headers=headers, payload=payload,
                                 retries=self._retries)
        body = resp.json()
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError("llm_bad_output", "Unexpected LLM response shape.") from e
        data = parse_json_text(content or "")
        usage = body.get("usage", {})
        return LLMResult(data, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)),
                         int((time.perf_counter() - t0) * 1000), body.get("model", self.model))


def get_provider(settings: Settings | None = None, client: httpx.Client | None = None) -> LLMProvider | None:
    """Return the configured provider, or None in demo mode (no key configured)."""
    s = settings or get_settings()
    if not s.llm_enabled:
        return None
    if s.llm_provider == "anthropic":
        return AnthropicProvider(s, client)
    if s.llm_provider == "openai":
        return OpenAIProvider(s, client)
    return None
