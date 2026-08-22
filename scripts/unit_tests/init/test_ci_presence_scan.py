"""R8 — reusable CI-presence scan for init and base-preflight."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wave_preflight import (  # noqa: E402
    CI_PRESENCE_NO_WORKFLOWS,
    CI_PRESENCE_RESTRICTED,
    CI_PRESENCE_SATISFIED,
    run_base_check,
    scan_ci_workflows,
)

STUB_WORKFLOW = """\
# Shipwright CI stub — human-editable; Shipwright will not rewrite after apply.
name: Shipwright CI stub
on:
  pull_request:
jobs:
  placeholder:
    runs-on: ubuntu-latest
    steps:
      - name: Placeholder
        run: echo "Replace with your CI steps"
"""


def _write_workflow(root: Path, name: str, body: str) -> None:
    workflows = root / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / name).write_text(body, encoding="utf-8")


def test_scan_importable_without_cli_side_effects() -> None:
    assert callable(scan_ci_workflows)
    assert scan_ci_workflows.__module__ == "wave_preflight"


def test_empty_repo_reports_no_workflows(tmp_path: Path) -> None:
    result = scan_ci_workflows(tmp_path, "main")
    assert result["presence"] == CI_PRESENCE_NO_WORKFLOWS
    assert result["ok"] is False
    assert result["workflows"] == []


def test_restricted_pr_trigger_reports_verdict(tmp_path: Path) -> None:
    _write_workflow(
        tmp_path,
        "ci.yml",
        """\
name: CI
on:
  pull_request:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: echo test
""",
    )
    result = scan_ci_workflows(tmp_path, "main")
    assert result["presence"] == CI_PRESENCE_RESTRICTED
    assert result["ok"] is False
    assert result["restricted"] == ["ci.yml"]


def test_stub_seeded_repo_scans_satisfied(tmp_path: Path) -> None:
    _write_workflow(tmp_path, "shipwright-ci-stub.yml", STUB_WORKFLOW)
    result = scan_ci_workflows(tmp_path, "main")
    assert result["presence"] == CI_PRESENCE_SATISFIED
    assert result["ok"] is True


def test_stub_passes_base_preflight_ci_or_review(tmp_path: Path) -> None:
    _write_workflow(tmp_path, "shipwright-ci-stub.yml", STUB_WORKFLOW)
    payload = run_base_check(tmp_path, "feat/greenfield-demo", "main")
    assert payload["verdict"] == "pass"
    assert payload["ci"]["presence"] == CI_PRESENCE_SATISFIED


def test_empty_repo_fails_base_preflight(tmp_path: Path) -> None:
    payload = run_base_check(tmp_path, "feat/greenfield-demo", "main")
    assert payload["verdict"] == "fail"
    assert payload["ci"]["presence"] == CI_PRESENCE_NO_WORKFLOWS
