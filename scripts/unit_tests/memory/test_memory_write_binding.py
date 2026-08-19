"""PRD 279 R11/R12 — write-binding regression suite (unbound/marker/bound/__global__)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from memory_preflight import dispatch_mutating_store, memory_sync_store_path
from memory_rules_promote import (
    AUDIT_COMMAND,
    content_hash,
    memory_sync_store,
    ordinary_store,
)
from memory_write_binding import (
    CAUSE_GLOBAL_REFUSED,
    CAUSE_MARKER_REMOTE_NEEDS_PROJECT,
    CAUSE_PROJECT_MISSING,
    CAUSE_UNBOUND,
    MemoryWriteBindingError,
    assert_memory_write_binding,
    emit_write_refuse_audit,
)


def _write_config(root: Path, memory: dict) -> None:
    cfg_dir = root / ".cursor"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "workflow.config.json").write_text(
        json.dumps({"memory": memory}, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_marker(root: Path, provider: str) -> None:
    path = root / ".cursor" / "sw-memory.provider"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(provider + "\n", encoding="utf-8")


def _audit_lines(root: Path) -> list[dict]:
    path = root / ".cursor" / "sw-memory-write-audit.jsonl"
    if not path.is_file():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


def test_unbound_sync_store_refuses_writer_not_invoked_and_audits(tmp_path: Path) -> None:
    _write_config(tmp_path, {})
    invoked: list[str] = []

    def writer(binding) -> dict:
        invoked.append(binding.provider)
        return {"verdict": "ok"}

    with pytest.raises(MemoryWriteBindingError) as exc:
        memory_sync_store_path(tmp_path, category="learning", writer=writer)
    assert exc.value.refuse.cause == CAUSE_UNBOUND
    assert invoked == []
    events = _audit_lines(tmp_path)
    assert events, "expected refuse audit"
    assert events[-1]["event"] == "memory-write-refused"
    assert events[-1]["cause"] == CAUSE_UNBOUND
    assert events[-1]["operation"] == "memory-sync"


def test_unbound_dispatch_mutating_store_refuses(tmp_path: Path) -> None:
    _write_config(tmp_path, {})
    invoked = []

    with pytest.raises(MemoryWriteBindingError) as exc:
        dispatch_mutating_store(
            tmp_path,
            operation="store",
            category="learning",
            writer=lambda b: invoked.append(b.provider) or {"verdict": "ok"},
        )
    assert exc.value.refuse.cause == CAUSE_UNBOUND
    assert invoked == []


def test_marker_in_repo_basename_ok(tmp_path: Path) -> None:
    # Named directory so basename project is stable.
    root = tmp_path / "demo-repo"
    root.mkdir()
    _write_config(root, {})
    _write_marker(root, "in-repo")
    binding = assert_memory_write_binding(root, "memory-sync", "learning")
    assert binding.provider == "in-repo"
    assert binding.project == "demo-repo"
    assert binding.source == "marker-in-repo"
    result = memory_sync_store_path(root, category="learning")
    assert result["verdict"] == "ok"
    assert result["provider"] == "in-repo"
    assert result["project"] == "demo-repo"


def test_remote_marker_without_project_refused(tmp_path: Path) -> None:
    _write_config(tmp_path, {})
    _write_marker(tmp_path, "recallium")
    with pytest.raises(MemoryWriteBindingError) as exc:
        assert_memory_write_binding(tmp_path, "memory-sync", "learning")
    assert exc.value.refuse.cause == CAUSE_MARKER_REMOTE_NEEDS_PROJECT
    assert _audit_lines(tmp_path)[-1]["cause"] == CAUSE_MARKER_REMOTE_NEEDS_PROJECT


def test_bound_config_stays_on_configured_project(tmp_path: Path) -> None:
    _write_config(tmp_path, {"provider": "recallium", "project": "shipwright"})
    binding = assert_memory_write_binding(tmp_path, "memory-sync", "decision")
    assert binding.provider == "recallium"
    assert binding.project == "shipwright"
    assert binding.source == "config"
    result = memory_sync_store_path(tmp_path, category="decision")
    assert result["project"] == "shipwright"
    assert result["provider"] == "recallium"


def test_provider_without_project_refused(tmp_path: Path) -> None:
    _write_config(tmp_path, {"provider": "recallium", "project": ""})
    with pytest.raises(MemoryWriteBindingError) as exc:
        assert_memory_write_binding(tmp_path, "store", "learning")
    assert exc.value.refuse.cause == CAUSE_PROJECT_MISSING


def test_global_refused_when_unbound(tmp_path: Path) -> None:
    _write_config(tmp_path, {})
    with pytest.raises(MemoryWriteBindingError) as exc:
        assert_memory_write_binding(
            tmp_path,
            "memory-sync",
            "learning",
            project_override="__global__",
        )
    assert exc.value.refuse.cause == CAUSE_GLOBAL_REFUSED


def test_global_allowed_only_with_explicit_config_binding(tmp_path: Path) -> None:
    _write_config(tmp_path, {"provider": "recallium", "project": "__global__"})
    binding = assert_memory_write_binding(tmp_path, "memory-sync", "learning")
    assert binding.project == "__global__"
    assert binding.source == "config"


def test_global_override_refused_on_marker_binding(tmp_path: Path) -> None:
    root = tmp_path / "marked"
    root.mkdir()
    _write_config(root, {})
    _write_marker(root, "in-repo")
    with pytest.raises(MemoryWriteBindingError) as exc:
        assert_memory_write_binding(
            root,
            "memory-sync",
            "learning",
            project_override="__global__",
        )
    assert exc.value.refuse.cause == CAUSE_GLOBAL_REFUSED


def test_prd_277_rule_promote_load_paths_still_green(tmp_path: Path) -> None:
    """Ordinary/non-root store + approved rule path remain usable (PRD 277)."""
    body = "Never auto-promote rule-class memories.\n"
    approval = {
        "command": AUDIT_COMMAND,
        "ruleId": "no-auto-promote",
        "contentHash": content_hash(body),
        "approvedBy": "operator",
        "provenance": "sw-memory-audit",
    }
    # Without root, promote contract still allows non-binding path (legacy unit API).
    ok = ordinary_store(category="learning", rule_id="", body="a lesson")
    assert ok["verdict"] == "ok"
    ok_sync = memory_sync_store(category="learning", rule_id="", body="a lesson")
    assert ok_sync["verdict"] == "ok"
    approved = ordinary_store(
        category="rule",
        rule_id="no-auto-promote",
        body=body,
        approval=approval,
    )
    assert approved["verdict"] == "ok"


def test_emit_audit_scrubs_secretish_reason(tmp_path: Path) -> None:
    event = emit_write_refuse_audit(
        tmp_path,
        operation="memory-sync",
        reason="token=abc123secret-value",
        cause=CAUSE_UNBOUND,
        category="learning",
    )
    # Keyword scrub replaces credential-ish keys (token/secret/…); values may remain.
    assert "token" not in event["reason"].lower()
    assert "[redacted]" in event["reason"]
