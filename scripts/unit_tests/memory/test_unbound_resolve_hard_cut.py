"""PRD 279 R10/D2 — unbound resolve-provider hard cut (no ambient Recallium writes)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from memory_preflight import resolve_provider
from memory_write_binding import CAUSE_UNBOUND, MemoryWriteBindingError


def _cfg(root: Path, memory: dict) -> None:
    d = root / ".cursor"
    d.mkdir(parents=True, exist_ok=True)
    (d / "workflow.config.json").write_text(json.dumps({"memory": memory}) + "\n", encoding="utf-8")


def test_unbound_read_aligns_in_repo_not_recallium(tmp_path: Path) -> None:
    _cfg(tmp_path, {})
    result = resolve_provider(tmp_path, for_write=False)
    assert result["source"] == "unbound"
    assert result["provider"] is None
    assert result["displayGuidance"] == "in-repo"
    assert result["writeAuthorized"] is False
    assert result["provider"] != "recallium"


def test_unbound_write_refuses_hard_cut(tmp_path: Path) -> None:
    _cfg(tmp_path, {})
    with pytest.raises(MemoryWriteBindingError) as exc:
        resolve_provider(tmp_path, for_write=True, operation="memory-sync", category="learning")
    assert exc.value.refuse.cause == CAUSE_UNBOUND


def test_bound_write_authorizes_configured_project(tmp_path: Path) -> None:
    _cfg(tmp_path, {"provider": "recallium", "project": "shipwright"})
    result = resolve_provider(tmp_path, for_write=True, category="learning")
    assert result["writeAuthorized"] is True
    assert result["provider"] == "recallium"
    assert result["project"] == "shipwright"
