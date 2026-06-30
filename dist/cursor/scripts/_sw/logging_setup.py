"""Structured logging to stderr with run-log append and redaction (R13, R14)."""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

_LOGGER: logging.Logger | None = None


def _redact_message(text: str) -> str:
    try:
        scripts_dir = Path(__file__).resolve().parent.parent
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        from secret_patterns import REDACTIONS  # noqa: WPS433

        out = text
        for pattern, replacement in REDACTIONS:
            out = pattern.sub(replacement, out)
        return out
    except Exception:
        return text


class _RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        original = record.getMessage()
        record.msg = _redact_message(original)
        record.args = ()
        return super().format(record)


def resolve_log_level() -> int:
    raw = os.environ.get("SW_LOG_LEVEL", "WARNING").strip().upper()
    return _LEVELS.get(raw, logging.WARNING)


def get_logger(name: str = "shipwright") -> logging.Logger:
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER
    logger = logging.getLogger(name)
    logger.setLevel(resolve_log_level())
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(_RedactingFormatter("%(levelname)s: %(message)s"))
        handler.setLevel(resolve_log_level())
        logger.addHandler(handler)
    _LOGGER = logger
    return logger


def log(level: int, message: str, *args: Any) -> None:
    get_logger().log(level, message, *args)


def debug(message: str, *args: Any) -> None:
    get_logger().debug(message, *args)


def info(message: str, *args: Any) -> None:
    get_logger().info(message, *args)


def warning(message: str, *args: Any) -> None:
    get_logger().warning(message, *args)


def error(message: str, *args: Any) -> None:
    get_logger().error(message, *args)


def resolve_run_log_path() -> Path | None:
    run_dir = os.environ.get("SW_RUN_DIR", "").strip()
    if run_dir:
        return Path(run_dir) / "run.log"
    slug = os.environ.get("SW_PHASE_SLUG", "").strip()
    if slug:
        return Path(".cursor") / "sw-deliver-runs" / slug / "run.log"
    return None


def append_run_log(event: dict[str, Any]) -> None:
    """Append a structured, redacted event line to the durable run log."""
    path = resolve_run_log_path()
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        **event,
    }
    try:
        from _sw import jsonio

        line = jsonio.dumps(payload)
    except Exception:
        import json

        line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    line = _redact_message(line)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.write("\n")
