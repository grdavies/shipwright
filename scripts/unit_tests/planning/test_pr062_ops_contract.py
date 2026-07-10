"""PRD 062 phase 4 — cleanup, budget, status vocab, facade rails (R15 h–k)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import cleanup_lib
import planning_query_cache as pqc
import planning_request_budget as prb
import planning_store as ps
import planning_unit_status as pus


def _write_state(root: Path, slug: str, *, verdict: str, target: str | None = None) -> None:
    state_path = root / ".cursor" / f"sw-deliver-state.{slug}.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {"verdict": verdict, "updatedAt": "2026-07-10T00:00:00Z"}
    if target:
        payload["target"] = {"branch": target}
    state_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_cleanup_scopes_inflight_to_active_run(tmp_git_repo: Path) -> None:
    """R15(h)/R10 — unrelated running scoped state does not block active cleanup scope."""
    subprocess.run(["git", "checkout", "-b", "feat/beta"], cwd=tmp_git_repo, check=True, capture_output=True)
    _write_state(tmp_git_repo, "alpha", verdict="running", target="feat/alpha")
    _write_state(tmp_git_repo, "beta", verdict="complete", target="feat/beta")
    inflight, reason = cleanup_lib.deliver_inflight(tmp_git_repo)
    assert inflight is False
    assert reason == ""


@pytest.mark.parametrize("verdict", ["blocked", "halted", "watching"])
def test_cleanup_protects_resumable_nonterminal_verdicts(tmp_git_repo: Path, verdict: str) -> None:
    """R15(h)/R10 — blocked/halted/watching run-state is protected from cleanup."""
    subprocess.run(["git", "checkout", "-b", "feat/demo"], cwd=tmp_git_repo, check=True, capture_output=True)
    _write_state(tmp_git_repo, "demo", verdict=verdict, target="feat/demo")
    report = cleanup_lib.enumerate_cleanup(tmp_git_repo)
    run_state_protected = [item for item in report.protected if item.kind == "run-state"]
    assert run_state_protected
    assert any(verdict in item.detail for item in run_state_protected)
    assert any("resumable deliver halt detected" in note for note in report.notes)


def test_cleanup_terminal_allowlist_excludes_blocked_autonomy(tmp_git_repo: Path) -> None:
    """R15(i)/R11 — autonomy does not delete blocked run-state and returns hygiene halt."""
    subprocess.run(["git", "checkout", "-b", "feat/demo"], cwd=tmp_git_repo, check=True, capture_output=True)
    cfg_dir = tmp_git_repo / ".cursor"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "workflow.config.json").write_text(
        json.dumps({"cleanup": {"autonomy": "auto"}}), encoding="utf-8"
    )
    _write_state(tmp_git_repo, "demo", verdict="blocked", target="feat/demo")
    out = cleanup_lib.apply_autonomous_cleanup(tmp_git_repo)
    assert out["verdict"] == "halt"
    assert "verdict=blocked" in out["reason"]
    assert not out["report"]["wouldRemove"]


def test_cleanup_terminal_allowlist_includes_complete(tmp_git_repo: Path) -> None:
    """R15(i)/R11 — only allowlisted terminal verdicts are cleanup candidates."""
    subprocess.run(["git", "checkout", "-b", "feat/demo"], cwd=tmp_git_repo, check=True, capture_output=True)
    _write_state(tmp_git_repo, "demo", verdict="complete", target="feat/demo")
    report = cleanup_lib.enumerate_cleanup(tmp_git_repo)
    run_state_candidates = [item for item in report.would_remove if item.kind == "run-state"]
    assert run_state_candidates


def test_parallel_ledger_isolation(tmp_git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R15(i)/R12 — parallel deliver runs keep separate budget ledgers."""
    monkeypatch.setenv("SW_RUN_DIR", ".cursor/sw-deliver-runs/run-a")
    path_a = prb.ledger_path(tmp_git_repo)
    monkeypatch.setenv("SW_RUN_DIR", ".cursor/sw-deliver-runs/run-b")
    path_b = prb.ledger_path(tmp_git_repo)
    assert path_a != path_b
    assert "run-a" in str(path_a)
    assert "run-b" in str(path_b)


def test_request_budget_uses_per_run_ledger_path(tmp_git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R15(i)/R12 — SW_RUN_DIR isolates ledgers by deliver run."""
    monkeypatch.setenv("SW_RUN_DIR", ".cursor/sw-deliver-runs/run-a")
    path = prb.ledger_path(tmp_git_repo)
    assert str(path).endswith(".cursor/sw-deliver-runs/run-a/planning-request-budget.json")


def test_request_budget_default_github_max_calls_750(tmp_git_repo: Path) -> None:
    """R15(i)/R12 — github requestBudget default maxCalls raised to 750."""
    ledger = prb.RequestBudgetLedger.from_config(tmp_git_repo, "github-issues")
    assert ledger.max_calls == 750


def test_critical_ops_bypass_cache_ttl(tmp_git_repo: Path) -> None:
    """R15(i)/R12 — critical cache reads bypass TTL; non-critical keeps configured TTL."""
    assert pqc.resolve_ttl(tmp_git_repo, "github-issues") > 0
    assert pqc.resolve_ttl(tmp_git_repo, "github-issues", critical=True) == 0


def test_status_vocab_unknown_and_unauthorized_are_non_terminal() -> None:
    """R15(j)/R13 — canonical four-state status keeps unknown/unauthorized non-terminal."""
    assert pus.map_native_status_to_unified("mystery", "prd") == "unknown"
    assert pus.canonical_status("unknown") == "planned"
    assert pus.canonical_status("unauthorized") == "planned"
    assert pus.status_is_complete("unknown") is False
    assert pus.status_is_complete("unauthorized") is False


def test_status_issue_lookup_auth_failure_is_fail_closed(
    tmp_git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R15(j)/R13 — issue lookup auth/capability failures fail closed."""
    monkeypatch.setattr(
        pus,
        "issue_get_facade",
        lambda *_args, **_kwargs: {"verdict": "fail", "error": "issue-capability-error"},
    )
    with pytest.raises(SystemExit) as exc:
        pus._lookup_issue_record(tmp_git_repo, "123")
    assert exc.value.code == 2


def test_facade_baseline_removes_planning_unit_status(repo_root: Path) -> None:
    """R15(k)/R16 — status script no longer requires facade bypass baseline entry."""
    assert "scripts/planning_unit_status.py" not in ps.FACADE_BYPASS_BASELINE
    lint = ps.lint_facade_imports(repo_root, scope="scripts/planning_unit_status.py")
    assert lint["verdict"] == "pass"
