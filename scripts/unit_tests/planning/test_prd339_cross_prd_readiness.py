"""PRD 339 R37/R39 cross-PRD readiness milestone (PRD 337 consumer evidence)."""

from __future__ import annotations

import json
from pathlib import Path

from prd339_cross_prd_gate import (
    PRD_339_R37_ACCEPTANCE_TEST,
    PRD_339_R39_ACCEPTANCE_TEST,
    prd339_absorb_acceptance_milestone,
)


def test_cross_prd_milestone_blocked_until_acceptance_tests_exist(tmp_path: Path) -> None:
    """R37/R39 — milestone blocks until list-form absorbs and index self-heal are green."""
    out = prd339_absorb_acceptance_milestone(tmp_path)
    assert out["verdict"] == "blocked"
    assert out["cause"] == "prd-339-r37-r39-not-merged-green"
    blocked_tests = {item["test"] for item in out.get("blocked") or []}
    assert PRD_339_R37_ACCEPTANCE_TEST in blocked_tests
    assert PRD_339_R39_ACCEPTANCE_TEST in blocked_tests


def test_cross_prd_milestone_ready_without_prd337_closeout(repo_root: Path) -> None:
    """R37/R39 — merged-green milestone evidence without implementing PRD 337 closeout."""
    out = prd339_absorb_acceptance_milestone(repo_root)
    if out.get("verdict") != "ready":
        blocked = out.get("blocked") or []
        detail = json.dumps(blocked, ensure_ascii=False, indent=2)
        raise AssertionError(
            f"cross-prd readiness not green: {out.get('cause')} blocked={detail}"
        )
    assert out.get("requirements") == ["R37", "R39"]
    checks = {item["test"]: item for item in out.get("checks") or []}
    assert checks[PRD_339_R37_ACCEPTANCE_TEST]["verdict"] == "ready"
    assert checks[PRD_339_R39_ACCEPTANCE_TEST]["verdict"] == "ready"
    assert "close-delivery-units" not in str(out.get("resumeCommand") or "")
