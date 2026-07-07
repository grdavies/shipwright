#!/usr/bin/env python3
"""Gap-capture golden-output parity (PRD 057 R1; task 6.5).

Proves the R1 write-through guard end to end using the hermetic issues fixture
store (``SW_ISSUES_FIXTURE=1`` — no network, no live provider):

- **State (same-repo unchanged):** under issue-store ``same-repo`` the legacy
  ``GAP-BACKLOG.md`` projection write is unchanged from the pre-R1 shape.
- **One / Many (separate-project write-through):** a single capture, and a
  repeated capture, both skip the local projection write under
  ``separate-project`` — gap capture writes through to the store only.
- **Interfaces (--projection):** ``projection=True`` (the CLI ``--projection``
  flag) retains the legacy row write even under ``separate-project``.
- **Zero (sunset stub):** once no open gap issues remain, the projection is
  reduced to a documented sunset stub rather than deleted outright.
- File-store (non-issue-store) capture is untouched by the guard — verbatim
  pre-R1 behavior.

Discovered and run by ``planning-file-store-parity/harness.py::run_golden``
via its ``run()`` entry point; also runnable standalone.
"""
from __future__ import annotations

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

import planning_migrate_issue_store as pmis  # noqa: E402
from issues_lib import IssuesClient  # noqa: E402
from planning_canonical import project_label, title_prefix, type_label  # noqa: E402

_PROJECT_KEY = "gap-golden-fixture"

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
                "repo": "planning-store",
            },
        }
    },
    "host": {"provider": "github"},
}


def _gap_backlog_path(root: Path) -> Path:
    return root / "docs" / "prds" / "GAP-BACKLOG.md"


def _sandbox(cfg: dict) -> Path:
    root = Path(tempfile.mkdtemp(prefix="sw-gap-capture-golden-"))
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    cfg_path = root / ".cursor" / "workflow.config.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return root


def _create_gap_issue(root: Path, *, unit_id: str) -> None:
    client = IssuesClient(root, "github-issues")
    client.issue_create(
        title=f"{title_prefix(_PROJECT_KEY)} gap:{unit_id}",
        body=f"---\ntype: gap\nunit-id: {unit_id}\nstatus: open\n---\n\nGolden fixture gap.\n",
        labels=sorted({"sw:gap-open", project_label(_PROJECT_KEY), type_label("gap")}),
        project_key=_PROJECT_KEY,
        artifact_type="gap",
        unit_id=unit_id,
    )


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


def check_file_store_parity_verbatim() -> dict:
    """Non-issue-store (file-store) capture path is untouched by the R1 guard."""
    root = _sandbox({})
    result = pmis.refresh_gap_backlog_projection(root, {}, apply=True)
    untouched = not _gap_backlog_path(root).is_file()
    ok = result == {"skipped": True, "reason": "not-issue-store"} and untouched
    return {
        "name": "file-store-parity-verbatim",
        "ok": ok,
        "detail": f"result={result} untouched={untouched}",
    }


def check_same_repo_projection_unchanged() -> dict:
    """State: same-repo issue-store keeps writing the full issue-derived projection."""
    with _FixtureEnv():
        root = _sandbox(_SAME_REPO_CFG)
        _create_gap_issue(root, unit_id="gap-901-golden")
        result = pmis.refresh_gap_backlog_projection(root, _SAME_REPO_CFG, apply=True)
        gap_path = _gap_backlog_path(root)
        wrote = gap_path.is_file()
        content = gap_path.read_text(encoding="utf-8") if wrote else ""
    ok = wrote and "GAP-901" in content and not result.get("skipped") and result.get("gapRows") == 1
    return {
        "name": "same-repo-projection-unchanged",
        "ok": ok,
        "detail": f"wrote={wrote} result={result}",
    }


