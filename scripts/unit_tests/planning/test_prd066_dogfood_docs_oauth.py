"""PRD 066 phase 11 — dogfood acceptance, docs currency, OAuth docs gate (R25, R30, R23)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_linear_client as plc


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_r25_stage1_dogfood_gate_passes() -> None:
    """R25 — stage-1 dogfood checklist documented and gate green."""
    root = _repo_root()
    result = plc.stage1_dogfood_checklist_gate(root)
    assert result["verdict"] == "ok"
    assert result["gate"] == "stage1-dogfood-gate"
    assert result["checklist"]["mvpAuthMode"] == "api-key"


def test_r23_oauth_docs_gate_passes() -> None:
    """R23 — OAuth secondary mode fully documented; MVP dogfood remains api-key."""
    root = _repo_root()
    result = plc.oauth_docs_gate(root)
    assert result["verdict"] == "ok"
    assert result["gate"] == "oauth-docs-gate"
    assert result["mvpDogfoodAuth"] == "api-key"
    storage = result["storage"]
    assert storage["operatorLocalOnly"] is True
    assert storage["mustNotCommitToPlanningRepo"] is True


def test_r30_docs_currency_gate_passes() -> None:
    """R30 — documentation currency inventory complete before adapter-complete."""
    root = _repo_root()
    result = plc.docs_currency_gate(root)
    assert result["verdict"] == "ok"
    assert result["gate"] == "docs-currency-gate"
    assert "core/providers/issues/linear.md" in result["inventory"]
    assert "docs/guides/workflows.md" in result["inventory"]


def test_r25_linear_md_volume_and_coexistence_sections() -> None:
    """R25 — linear.md enumerates volume floors, R1 views, naming, coexistence."""
    doc = plc.linear_provider_doc_text(_repo_root())
    assert "≥3 PRD Projects" in doc
    assert "≥20 task Issues" in doc
    assert "R1(1)" in doc or "R1 question" in doc
    assert "Naming and archival" in doc
    assert "Coexistence" in doc


def test_r23_linear_md_oauth_scopes_and_refresh() -> None:
    """R23 — linear.md documents scopes, operator-local storage, refresh expectations."""
    doc = plc.linear_provider_doc_text(_repo_root())
    assert "issues:create" in doc
    assert "comments:create" in doc
    assert "refresh" in doc.lower()
    assert "stage-4" in doc.lower() or "Stage-4" in doc


def test_cli_stage1_and_oauth_gates_exit_zero() -> None:
    """CLI surfaces for stage-1 and oauth docs gates return ok JSON."""
    root = _repo_root()
    for cmd in ("stage1-dogfood-gate", "oauth-docs-gate", "docs-currency-gate"):
        proc = subprocess.run(
            [sys.executable, str(scripts / "planning_linear_client.py"), str(root), cmd],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["verdict"] == "ok", payload


def test_oauth_docs_gate_fails_when_marker_missing(tmp_path: Path) -> None:
    """Gate fails closed when required OAuth doc markers are absent."""
    doc_path = tmp_path / "core/providers/issues/linear.md"
    doc_path.parent.mkdir(parents=True)
    doc_path.write_text("# stub\n", encoding="utf-8")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(plc, "resolve_linear_provider_doc", lambda _root: doc_path)
    try:
        result = plc.oauth_docs_gate(tmp_path)
    finally:
        monkeypatch.undo()
    assert result["verdict"] == "fail"
    assert result["error"] == "missing-doc-markers"
