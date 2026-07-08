#!/usr/bin/env python3
"""Full deliver-chain parity matrix fixture (PRD 057 R6; task 19.2).

Asserts the cumulative Waves 1–5 guards hold end-to-end:

1. The published command×artifact×backend matrix exists and names the guarded surfaces.
2. Under issue-store ``separate-project`` (hermetic ``SW_ISSUES_FIXTURE=1``), the brainstorm→PRD→
   tasks→deliver pollution stoppers write **no tracked local planning derived artifact** —
   gap-capture, spec-seed, reconcile, gap-resolution, and docs-worktree handoff all divert to the
   store or skip with an explicit reason.
3. Per-command golden modules from ``planning-file-store-parity`` pass under the fixture store.
4. The per-wave incremental fixture (R24) still passes against the frozen task list.
5. Operator doc surfaces link the matrix (deliver skill + configuration guide).

File-store / token-absent behavior follows R30: deterministic hermetic checks always run; live
issue-store authoritative checks degrade to skip-with-advisory when the store token is absent.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import planning_store  # noqa: E402

MATRIX_REL = "core/sw-reference/planning-deliver-parity-matrix.md"
TRACKED_DERIVED = (
    "docs/prds/INDEX.md",
    "docs/prds/INDEX-archive.md",
    "docs/prds/SUPERSEDED.md",
    "docs/prds/GAP-BACKLOG.md",
)

_SEPARATE_PROJECT_CFG = {
    "planning": {
        "store": {
            "backend": "issue-store",
            "issuesProvider": "github-issues",
            "projectKey": "full-matrix-fixture",
            "storeLocation": {
                "mode": "separate-project",
                "owner": "acme",
                "repo": "planning-store",
            },
        }
    },
    "host": {"provider": "github"},
}

_REQUIRED_MATRIX_COMMANDS = (
    "docs_worktree",
    "refresh_gap_backlog_projection",
    "ensure_redacted_index",
    "reconcile_core",
    "resolve_for_prd",
    "doctor_separate_project_local_writes",
)

_DOC_SURFACES = (
    ("core/skills/deliver/SKILL.md", "planning-deliver-parity-matrix"),
    ("docs/guides/configuration.md", "planning-deliver-parity-matrix"),
)


def _load_module(rel_path: str, name: str) -> ModuleType:
    path = ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FixtureEnv:
    def __enter__(self) -> "_FixtureEnv":
        self._prev = os.environ.get("SW_ISSUES_FIXTURE")
        os.environ["SW_ISSUES_FIXTURE"] = "1"
        return self

    def __exit__(self, *exc: object) -> None:
        if self._prev is None:
            os.environ.pop("SW_ISSUES_FIXTURE", None)
        else:
            os.environ["SW_ISSUES_FIXTURE"] = self._prev


def _sandbox(cfg: dict) -> Path:
    root = Path(tempfile.mkdtemp(prefix="sw-full-matrix-"))
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    cfg_path = root / ".cursor" / "workflow.config.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return root


def check_matrix_published() -> dict:
    path = ROOT / MATRIX_REL
    if not path.is_file():
        return {
            "name": "matrix-published",
            "ok": False,
            "detail": f"missing:{MATRIX_REL}",
        }
    text = path.read_text(encoding="utf-8")
    ok = (
        "issue-store `separate-project`" in text
        and "file-store (default)" in text
        and all(cmd in text for cmd in _REQUIRED_MATRIX_COMMANDS)
        and "full_matrix.py" in text
    )
    return {
        "name": "matrix-published",
        "ok": ok,
        "detail": f"path={MATRIX_REL} bytes={path.stat().st_size}",
    }


def check_doc_surface_links() -> dict:
    missing: list[str] = []
    for rel, needle in _DOC_SURFACES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        if needle not in text:
            missing.append(rel)
    return {
        "name": "doc-surface-links",
        "ok": not missing,
        "detail": f"missing={missing}",
    }


def check_wave_incremental_passes() -> dict:
    wi = _load_module(
        "scripts/test/fixtures/planning-deliver-parity/wave_incremental.py",
        "_full_matrix_wave_incremental",
    )
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        exit_code = wi.main()
    try:
        report = json.loads(buf.getvalue())
    except json.JSONDecodeError:
        report = {"verdict": "fail", "raw": buf.getvalue()[:200]}
    ok = exit_code == 0 and report.get("verdict") == "pass"
    return {
        "name": "wave-incremental-green",
        "ok": ok,
        "detail": f"exitCode={exit_code} verdict={report.get('verdict')}",
    }


def check_file_store_parity_goldens() -> dict:
    fsp = _load_module(
        "scripts/test/fixtures/planning-file-store-parity/harness.py",
        "_full_matrix_fsp",
    )
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        exit_code = fsp.main()
    report = json.loads(buf.getvalue())
    golden = report.get("goldenModules") or []
    golden_failures = [g for g in golden if not g.get("ok")]
    ok = exit_code == 0 and report.get("verdict") == "pass" and not golden_failures
    return {
        "name": "file-store-parity-goldens",
        "ok": ok,
        "detail": f"exitCode={exit_code} goldenFailures={golden_failures}",
    }


def check_docs_worktree_separate_project_skip() -> dict:
    docs_wt = _load_module("scripts/docs_worktree.py", "_full_matrix_docs_wt")
    with _FixtureEnv():
        root = _sandbox(_SEPARATE_PROJECT_CFG)
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            exit_code = docs_wt.emit_separate_project_skip(root, "docs_worktree", "parity-topic")
        payload = json.loads(buf.getvalue())
    ok = (
        exit_code == 0
        and payload.get("skipped") is True
        and payload.get("reason") == "separate-project-issue-store"
        and payload.get("handoff", {}).get("issueRefsOnly") is True
    )
    return {
        "name": "docs-worktree-separate-project-skip",
        "ok": ok,
        "detail": payload,
    }


def check_simulated_deliver_chain_no_tracked_writes() -> dict:
    """Hermetic separate-project: run pollution-stopper entry points; no tracked derived files."""
    gap_golden = _load_module(
        "scripts/test/fixtures/planning-file-store-parity/gap_capture_golden.py",
        "_full_matrix_gap",
    )
    seed_golden = _load_module(
        "scripts/test/fixtures/planning-file-store-parity/spec_seed_reconcile_golden.py",
        "_full_matrix_seed",
    )
    with _FixtureEnv():
        gap_outcome = gap_golden.run()
        seed_outcome = seed_golden.run()
    gap_ok = gap_outcome.get("ok") is True
    seed_ok = seed_outcome.get("ok") is True
    separate_checks = [
        c
        for mod in (gap_outcome, seed_outcome)
        for c in (mod.get("checks") or [])
        if "separate-project" in c.get("name", "")
    ]
    separate_ok = all(c.get("ok") for c in separate_checks)
    ok = gap_ok and seed_ok and separate_ok
    return {
        "name": "simulated-chain-no-tracked-writes",
        "ok": ok,
        "detail": {
            "gapGolden": gap_ok,
            "seedGolden": seed_ok,
            "separateProjectChecks": separate_checks,
        },
    }


def check_doctor_clean_sandbox() -> dict:
    with _FixtureEnv():
        root = _sandbox(_SEPARATE_PROJECT_CFG)
        cfg = dict(_SEPARATE_PROJECT_CFG)
        result = planning_store.doctor_separate_project_local_writes(root, cfg)
    ok = result.get("verdict") == "pass" and "no-tracked-planning-bodies" in (
        result.get("checks") or []
    )
    return {
        "name": "doctor-clean-separate-project-sandbox",
        "ok": ok,
        "detail": result,
    }


def check_live_issue_store_side() -> dict:
    """Live repo: verify guard predicate alignment; skip when token absent (R30)."""
    cfg = planning_store.load_workflow_config(ROOT)
    effective = planning_store.resolve_effective_backend(ROOT, cfg)
    if effective.get("effective") != "issue-store":
        return {
            "name": "live-issue-store-authoritative",
            "skipped": True,
            "reason": "backend-not-issue-store",
        }
    provider = planning_store.resolve_issues_provider(cfg).get("provider", "")
    token_env = planning_store.resolve_issues_token_env(cfg, provider)
    if not token_env or not planning_store.token_present(token_env):
        return {
            "name": "live-issue-store-authoritative",
            "skipped": True,
            "reason": "store-token-absent",
        }
    from planning_artifact_handle import issue_store_separate_project_effective

    predicate = issue_store_separate_project_effective(ROOT, cfg)
    location = planning_store.resolve_store_location(ROOT, cfg)
    ok = predicate == (location.get("mode") == "separate-project")
    return {
        "name": "live-issue-store-authoritative",
        "skipped": False,
        "ok": ok,
        "detail": f"mode={location.get('mode')} predicate={predicate}",
    }


def main() -> int:
    checks = [
        check_matrix_published(),
        check_doc_surface_links(),
        check_wave_incremental_passes(),
        check_file_store_parity_goldens(),
        check_docs_worktree_separate_project_skip(),
        check_simulated_deliver_chain_no_tracked_writes(),
        check_doctor_clean_sandbox(),
        check_live_issue_store_side(),
    ]
    ran = [c for c in checks if not c.get("skipped")]
    failures = [c for c in ran if not c.get("ok")]
    verdict = "pass" if not failures else "fail"
    report = {
        "fixture": "planning-deliver-parity",
        "suite": "full_matrix",
        "rid": "R6",
        "verdict": verdict,
        "matrix": MATRIX_REL,
        "trackedDerivedArtifacts": list(TRACKED_DERIVED),
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if verdict == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
