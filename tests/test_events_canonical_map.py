"""PRD 349 R19: adapters derive event names from core/schemas/events.json only."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EVENTS_PATH = REPO_ROOT / "core" / "schemas" / "events.json"
CLAUDE_GENERATORS = REPO_ROOT / "platforms" / "claude-code" / "generators"

sys.path.insert(0, str(CLAUDE_GENERATORS))
import event_registry  # noqa: E402


def test_events_json_is_authoritative() -> None:
    doc = json.loads(EVENTS_PATH.read_text(encoding="utf-8"))
    assert isinstance(doc.get("events"), list) and doc["events"]
    for entry in doc["events"]:
        assert "canonical" in entry
        assert "hosts" in entry
        assert "emitter_params" in entry
        assert "unsupported_on" in entry


def test_claude_registry_reads_events_json() -> None:
    names = event_registry.registered_host_events("claude-code")
    assert names
    assert "ContextSwitch" not in names
    unsupported = event_registry.unsupported_events("claude-code")
    assert any(
        row.get("canonical") == "ContextSwitch" and row.get("unsupported_flag") is True
        for row in unsupported
    )


def test_no_event_name_literals_in_claude_generators() -> None:
    doc = json.loads(EVENTS_PATH.read_text(encoding="utf-8"))
    banned: set[str] = set()
    for entry in doc["events"]:
        banned.add(str(entry["canonical"]))
        for host_name in (entry.get("hosts") or {}).values():
            if isinstance(host_name, str) and host_name.strip():
                banned.add(host_name.strip())

    for path in CLAUDE_GENERATORS.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            value = node.value
            if value not in banned:
                continue
            if path.name == "event_registry.py" and value == "ContextSwitch":
                continue
            raise AssertionError(f"event name literal {value!r} embedded in {path}")
