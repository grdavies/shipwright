"""PRD 339 R34 — Linear adapter gated on PRD 061 facade/projection readiness."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from planning_linear_client import (
    PRD_061_FACADE_ACCEPTANCE_TEST,
    PRD_061_PROJECTION_ACCEPTANCE_TEST,
    LinearClientError,
    LinearIssuesClient,
    prd061_facade_projection_readiness,
)


def _copy_test(repo_root: Path, dest_root: Path, rel_test: str) -> None:
    src = repo_root / rel_test
    dst = dest_root / rel_test
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def test_linear_blocked_until_prd061_absent(tmp_path: Path) -> None:
    """R34 — absent prerequisites block linear activation."""
    out = prd061_facade_projection_readiness(tmp_path)
    assert out["verdict"] == "blocked"
    assert out["cause"] == "prd-061-facade-projection-not-merged-green"
    blocked_tests = {item["test"] for item in out.get("blocked") or []}
    assert PRD_061_FACADE_ACCEPTANCE_TEST in blocked_tests
    assert PRD_061_PROJECTION_ACCEPTANCE_TEST in blocked_tests


def test_linear_blocked_until_prd061_partial(tmp_path: Path, repo_root: Path) -> None:
    """R34 — partial prerequisites block until both facade and projection contracts are green."""
    _copy_test(repo_root, tmp_path, PRD_061_FACADE_ACCEPTANCE_TEST)
    out = prd061_facade_projection_readiness(tmp_path)
    assert out["verdict"] == "blocked"
    blocked = {item["test"]: item for item in out.get("blocked") or []}
    assert PRD_061_PROJECTION_ACCEPTANCE_TEST in blocked
    assert blocked[PRD_061_PROJECTION_ACCEPTANCE_TEST]["reason"] == "acceptance-test-missing"


def test_linear_blocked_until_prd061_green(repo_root: Path) -> None:
    """R34 — merged-green PRD 061 facade/projection contract evidence unblocks linear."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "scripts")
    proc = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/planning_linear_client.py"),
            str(repo_root),
            "prd061-readiness-gate",
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    out = json.loads(proc.stdout)
    assert out.get("verdict") == "ready", out
    checks = {item["test"]: item for item in out.get("checks") or []}
    assert checks[PRD_061_FACADE_ACCEPTANCE_TEST]["verdict"] == "ready"
    assert checks[PRD_061_PROJECTION_ACCEPTANCE_TEST]["verdict"] == "ready"


def test_linear_client_live_path_refuses_without_prd061(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R34 — live LinearIssuesClient refuses activation when PRD 061 gate is blocked."""
    # CI suites often set SW_ISSUES_FIXTURE=1; that skips the live gate — clear it.
    monkeypatch.delenv("SW_ISSUES_FIXTURE", raising=False)
    monkeypatch.delenv("SW_HOST_ISSUES_FIXTURE", raising=False)
    cfg = {
        "planning": {
            "store": {
                "projectKey": "fixture",
                "issues": {"teamKey": "SW"},
            }
        }
    }
    with pytest.raises(LinearClientError) as exc_info:
        LinearIssuesClient(tmp_path, cfg=cfg)
    assert exc_info.value.code == "prd061-readiness-blocked"


def test_linear_client_fixture_path_skips_prd061_gate(repo_root: Path) -> None:
    """Fixture harness remains available for hermetic tests without live PRD 061 re-probe."""
    cfg = {
        "planning": {
            "store": {
                "projectKey": "fixture",
                "issues": {"teamKey": "SW"},
            }
        }
    }
    client = LinearIssuesClient(repo_root, cfg=cfg, fixture_store=object())
    assert client._fixture is not None
