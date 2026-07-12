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