def check_separate_project_skips_local_write() -> dict:
    """One + Many: separate-project write-through skips the local write, repeatedly."""
    with _FixtureEnv():
        root = _sandbox(_SEPARATE_PROJECT_CFG)
        _create_gap_issue(root, unit_id="gap-902-golden")
        first = pmis.refresh_gap_backlog_projection(root, _SEPARATE_PROJECT_CFG, apply=True)
        second = pmis.refresh_gap_backlog_projection(root, _SEPARATE_PROJECT_CFG, apply=True)
        never_wrote = not _gap_backlog_path(root).is_file()
    ok = (
        never_wrote
        and first.get("skipped") is True
        and second.get("skipped") is True
        and first.get("reason") == "separate-project-write-through"
        and second == first
    )
    return {
        "name": "separate-project-skips-local-write-repeated",
        "ok": ok,
        "detail": f"neverWrote={never_wrote} first={first} second={second}",
    }


def check_projection_flag_retains_legacy_row() -> dict:
    """Interfaces: projection=True (--projection) retains the legacy row under separate-project."""
    with _FixtureEnv():
        root = _sandbox(_SEPARATE_PROJECT_CFG)
        _create_gap_issue(root, unit_id="gap-903-golden")
        result = pmis.refresh_gap_backlog_projection(
            root, _SEPARATE_PROJECT_CFG, apply=True, projection=True
        )
        gap_path = _gap_backlog_path(root)
        wrote = gap_path.is_file()
        content = gap_path.read_text(encoding="utf-8") if wrote else ""
    ok = wrote and "GAP-903" in content and not result.get("skipped")
    return {
        "name": "projection-flag-retains-legacy-row",
        "ok": ok,
        "detail": f"wrote={wrote} result={result}",
    }


def check_zero_open_gaps_sunset_stub() -> dict:
    """Zero: no open gaps under separate-project reduces the projection to a sunset stub."""
    with _FixtureEnv():
        root = _sandbox(_SEPARATE_PROJECT_CFG)
        gap_path = _gap_backlog_path(root)
        gap_path.parent.mkdir(parents=True, exist_ok=True)
        gap_path.write_text(pmis.render_gap_backlog_from_issue_records([]), encoding="utf-8")
        result = pmis.try_sunset_gap_backlog_projection(root, _SEPARATE_PROJECT_CFG, apply=True)
        content = gap_path.read_text(encoding="utf-8")
    ok = result.get("stubbed") is True and pmis.GAP_BACKLOG_SUNSET_STUB_MARKER in content
    return {
        "name": "zero-open-gaps-sunset-stub",
        "ok": ok,
        "detail": f"result={result}",
    }


def check_same_repo_sunset_removes_outright() -> dict:
    """Zero (same-repo contrast): same-repo sunset still removes the file outright."""
    with _FixtureEnv():
        root = _sandbox(_SAME_REPO_CFG)
        gap_path = _gap_backlog_path(root)
        gap_path.parent.mkdir(parents=True, exist_ok=True)
        gap_path.write_text(pmis.render_gap_backlog_from_issue_records([]), encoding="utf-8")
        result = pmis.try_sunset_gap_backlog_projection(root, _SAME_REPO_CFG, apply=True)
        removed = not gap_path.is_file()
    ok = result.get("removed") is True and removed
    return {
        "name": "same-repo-sunset-removes-outright",
        "ok": ok,
        "detail": f"result={result} removed={removed}",
    }


def run() -> dict:
    """Entry point discovered by ``planning-file-store-parity/harness.py``."""
    checks = [
        check_file_store_parity_verbatim(),
        check_same_repo_projection_unchanged(),
        check_separate_project_skips_local_write(),
        check_projection_flag_retains_legacy_row(),
        check_zero_open_gaps_sunset_stub(),
        check_same_repo_sunset_removes_outright(),
    ]
    failures = [c for c in checks if not c.get("ok")]
    return {"ok": not failures, "checks": checks, "failures": failures}


def main() -> int:
    outcome = run()
    report = {
        "fixture": "planning-file-store-parity.gap_capture_golden",
        "rid": "R1",
        "verdict": "pass" if outcome["ok"] else "fail",
        "checks": outcome["checks"],
        "failures": outcome["failures"],
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if outcome["ok"] else 20


if __name__ == "__main__":
    raise SystemExit(main())
