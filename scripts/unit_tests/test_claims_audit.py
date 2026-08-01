"""Unit tests for claims_audit_lib (PRD 064 R3/R4)."""
from __future__ import annotations

from pathlib import Path

import claims_audit_lib as lib


TASKS_SNIPPET = """
### 6. Adversarial completion-claims audit (Workstream A)

- [x] 6.1 Add a claims-audit agent (R3)
  - **File:** `core/skills/verification-gate/SKILL.md`
  - **Expected:** claims-audit integration documented; fail-closed overlay wired.
- [ ] 6.2 Reuse at deliver collect (R4)
  - **File:** `core/skills/deliver/SKILL.md`
  - **Expected:** collect-time audit documented.
"""


def test_parse_phase_subtasks_extracts_expected():
    rows = lib.parse_phase_subtasks(TASKS_SNIPPET, "6")
    assert len(rows) == 2
    assert rows[0]["ref"] == "6.1"
    assert rows[0]["checked"] is True
    assert "verification-gate" in rows[0]["files"][0]
    assert "claims-audit" in rows[0]["expected"]


def test_completed_claims_only_checked():
    claims = lib.completed_claims(TASKS_SNIPPET, "6")
    assert [c["ref"] for c in claims] == ["6.1"]


def test_merge_claim_results_fails_without_agent_for_expected(tmp_path: Path):
    claims = lib.completed_claims(TASKS_SNIPPET, "6")
    mechanical = [{
        "ref": "6.1",
        "verdict": "pass",
        "dimension": "mechanical",
        "reason": "ok",
    }]
    result = lib.merge_claim_results(mechanical, [], claims=claims)
    assert result["verdict"] == "fail"


def test_apply_verification_overlay_fail_closed():
    verdict = {"verdict": "verified", "reason": "ok", "evidence": {}}
    out = lib.apply_verification_overlay(verdict, {"verdict": "fail", "claims": []})
    assert out["verdict"] == "inconclusive"
    assert out["inconclusiveClass"] == "missing-required"


WIRED_TASKS_SNIPPET = """
### 1. Credential backend wiring (R16)

- [x] 1.1 Add foo backend (R16)
  - **File:** `scripts/credentials/backends/foo.py`
  - **Expected:** adds a new backend/adapter registration function
  - **Wired:** `scripts/credentials/resolver.py`
"""


def test_reachability_findings_gap_when_callsite_missing_reference(tmp_path: Path):
    resolver = tmp_path / "scripts/credentials/resolver.py"
    backend = tmp_path / "scripts/credentials/backends/foo.py"
    resolver.parent.mkdir(parents=True)
    backend.parent.mkdir(parents=True)
    resolver.write_text("# resolver without backend import\n", encoding="utf-8")
    backend.write_text("def register():\n    pass\n", encoding="utf-8")
    claims = lib.completed_claims(WIRED_TASKS_SNIPPET, "1")
    touched = {
        "scripts/credentials/resolver.py",
        "scripts/credentials/backends/foo.py",
    }
    findings = lib.reachability_findings(tmp_path, claims, touched=touched)
    assert any(f["verdict"] == "fail" and f["dimension"] == "reachability" for f in findings)


def test_reachability_findings_passes_with_genuine_reference(tmp_path: Path):
    resolver = tmp_path / "scripts/credentials/resolver.py"
    backend = tmp_path / "scripts/credentials/backends/foo.py"
    resolver.parent.mkdir(parents=True)
    backend.parent.mkdir(parents=True)
    resolver.write_text(
        "from scripts.credentials.backends import foo\n",
        encoding="utf-8",
    )
    backend.write_text("def register():\n    pass\n", encoding="utf-8")
    claims = lib.completed_claims(WIRED_TASKS_SNIPPET, "1")
    touched = {
        "scripts/credentials/resolver.py",
        "scripts/credentials/backends/foo.py",
    }
    findings = lib.reachability_findings(tmp_path, claims, touched=touched)
    assert findings and all(f["verdict"] == "pass" for f in findings)


def test_build_agent_brief_includes_reachability_verdict(tmp_path: Path):
    resolver = tmp_path / "scripts/credentials/resolver.py"
    backend = tmp_path / "scripts/credentials/backends/foo.py"
    resolver.parent.mkdir(parents=True)
    backend.parent.mkdir(parents=True)
    resolver.write_text("# no reference\n", encoding="utf-8")
    backend.write_text("pass\n", encoding="utf-8")
    claims = lib.completed_claims(WIRED_TASKS_SNIPPET, "1")
    touched = {
        "scripts/credentials/resolver.py",
        "scripts/credentials/backends/foo.py",
    }
    brief = lib.build_agent_brief(claims, diff_paths=touched, root=tmp_path)
    assert brief.get("reachabilityVerdict") == "fail"
    assert brief.get("reachabilityFindings")
