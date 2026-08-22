"""Empty-repo init → stub apply → preflight integration test (PRD 324 phase 12 / R8, R14)."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from init_ci_stub import apply_ci_stub, record_decline  # noqa: E402
from wave_preflight import (  # noqa: E402
    CI_PRESENCE_NO_WORKFLOWS,
    CI_PRESENCE_SATISFIED,
    run_base_check,
    scan_ci_workflows,
)


def _seed_ci_stub_template(repo: Path, repo_root: Path) -> None:
    src = repo_root / "core/sw-reference/templates/ci-stub-pull-request.yml"
    dest_dir = repo / "core/sw-reference/templates"
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest_dir / "ci-stub-pull-request.yml")


def test_empty_repo_fails_then_passes_after_stub_apply(
    tmp_git_repo: Path, repo_root: Path
) -> None:
    _seed_ci_stub_template(tmp_git_repo, repo_root)
    before = scan_ci_workflows(tmp_git_repo, "main")
    assert before["presence"] == CI_PRESENCE_NO_WORKFLOWS
    preflight_before = run_base_check(tmp_git_repo, "feat/demo", "main")
    assert preflight_before["verdict"] == "fail"

    applied = apply_ci_stub(tmp_git_repo, confirm=True)
    assert applied["verdict"] == "pass"

    after = scan_ci_workflows(tmp_git_repo, "main")
    assert after["presence"] == CI_PRESENCE_SATISFIED
    preflight_after = run_base_check(tmp_git_repo, "feat/demo", "main")
    assert preflight_after["verdict"] == "pass"
    assert preflight_after["ci"]["presence"] == CI_PRESENCE_SATISFIED


def test_explicit_decline_recorded_and_reported(tmp_git_repo: Path, repo_root: Path) -> None:
    _seed_ci_stub_template(tmp_git_repo, repo_root)
    decline = record_decline(tmp_git_repo, reason="operator-decline")
    assert decline["declined"] is True
    decline_path = tmp_git_repo / ".cursor/sw-init-ci-stub.json"
    assert decline_path.is_file()
    stored = json.loads(decline_path.read_text(encoding="utf-8"))
    assert stored["declined"] is True
    assert stored["surface"] == "ci-stub"

    skipped = apply_ci_stub(tmp_git_repo, confirm=True)
    assert skipped["verdict"] == "noop"
    assert skipped["reason"] == "declined"
