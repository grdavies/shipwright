"""PRD 082 R32 — fail-closed redaction and verification post-condition fixtures."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import memory_redact  # noqa: E402
import planning_cross_project_recall as recall  # noqa: E402

_SECRET = "ghp_" + "A" * 36


def _run_memory_redact(destination: str, text: str, *, prelude: str = "") -> subprocess.CompletedProcess[str]:
    code = f"""
import sys
from pathlib import Path
sys.path.insert(0, {str(SCRIPTS)!r})
{prelude}
import memory_redact
raise SystemExit(memory_redact.main(["--destination", {destination!r}]))
"""
    return subprocess.run(
        [sys.executable, "-c", code],
        input=text,
        capture_output=True,
        text=True,
    )


def test_redaction_subprocess_failure_emits_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_args, **_kwargs):
        raise OSError("redact subprocess failed")

    monkeypatch.setattr(recall.subprocess, "run", _boom)
    assert recall.redact_text(_SECRET) is None


def test_residual_match_exits_nonzero_naming_detector(monkeypatch: pytest.MonkeyPatch) -> None:
    noop = [(re.compile(r"ghp_[A-Za-z0-9]{36,}"), _SECRET)]
    monkeypatch.setattr(memory_redact, "REDACTIONS", noop)
    with pytest.raises(memory_redact.RedactionError) as exc:
        memory_redact.redact_with_postcondition(_SECRET, destination="external")
    assert exc.value.detector == "GITHUB_PAT"

    prelude = f"import memory_redact, re\nmemory_redact.REDACTIONS = [(re.compile(r'ghp_[A-Za-z0-9]{{36,}}'), {_SECRET!r})]\n"
    proc = _run_memory_redact("external", _SECRET, prelude=prelude)
    assert proc.returncode != 0
    assert proc.stdout == ""
    assert "GITHUB_PAT" in proc.stderr


def test_advisory_destination_warns_with_counters_without_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    noop = [(re.compile(r"ghp_[A-Za-z0-9]{36,}"), _SECRET)]
    monkeypatch.setattr(memory_redact, "REDACTIONS", noop)

    out, residuals = memory_redact.redact_with_postcondition(_SECRET, destination="committed")
    assert out == _SECRET
    assert residuals.get("GITHUB_PAT") == 1

    prelude = f"import memory_redact, re\nmemory_redact.REDACTIONS = [(re.compile(r'ghp_[A-Za-z0-9]{{36,}}'), {_SECRET!r})]\n"
    proc = _run_memory_redact("committed", _SECRET, prelude=prelude)
    assert proc.returncode == 0
    assert proc.stdout == _SECRET
    assert "warning: residual detector GITHUB_PAT: 1" in proc.stderr


def test_missing_pattern_set_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(memory_redact, "REDACTIONS", [])
    with pytest.raises(memory_redact.RedactionError, match="missing pattern set"):
        memory_redact.apply_substitutions("secret")


def test_cross_project_recall_skips_hit_when_redaction_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = SCRIPTS.parent
    monkeypatch.setattr(recall, "redact_text", lambda _text: None)
    result = recall.recall_cross_project(
        root,
        source_project_key="proj-a",
        caller_project_key="proj-b",
        query="",
        pointers=[
            {
                "projectKey": "proj-a",
                "unitId": "unit-1",
                "memoryId": "mem-1",
                "visibility": "public",
                "excerpt": _SECRET,
            }
        ],
        authorized_projects=["proj-a"],
    )
    assert result["verdict"] == "pass"
    assert result["hits"] == []


def test_cross_project_recall_nonzero_redact_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = MagicMock()
    mock.returncode = 1
    mock.stdout = ""
    mock.stderr = "redaction failed"
    monkeypatch.setattr(recall.subprocess, "run", lambda *_a, **_k: mock)
    assert recall.redact_text("token") is None
