"""PRD 326 phase 1 / R1 — resilience verify-scope gate + runner readiness.

Asserts ``check_gate_lib.validate_resilience_verify_scope`` (PRD 323 R22) still resolves,
``scripts/test/_runner.py`` dispatches the resilience scope, and suite-registry carries a
resilience slice (or a typed fail naming the missing wiring).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import check_gate_lib as cgl  # noqa: E402


def _suite_registry_has_resilience_slice(root: Path) -> tuple[bool, str]:
    path = root / "core/sw-reference/suite-registry.json"
    if not path.is_file():
        return False, "suite-registry-missing"
    data = json.loads(path.read_text(encoding="utf-8"))
    suites = data.get("suites") or []
    for suite in suites:
        if not isinstance(suite, dict):
            continue
        blob = json.dumps(suite)
        sid = str(suite.get("id") or "")
        if (
            sid == "resilience-fixtures"
            or "unit_tests/resilience" in blob
            or "resilience" in sid
        ):
            return True, sid or "matched"
    # Domain pathTriggers covering resilience package also count as the slice.
    domains = data.get("domains") or {}
    for name, domain in domains.items() if isinstance(domains, dict) else []:
        if not isinstance(domain, dict):
            continue
        triggers = domain.get("pathTriggers") or []
        if any("unit_tests/resilience" in str(t) for t in triggers):
            return True, f"domain:{name}"
    return False, "suite-registry-resilience-slice-missing"


def _runner_dispatches_resilience(root: Path) -> tuple[bool, str]:
    runner = root / "scripts/test/_runner.py"
    if not runner.is_file():
        return False, "runner-missing"
    text = runner.read_text(encoding="utf-8", errors="replace")
    if "resilience" not in text:
        return False, "runner-missing-resilience-scope"
    if "run_resilience_verify" not in text:
        return False, "runner-missing-resilience-handler"
    return True, "ok"


def test_prd323_gate_readiness(repo_root: Path) -> None:
    """Resilience verify-scope readiness must resolve fail-closed (no silent skip)."""
    cfg = cgl.load_workflow_config(repo_root)
    err = cgl.validate_resilience_verify_scope(repo_root, cfg)
    assert err is None, f"typed halt: resilienceVerify:{err}"

    ok_runner, runner_reason = _runner_dispatches_resilience(repo_root)
    assert ok_runner, f"typed halt: {runner_reason}"

    ok_suite, suite_reason = _suite_registry_has_resilience_slice(repo_root)
    assert ok_suite, f"typed halt: {suite_reason}"
