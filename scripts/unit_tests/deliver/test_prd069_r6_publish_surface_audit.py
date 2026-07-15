"""PRD 069 R6 — publish-surface audit fail-closed and false-green prevention."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import publish_surface_audit as psa


def test_publish_surface_audit_green_shape(repo_root: Path) -> None:
    result = psa.run_publish_surface_audit(repo_root)
    assert result["action"] == "publish-surface-audit"
    assert "considered" in result
    assert "passed" in result
    assert "failed" in result
    assert "skipped" in result
    assert result["severitiesExpected"] == ["critical", "warning"]
    assert set(result["severitiesConsidered"]) <= {"critical", "warning"}


def test_publish_surface_audit_emits_json(repo_root: Path, tmp_path: Path) -> None:
    dest = tmp_path / ".cursor" / "sw-deliver-runs"
    dest.mkdir(parents=True)
    with patch.object(psa, "audit_path_for", return_value=dest / "publish-surface-audit.json"):
        result = psa.emit_publish_surface_audit(repo_root, write=True)
    assert result["verdict"] in {"ready", "not-ready"}
    written = dest / "publish-surface-audit.json"
    assert written.is_file()
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["action"] == "publish-surface-audit"
    assert isinstance(payload["considered"], list)


def test_publish_surface_audit_critical_leak_not_ready() -> None:
    tracked = [
        "README.md",
        "docs/learnings/sample-retro.md",
        "docs/guides/commands.md",
    ]
    result = psa.run_publish_surface_audit(Path("."), tracked_override=tracked)
    assert result["verdict"] == "not-ready"
    assert "denylist-leaked-paths" in result["failed"]
    assert result["resumeCommand"]


def test_publish_surface_audit_partial_discovery_not_ready() -> None:
    """Partial discovery cannot false-green when critical checks are unconsidered."""
    with patch.object(psa, "CHECKS", (psa._check_denylist_leaked,)):
        result = psa.run_publish_surface_audit(Path("."), tracked_override=["README.md"])
    assert result["failed"] == []
    assert result["verdict"] == "not-ready"
    assert result["allSeveritiesConsidered"] is False
    assert result["severitiesConsidered"] == ["critical"]


def test_publish_surface_audit_docs_prds_leak_not_ready() -> None:
    tracked = ["README.md", "docs/prds/069-test/tasks-069-test.md"]
    result = psa.run_publish_surface_audit(Path("."), tracked_override=tracked)
    assert result["verdict"] == "not-ready"
    assert "docs-prds-absent" in result["failed"]
