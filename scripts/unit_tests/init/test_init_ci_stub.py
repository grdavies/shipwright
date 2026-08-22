"""CI stub plan/apply tests (PRD 324 phase 12 / R5–R7, R14)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from init_ci_stub import (  # noqa: E402
    STUB_WORKFLOW_REL,
    apply_ci_stub,
    plan_ci_stub,
    render_stub_body,
)
from wave_preflight import CI_PRESENCE_RESTRICTED, CI_PRESENCE_SATISFIED, scan_ci_workflows  # noqa: E402


def _seed_ci_stub_template(repo: Path, repo_root: Path) -> None:
    src = repo_root / "core/sw-reference/templates/ci-stub-pull-request.yml"
    dest_dir = repo / "core/sw-reference/templates"
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest_dir / "ci-stub-pull-request.yml")


def _write_restricted_workflow(repo: Path) -> None:
    workflows = repo / ".github/workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / "ci.yml").write_text(
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
        encoding="utf-8",
    )


class TestInitCiStub:
    def test_apply_without_confirm_refuses(self, tmp_git_repo: Path, repo_root: Path) -> None:
        _seed_ci_stub_template(tmp_git_repo, repo_root)
        result = apply_ci_stub(tmp_git_repo, confirm=False)
        assert result["verdict"] == "fail"
        assert result["error"] == "confirm-required"
        assert not (tmp_git_repo / STUB_WORKFLOW_REL).exists()

    def test_empty_repo_apply_seeds_unrestricted_pull_request(
        self, tmp_git_repo: Path, repo_root: Path
    ) -> None:
        _seed_ci_stub_template(tmp_git_repo, repo_root)
        plan = plan_ci_stub(tmp_git_repo)
        assert plan["needed"] is True
        assert plan["reason"] == "no-workflows"
        result = apply_ci_stub(tmp_git_repo, confirm=True)
        assert result["verdict"] == "pass"
        assert result["written"] is True
        body = (tmp_git_repo / STUB_WORKFLOW_REL).read_text(encoding="utf-8")
        assert "pull_request:" in body
        assert "branches:" not in body.split("pull_request:")[1].split("jobs:")[0]

    def test_second_apply_is_noop_preserving_operator_edits(
        self, tmp_git_repo: Path, repo_root: Path
    ) -> None:
        _seed_ci_stub_template(tmp_git_repo, repo_root)
        apply_ci_stub(tmp_git_repo, confirm=True)
        target = tmp_git_repo / STUB_WORKFLOW_REL
        edited = target.read_text(encoding="utf-8") + "# operator edit\n"
        target.write_text(edited, encoding="utf-8")
        second = apply_ci_stub(tmp_git_repo, confirm=True)
        assert second["verdict"] == "noop"
        assert second["reason"] in ("already-present", "satisfied")
        assert target.read_text(encoding="utf-8") == edited

    def test_restricted_trigger_fixture_detected(self, tmp_git_repo: Path, repo_root: Path) -> None:
        _seed_ci_stub_template(tmp_git_repo, repo_root)
        _write_restricted_workflow(tmp_git_repo)
        scan = scan_ci_workflows(tmp_git_repo, "main")
        assert scan["presence"] == CI_PRESENCE_RESTRICTED
        plan = plan_ci_stub(tmp_git_repo)
        assert plan["needed"] is True
        assert plan["reason"] == "restricted-PR-trigger"

    def test_placeholder_job_does_not_advertise_verify_without_opt_in(
        self, tmp_git_repo: Path, repo_root: Path
    ) -> None:
        _seed_ci_stub_template(tmp_git_repo, repo_root)
        default_body = render_stub_body(tmp_git_repo, wire_verify="off")
        assert "check-gate.py" not in default_body
        assert "placeholder" in default_body.lower() or "Placeholder" in default_body
        wired = render_stub_body(tmp_git_repo, wire_verify="on")
        assert "check-gate.py" in wired

    def test_stub_seeded_repo_scans_satisfied(self, tmp_git_repo: Path, repo_root: Path) -> None:
        _seed_ci_stub_template(tmp_git_repo, repo_root)
        apply_ci_stub(tmp_git_repo, confirm=True)
        scan = scan_ci_workflows(tmp_git_repo, "main")
        assert scan["presence"] == CI_PRESENCE_SATISFIED
        assert scan["ok"] is True
