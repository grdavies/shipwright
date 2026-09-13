"""PRD 349 R15–R18 capability schema + unknown_host resolver tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from core.adapters.host_resolver import (  # noqa: E402
    UnknownHostError,
    dispatch_host_adapter,
    resolve_host,
)

SCHEMA_PATH = REPO_ROOT / "core" / "schemas" / "capabilities" / "capability.schema.json"
CURSOR_PATH = REPO_ROOT / "core" / "schemas" / "capabilities" / "cursor.json"
CLAUDE_PATH = REPO_ROOT / "core" / "schemas" / "capabilities" / "claude-code.json"

REQUIRED_OPS = [
    "load_context",
    "invoke_workflow",
    "inspect_tool_call",
    "block_action",
    "dispatch_reviewer",
    "capture_progress",
    "restore_state",
    "emit_hook",
    "resolve_instruction",
]
OP_FIELDS = (
    'implementation_mode', 'evidence_required', 'known_gaps', 'failure_behavior',
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_descriptor(data: dict, schema: dict) -> list[str]:
    errors: list[str] = []
    for key in schema.get("required", []):
        if key not in data:
            errors.append(f"missing:{key}")
    surface = data.get("surface")
    if surface is not None and surface not in schema["properties"]["surface"]["enum"]:
        errors.append("surface:invalid")
    if data.get("trust_level") == "tested" and "tested_at" not in data:
        errors.append("tested_at:required")
    caps = data.get("capabilities")
    if not isinstance(caps, dict):
        errors.append("capabilities:missing")
        return errors
    for op in REQUIRED_OPS:
        if op not in caps:
            errors.append(f"capabilities.missing:{op}")
            continue
        entry = caps[op]
        if not isinstance(entry, dict):
            errors.append(f"capabilities.{op}:not-object")
            continue
        for field in OP_FIELDS:
            if field not in entry:
                errors.append(f"capabilities.{op}.missing:{field}")
        mode = entry.get('implementation_mode')
        if mode is not None and mode not in {
            "native",
            "adapted",
            "explicit",
            "unsupported",
        }:
            errors.append(f"capabilities.{op}.implementation_mode:invalid")
    return errors


def test_shipped_descriptors_conform() -> None:
    schema = _load(SCHEMA_PATH)
    for path in (CURSOR_PATH, CLAUDE_PATH):
        assert _validate_descriptor(_load(path), schema) == []


def test_schema_rejects_missing_host_or_surface() -> None:
    schema = _load(SCHEMA_PATH)
    base = _load(CURSOR_PATH)
    for key in ("host", "surface"):
        bad = dict(base)
        bad.pop(key, None)
        assert f"missing:{key}" in _validate_descriptor(bad, schema)


def test_schema_rejects_missing_implementation_mode() -> None:
    schema = _load(SCHEMA_PATH)
    bad = _load(CURSOR_PATH)
    bad["capabilities"]["load_context"] = {
        "evidence_required": "x",
        "known_gaps": [],
        "failure_behavior": "x",
    }
    errors = _validate_descriptor(bad, schema)
    assert "capabilities.load_context.missing:implementation_mode" in errors


def test_tested_trust_requires_tested_at() -> None:
    schema = _load(SCHEMA_PATH)
    bad = _load(CURSOR_PATH)
    bad["trust_level"] = "tested"
    bad.pop("tested_at", None)
    assert "tested_at:required" in _validate_descriptor(bad, schema)
    good = dict(bad)
    good["tested_at"] = "2026-09-12T00:00:00Z"
    assert "tested_at:required" not in _validate_descriptor(good, schema)


def test_unknown_host_emits_diagnostic_and_halts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(UnknownHostError) as exc:
        resolve_host("made-up-host")
    diag = exc.value.diagnostic.as_dict()
    assert diag["error"] == "unknown_host"
    assert diag["host_id"] == "made-up-host"
    assert "cursor" in diag["available_adapter_ids"]
    assert "unknown_host" in capsys.readouterr().err


def test_resolve_known_hosts() -> None:
    assert resolve_host("cursor").adapter_id == "cursor"
    assert resolve_host("claude-code").adapter_id == "claude-code"


def test_dispatch_exhaustive_match_raises() -> None:
    assert dispatch_host_adapter("cursor") == "cursor"
    with pytest.raises(NotImplementedError) as exc:
        dispatch_host_adapter("not-a-real-host")
    assert str(exc.value) == "not-a-real-host"
