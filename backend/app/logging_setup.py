"""Structured JSON logging with request IDs. Never logs secrets."""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_SECRET_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9_\-]{8,})"),
    re.compile(r"(sk-ant-[A-Za-z0-9_\-]{8,})"),
    re.compile(r"(?i)(password|api[_-]?key|secret|authorization)(\"?\s*[:=]\s*\"?)([^\s\",]+)"),
    re.compile(r"(postgres(?:ql)?(?:\+psycopg)?://[^:\s]+:)([^@\s]+)(@)"),
]


def redact(msg: str) -> str:
    msg = _SECRET_PATTERNS[0].sub("sk-***", msg)
    msg = _SECRET_PATTERNS[1].sub("sk-ant-***", msg)
    msg = _SECRET_PATTERNS[2].sub(lambda m: f"{m.group(1)}{m.group(2)}***", msg)
    msg = _SECRET_PATTERNS[3].sub(lambda m: f"{m.group(1)}***{m.group(3)}", msg)
    return msg


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
            "request_id": request_id_var.get(),
        }
        for k in ("path", "method", "status", "duration_ms", "user_id"):
            if hasattr(record, k):
                payload[k] = getattr(record, k)
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))[-2000:]
        return json.dumps(payload)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        return
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root.handlers = [h]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
