"""PRD 326 R15 — doctrine assessment evaluator verdicts and waiver rules."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import architecture_assessment as aa

PASSING_ASSESSMENT = """\
doctrineVersion: 1
assessments:
  - id: AD-1
    verdict: pass
  - id: AD-2
    verdict: pass
  - id: AD-3
    verdict: pass
  - id: AD-4
    verdict: pass
  - id: AD-5
    verdict: pass
  - id: AD-6
    verdict: manual
"""


@pytest.fixture(autouse=True)
def _cleanup_assessment_artifacts(repo_root: Path) -> None:
    (repo_root / ".cursor/workflow.config.json").unlink(missing_ok=True)
    (repo_root / ".cursor/architecture-assessment.yaml").unlink(missing_ok=True)
    yield
    (repo_root / ".cursor/workflow.config.json").unlink(missing_ok=True)
    (repo_root / ".cursor/architecture-assessment.yaml").unlink(missing_ok=True)


def _write_config(tmp_path: Path, mode: str) -> None:
    cfg_dir = tmp_path / ".cursor"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "workflow.config.json").write_text(
        json.dumps(
            {
                "architecture": {
                    "assessment": {
                        "mode": mode,
                        "path": ".cursor/architecture-assessment.yaml",
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def _write_assessment(tmp_path: Path, yaml_text: str) -> None:
    path = tmp_path / ".cursor/architecture-assessment.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml_text, encoding="utf-8")


def test_mode_off_skips(repo_root: Path) -> None:
    result = aa.evaluate(repo_root)
    assert result["verdict"] == "skip"
    assert aa.exit_code_for_result(result) == 0


def test_mixed_rollout(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aa, "evaluate_signal", lambda _root, _statement: True)
    _write_config(repo_root, "blocking")
    _write_assessment(
        repo_root,
        """\
doctrineVersion: 1
assessments:
  - id: AD-1
    verdict: pass
  - id: AD-2
    verdict: pass
  - id: AD-3
    verdict: pass
  - id: AD-4
    verdict: pass
  - id: AD-5
    verdict: pass
  - id: AD-6
    verdict: manual
""",
    )
    try:
        result = aa.evaluate_assessments(repo_root)
        assert result["verdict"] == "pass"
        assert result["manual"] == ["AD-6"]
    finally:
        (repo_root / ".cursor/workflow.config.json").unlink(missing_ok=True)
        (repo_root / ".cursor/architecture-assessment.yaml").unlink(missing_ok=True)


def test_advisory_single_fail_exits_zero(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_config(repo_root, "advisory")
    _write_assessment(
        repo_root,
        """\
doctrineVersion: 1
assessments:
  - id: AD-1
    verdict: fail
""",
    )
    try:
        result = aa.evaluate(repo_root)
        assert result["mode"] == "advisory"
        assert result["verdict"] == "fail"
        assert "AD-1" in result["failed"]
        assert aa.exit_code_for_result(result) == 0
    finally:
        (repo_root / ".cursor/workflow.config.json").unlink(missing_ok=True)
        (repo_root / ".cursor/architecture-assessment.yaml").unlink(missing_ok=True)


def test_blocking_fail_exits_twenty(repo_root: Path) -> None:
    _write_config(repo_root, "blocking")
    _write_assessment(
        repo_root,
        """\
doctrineVersion: 1
assessments:
  - id: AD-1
    verdict: fail
""",
    )
    try:
        result = aa.evaluate(repo_root)
        assert result["mode"] == "blocking"
        assert result["verdict"] == "fail"
        assert aa.exit_code_for_result(result) == 20
    finally:
        (repo_root / ".cursor/workflow.config.json").unlink(missing_ok=True)
        (repo_root / ".cursor/architecture-assessment.yaml").unlink(missing_ok=True)


def test_expired_waiver_counts_as_fail(repo_root: Path) -> None:
    assessment = aa.load_assessment_yaml(
        repo_root,
        path=repo_root / ".cursor/architecture-assessment.yaml",
    )
    # Build isolated evaluation with expired waiver
    document = {
        "doctrineVersion": 1,
        "assessments": [
            {
                "id": "AD-1",
                "verdict": "waived",
                "waiver": {
                    "actor": "human@example.com",
                    "reason": "legacy",
                    "expires": "2000-01-01",
                },
            }
        ],
    }
    doctrine = aa.parse_doctrine(repo_root)
    result = aa.evaluate_assessments(
        repo_root,
        doctrine=doctrine,
        assessment={"verdict": "pass", "document": document},
        today=date(2026, 1, 1),
    )
    assert "AD-1" in result["failed"]


def test_waiver_expiring_today_is_not_expired(repo_root: Path) -> None:
    today = date(2026, 8, 23)
    document = {
        "doctrineVersion": 1,
        "assessments": [
            {
                "id": "AD-1",
                "verdict": "waived",
                "waiver": {
                    "actor": "human@example.com",
                    "reason": "today",
                    "expires": "2026-08-23",
                },
            }
        ],
    }
    doctrine = aa.parse_doctrine(repo_root)
    result = aa.evaluate_assessments(
        repo_root,
        doctrine=doctrine,
        assessment={"verdict": "pass", "document": document},
        today=today,
    )
    assert "AD-1" in result["waived"]


def test_record_waiver_refused_on_agent_dispatch(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SW_DISPATCH_PARENT_COMMAND", "sw-doc")
    proc = subprocess.run(
        [
            "python3",
            str(repo_root / "scripts/architecture_assessment.py"),
            "--root",
            str(repo_root),
            "record-waiver",
            "AD-1",
            "--actor",
            "human@example.com",
            "--reason",
            "test",
            "--expires",
            "2099-01-01",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(repo_root / "scripts")},
    )
    assert proc.returncode == 20
    payload = json.loads(proc.stdout)
    assert payload["cause"] == "agent-dispatch-override-denied"


def test_verdict_json_shape(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aa, "evaluate_signal", lambda _root, _statement: True)
    _write_config(repo_root, "blocking")
    _write_assessment(repo_root, PASSING_ASSESSMENT)
    try:
        result = aa.evaluate(repo_root)
        for key in ("verdict", "failed", "waived", "manual"):
            assert key in result
    finally:
        (repo_root / ".cursor/workflow.config.json").unlink(missing_ok=True)
        (repo_root / ".cursor/architecture-assessment.yaml").unlink(missing_ok=True)
