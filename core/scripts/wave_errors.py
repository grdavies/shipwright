#!/usr/bin/env python3
"""Shared JSON subprocess error forwarding for deliver wave modules (PRD 050 A6)."""
from __future__ import annotations

from typing import Any, Callable


def fail_from_payload(
    fail_fn: Callable[..., None],
    data: dict[str, Any],
    default: str,
    exit_code: int,
    **extra: Any,
) -> None:
    """Forward subprocess JSON without duplicate ``error`` kwarg TypeError (R55)."""
    reserved = {"error", *extra.keys()}
    payload = {k: v for k, v in data.items() if k not in reserved}
    fail_fn(data.get("error") or default, exit_code=exit_code, **extra, **payload)


def emit_fail_payload(
    emit_fn: Callable[[dict[str, Any], int], None],
    default: str,
    payload: dict[str, Any],
    *,
    exit_code: int = 2,
    **extra: Any,
) -> None:
    """Emit fail JSON directly (modules without a local ``fail`` helper)."""
    reserved = {"error", *extra.keys()}
    spread = {k: v for k, v in payload.items() if k not in reserved}
    msg = payload.get("error") or default
    emit_fn({"verdict": "fail", "error": str(msg), **extra, **spread}, exit_code)
