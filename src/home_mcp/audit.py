"""Structured audit logging and secret redaction.

Every tool invocation and every authentication decision is written here as a
single JSON line, so there is an accountable record of everything an authorized
session did through the server.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any

logger = logging.getLogger("home_mcp.audit")

# Substrings (underscores ignored) that mark a value as secret and worth hiding
# from the audit log. Kept deliberately narrow to avoid redacting innocuous
# fields such as "author" or "headRefName".
_SENSITIVE = (
    "token",
    "secret",
    "password",
    "passwd",
    "authorization",
    "apikey",
    "credential",
    "privatekey",
)

_MAX_STR = 500
_MAX_LIST = 50
_MAX_DEPTH = 6


def _normalize(key: str) -> str:
    return key.lower().replace("_", "").replace("-", "")


def _is_sensitive(key: str) -> bool:
    norm = _normalize(key)
    return any(token in norm for token in _SENSITIVE)


def redact(value: Any, _depth: int = 0) -> Any:
    """Return a copy of ``value`` with secret-looking fields and huge blobs hidden."""
    if _depth > _MAX_DEPTH:
        return "…"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, val in value.items():
            if _is_sensitive(str(key)):
                out[str(key)] = "***redacted***"
            else:
                out[str(key)] = redact(val, _depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        trimmed = [redact(item, _depth + 1) for item in list(value)[:_MAX_LIST]]
        if len(value) > _MAX_LIST:
            trimmed.append(f"…(+{len(value) - _MAX_LIST} more)")
        return trimmed
    if isinstance(value, str) and len(value) > _MAX_STR:
        return value[:_MAX_STR] + "…(truncated)"
    return value


def configure_audit(audit_log_file: str | None = None, level: str = "info") -> None:
    """Wire up the audit logger to stderr and, optionally, a rotating file."""
    logger.setLevel(logging.INFO)
    logger.propagate = False
    # Reset handlers so repeated calls (e.g. in tests) don't duplicate output.
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    formatter = logging.Formatter("%(message)s")

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    logger.addHandler(stderr_handler)

    if audit_log_file:
        file_handler = RotatingFileHandler(
            audit_log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)


def audit_log(event: str, **fields: Any) -> None:
    """Emit one structured, secret-redacted audit record."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
    }
    record.update(redact(fields))
    try:
        logger.info(json.dumps(record, default=str, ensure_ascii=False))
    except Exception:  # never let logging break a request
        logger.info(json.dumps({"ts": record["ts"], "event": event, "log_error": True}))
