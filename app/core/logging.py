"""Structured JSON logging with a per-request ID.

Privacy rule: question/answer text is never passed to the logger in the
default configuration. Log lengths, statuses and IDs instead.
"""

from __future__ import annotations

import logging
import re
import sys
from contextvars import ContextVar

import structlog

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_SECRET_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),  # Google API keys
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)(api[_-]?key|key|authorization|token|password)=([^\s&]+)"),
]


def _redact(value: str) -> str:
    for pat in _SECRET_PATTERNS:
        value = pat.sub(lambda m: (m.group(1) + "=[REDACTED]") if m.lastindex else "[REDACTED]", value)
    return value


def _add_request_id(_logger, _method, event_dict):
    rid = request_id_var.get()
    if rid and "request_id" not in event_dict:
        event_dict["request_id"] = rid
    return event_dict


def _redact_secrets(_logger, _method, event_dict):
    for key, val in list(event_dict.items()):
        if isinstance(val, str):
            event_dict[key] = _redact(val)
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    # Third-party HTTP loggers print request URLs at INFO and bypass the redaction
    # processor above; keep them quiet so no URL with credentials can be logged.
    for noisy in ("httpx", "httpx2", "httpcore", "google_genai", "google_genai._api_client"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_request_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            _redact_secrets,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None):
    return structlog.get_logger(name)
