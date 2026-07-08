#!/usr/bin/env python3
"""spec-seed + reconcile golden-output parity (PRD 057 R2, R3; task 7.3).

Proves the R2/R3 local-write guards end to end using the hermetic issues
fixture store (``SW_ISSUES_FIXTURE=1`` — no network, no live provider):

- **File-store (non-issue-store) parity:** ``wave_spec_seed.ensure_redacted_index``
  and ``planning_reconcile.reconcile_core`` write the same INDEX structural
  region content — the guard is inert and both entry points stay equivalent
  when the effective backend is not an issue-store (R23).
- **Same-repo unchanged:** under issue-store ``same-repo`` both commands keep
  writing the tracked local artifacts (INDEX.md, INDEX-archive.md,
  SUPERSEDED.md, legacy GAP-BACKLOG.md/INDEX.md projection) unchanged.
- **Separate-project skip:** under ``separate-project`` neither command writes
  a tracked local derived artifact; reconcile instead projects the derived
  map to the authoritative store (PRD 056 R8).

Discovered and run by ``planning-file-store-parity/harness.py::run_golden``
via its ``run()`` entry point; also runnable standalone.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import planning_index_gen as pig  # noqa: E402
import planning_reconcile as pr  # noqa: E402
import wave_spec_seed as wss  # noqa: E402

_PROJECT_KEY = "spec-seed-reconcile-golden-fixture"

_SAME_REPO_CFG = {
    "planning": {
        "store": {
            "backend": "issue-store",
            "issuesProvider": "github-issues",
            "projectKey": _PROJECT_KEY,
        }
    },
    "host": {"provider": "github"},
}

_SEPARATE_PROJECT_CFG = {
    "planning": {
        "store": {
            "backend": "issue-store",
            "issuesProvider": "github-issues",
            "projectKey": _PROJECT_KEY,
            "storeLocation": {
                "mode": "separate-project",
                "owner": "acme",
                "repo": "planning",
            },
        }
    },
    "host": {"provider": "github"},
}

_TRACKED_ARTIFACTS = (
    "docs/prds/INDEX.md",
    "docs/prds/INDEX-archive.md",
    "docs/prds/SUPERSEDED.md",
    "docs/prds/GAP-BACKLOG.md",
)


def _sandbox(cfg: dict) -> Path:
    root = Path(tempfile.mkdtemp(prefix="sw-spec-seed-reconcile-golden-"))
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    cfg_path = root / ".cursor" / "workflow.config.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    return root


def _tracked_artifacts_present(root: Path) -> dict[str, bool]:
    return {rel: (root / rel).is_file() for rel in _TRACKED_ARTIFACTS}


class _FixtureEnv:
    """Scope ``SW_ISSUES_FIXTURE=1`` to a block (hermetic, no network)."""

    def __enter__(self) -> "_FixtureEnv":
        self._prev = os.environ.get("SW_ISSUES_FIXTURE")
        os.environ["SW_ISSUES_FIXTURE"] = "1"
        return self

    def __exit__(self, *exc: object) -> None:
        if self._prev is None:
            os.environ.pop("SW_ISSUES_FIXTURE", None)
        else:
            os.environ["SW_ISSUES_FIXTURE"] = self._prev


def _reconcile_quiet(root: Path, **kwargs: object) -> dict:
    # planning-store put() logs an operation line to stdout; suppress so the
    # harness JSON verdict stays the only line on stdout.
    with contextlib.redirect_stdout(io.StringIO()):
        return pr.reconcile_core(root, **kwargs)  # type: ignore[arg-type]


def check_file_store_spec_seed_reconcile_structural_parity() -> dict:
    """File-store: spec-seed and reconcile emit the same INDEX structural region (R23)."""
    root = _sandbox({})
    seed_rel = wss.ensure_redacted_index(root)
    # ensure_redacted_index resolves the path via pig.index_rel (dirs.planning
    # default) — read back through the same accessor used by reconcile so the
    # comparison is entry-point-agnostic, not path-hardcoded.
    seed_path = pig.index_path(root)
    seed_structural = pig.parse_regions(seed_path.read_text(encoding="utf-8")).structural
    reconcile_result = _reconcile_quiet(root, dry_run=False)
    reconcile_structural = pig.parse_regions(seed_path.read_text(encoding="utf-8")).structural
    ok = (
        seed_rel is None  # untracked temp sandbox — same-repo/file-store shape unaffected by R2
        and seed_structural == reconcile_structural
        and "storeProjection" not in reconcile_result
    )
    return {
        "name": "file-store-spec-seed-reconcile-structural-parity",
        "ok": ok,
        "detail": f"seedRel={seed_rel} structuralEqual={seed_structural == reconcile_structural}",
    }


def check_same_repo_writes_unchanged() -> dict:
    """State: same-repo issue-store keeps writing tracked local derived artifacts (both commands)."""
    with _FixtureEnv():
        root = _sandbox(_SAME_REPO_CFG)
        seed_rel = wss.ensure_redacted_index(root)
        after_seed = pig.index_path(root).is_file()
        reconcile_result = _reconcile_quiet(root, dry_run=False)
        present = _tracked_artifacts_present(root)
    ok = (
        after_seed
        and all(present.values())
        and not reconcile_result.get("legacy", {}).get("skipped")
        and "storeProjection" not in reconcile_result
    )
    return {
        "name": "same-repo-writes-unchanged",
        "ok": ok,
        "detail": f"seedRel={seed_rel} afterSeed={after_seed} present={present} legacy={reconcile_result.get('legacy')}",
    }


def check_separate_project_skips_all_tracked_writes() -> dict:
    """Separate-project: neither spec-seed nor reconcile writes a tracked local derived artifact."""
    with _FixtureEnv():
        root = _sandbox(_SEPARATE_PROJECT_CFG)
        seed_rel = wss.ensure_redacted_index(root)
        after_seed = pig.index_path(root).is_file()
        reconcile_result = _reconcile_quiet(root, dry_run=False)
        present = _tracked_artifacts_present(root)
    ok = (
        seed_rel is None
        and not after_seed
        and not any(present.values())
        and reconcile_result.get("legacy", {}).get("skipped") is True
        and reconcile_result.get("legacy", {}).get("reason") == "separate-project-issue-store"
        and reconcile_result.get("storeProjection", {}).get("verdict") == "pass"
    )
    return {
        "name": "separate-project-skips-all-tracked-writes",
        "ok": ok,
        "detail": (
            f"seedRel={seed_rel} afterSeed={after_seed} present={present} "
            f"legacy={reconcile_result.get('legacy')} storeProjection={reconcile_result.get('storeProjection')}"
        ),
    }


def check_separate_project_repeated_reconcile_idempotent() -> dict:
    """Many: repeated reconcile under separate-project stays skip + store-projected, never local."""
    with _FixtureEnv():
        root = _sandbox(_SEPARATE_PROJECT_CFG)
        first = _reconcile_quiet(root, dry_run=False)
        second = _reconcile_quiet(root, dry_run=False)
        present = _tracked_artifacts_present(root)
    ok = (
        not any(present.values())
        and first.get("legacy", {}).get("skipped") is True
        and second.get("legacy", {}).get("skipped") is True
        and first.get("storeProjection", {}).get("verdict") == "pass"
        and second.get("storeProjection", {}).get("verdict") == "pass"
    )
    return {
        "name": "separate-project-repeated-reconcile-idempotent",
        "ok": ok,
        "detail": f"present={present} first={first.get('legacy')} second={second.get('legacy')}",
    }


def run() -> dict:
    """Entry point discovered by ``planning-file-store-parity/harness.py``."""
    checks = [
        check_file_store_spec_seed_reconcile_structural_parity(),
        check_same_repo_writes_unchanged(),
        check_separate_project_skips_all_tracked_writes(),
        check_separate_project_repeated_reconcile_idempotent(),
    ]
    failures = [c for c in checks if not c.get("ok")]
    return {"ok": not failures, "checks": checks, "failures": failures}


def main() -> int:
    outcome = run()
    report = {
        "fixture": "planning-file-store-parity.spec_seed_reconcile_golden",
        "rid": "R2,R3",
        "verdict": "pass" if outcome["ok"] else "fail",
        "checks": outcome["checks"],
        "failures": outcome["failures"],
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if outcome["ok"] else 20


if __name__ == "__main__":
    raise SystemExit(main())
