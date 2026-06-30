"""Deterministic JSON emission for stdout contracts (R38).

Normalization rules:
- ``sort_keys=True`` for stable key order.
- Fixed separators ``(',', ':')`` (no extra whitespace).
- Float ``-0.0`` normalized to ``0.0``.
- Path strings normalize backslashes to forward slashes.
- Dict keys are emitted in sorted order; list order is preserved.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path, PureWindowsPath
from typing import Any

_WINDOWS_PATH_RE = re.compile(r"^[A-Za-z]:\\")


def _normalize_value(value: Any) -> Any:
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return value
        if value == 0.0 and math.copysign(1.0, value) < 0:
            return 0.0
        return value
    if isinstance(value, str):
        if "\\" in value and (_WINDOWS_PATH_RE.match(value) or "/" not in value):
            return PureWindowsPath(value).as_posix()
        return value.replace("\\", "/") if "\\" in value and "/" in value else value
    if isinstance(value, dict):
        return {str(k): _normalize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_value(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    return value


def dumps(obj: Any, *, indent: int | None = None) -> str:
    """Serialize *obj* with deterministic normalization rules."""
    normalized = _normalize_value(obj)
    if indent is None:
        return json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    return json.dumps(
        normalized,
        sort_keys=True,
        indent=indent,
        ensure_ascii=False,
    )


def emit(obj: Any, *, indent: int | None = None) -> None:
    """Write normalized JSON to stdout with trailing newline."""
    import sys

    sys.stdout.write(dumps(obj, indent=indent))
    sys.stdout.write("\n")
