#!/usr/bin/env python3
"""Gap-resolution store close + label golden-output parity (PRD 057 R4; task 8.5).

Proves the R4 gap-resolution guard end to end using the hermetic issues fixture
store (``SW_ISSUES_FIXTURE=1`` — no network, no live provider):

- **File-store parity:** ``gap_backlog.resolve_for_prd`` is untouched under a
  non-issue-store backend — no issue-store dependency is invoked.
- **Same-repo unchanged:** under issue-store ``same-repo`` resolution keeps
  flipping the local canonical gap frontmatter + legacy ``GAP-BACKLOG.md`` row
  exactly as before R4 — no issue close/label call happens.
- **Separate-project close + label:** under ``separate-project`` resolution
  closes the scheduled gap issue and applies the ``sw:gap-resolved`` label
  directly — idempotently on repeat, and it aggregates a ``resolution-partial``
  verdict (never raises) when the issue lookup fails.
- **set_index_status propagation:** ``reconcile_lib.set_index_status`` forwards
  the resolver's verdict verbatim, so a separate-project resolution failure
  surfaces as ``resolution-partial`` (distinct from the same-repo exception
  path's generic ``partial``).

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
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import gap_backlog as gb  # noqa: E402
import reconcile_lib as rl  # noqa: E402
from issues_lib import IssuesClient  # noqa: E402
from planning_canonical import (  # noqa: E402
    GAP_LABEL_RESOLVED,
    GAP_LABEL_SCHEDULED,
    project_label,
    title_prefix,
    type_label,
)

_PROJECT_KEY = "gap-resolution-golden-fixture"

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


def _sandbox(cfg: dict) -> Path:
    root = Path(tempfile.mkdtemp(prefix="sw-gap-resolution-golden-"))
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    cfg_path = root / ".cursor" / "workflow.config.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return root


def _schedule_label(prd: str) -> str:
    return f"sw:gap-schedule:PRD%20{prd}"


def _create_scheduled_gap_issue(root: Path, *, unit_id: str, prd: str):
    client = IssuesClient(root, "github-issues")
    return client.issue_create(
        title=f"{title_prefix(_PROJECT_KEY)} gap:{unit_id}",
        body=f"---\ntype: gap\nunit-id: {unit_id}\nstatus: scheduled\nschedule: PRD {prd}\n---\n\nGolden fixture gap.\n",
        labels=sorted(
            {GAP_LABEL_SCHEDULED, _schedule_label(prd), project_label(_PROJECT_KEY), type_label("gap")}
        ),
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


def check_file_store_resolve_for_prd_untouched() -> dict:
    """File-store: resolve_for_prd never consults the issue-store path."""
    root = _sandbox({})
    result = gb.resolve_for_prd(root, "057")
    ok = result.get("verdict") == "pass" and result.get("flipped") == []
    return {
        "name": "file-store-resolve-for-prd-untouched",
        "ok": ok,
        "detail": f"result={result}",
    }


def check_same_repo_resolve_keeps_frontmatter_path() -> dict:
    """State: same-repo issue-store keeps the pre-R4 frontmatter/row flip — no issue close call."""
    with _FixtureEnv():
        root = _sandbox(_SAME_REPO_CFG)
        record = _create_scheduled_gap_issue(root, unit_id="gap-951-golden", prd="057")
        with mock.patch.object(gb, "close_gap_issue") as spy:
            result = gb.resolve_for_prd(root, "057")
        client = IssuesClient(root, "github-issues")
        refetched = client.issue_get(record.id)
    ok = (
        result.get("verdict") == "pass"
        and not spy.called
        and refetched.state == "open"
    )
    return {
        "name": "same-repo-resolve-keeps-frontmatter-path",
        "ok": ok,
        "detail": f"result={result} closeGapIssueCalled={spy.called} issueState={refetched.state}",
    }


def check_separate_project_closes_and_labels() -> dict:
    """Separate-project: resolve_for_prd closes the scheduled gap issue + applies the resolved label."""
    with _FixtureEnv():
        root = _sandbox(_SEPARATE_PROJECT_CFG)
        record = _create_scheduled_gap_issue(root, unit_id="gap-952-golden", prd="057")
        result = gb.resolve_for_prd(root, "057")
        client = IssuesClient(root, "github-issues")
        refetched = client.issue_get(record.id)
    ok = (
        result.get("verdict") == "pass"
        and result.get("flipped") == ["gap-952-golden"]
        and refetched.state == "closed"
        and GAP_LABEL_RESOLVED in refetched.labels
        and GAP_LABEL_SCHEDULED not in refetched.labels
    )
    return {
        "name": "separate-project-closes-and-labels",
        "ok": ok,
        "detail": f"result={result} issueState={refetched.state} labels={refetched.labels}",
    }


def check_separate_project_repeated_close_idempotent() -> dict:
    """Many: repeated resolution under separate-project stays a no-op pass (idempotent)."""
    with _FixtureEnv():
        root = _sandbox(_SEPARATE_PROJECT_CFG)
        _create_scheduled_gap_issue(root, unit_id="gap-953-golden", prd="057")
        first = gb.resolve_for_prd(root, "057")
        second = gb.resolve_for_prd(root, "057")
    ok = (
        first.get("verdict") == "pass"
        and second.get("verdict") == "pass"
        and first.get("flipped") == ["gap-953-golden"]
        and second.get("flipped") == ["gap-953-golden"]
    )
    return {
        "name": "separate-project-repeated-close-idempotent",
        "ok": ok,
        "detail": f"first={first} second={second}",
    }


def check_separate_project_partial_failure_aggregates() -> dict:
    """Zero/failure: a close_gap_issue failure aggregates to resolution-partial, not a raise."""
    with _FixtureEnv():
        root = _sandbox(_SEPARATE_PROJECT_CFG)
        _create_scheduled_gap_issue(root, unit_id="gap-954-golden", prd="057")
        with mock.patch.object(
            gb, "close_gap_issue", return_value={"verdict": "resolution-partial", "error": "simulated"}
        ):
            result = gb.resolve_for_prd(root, "057")
    ok = result.get("verdict") == "resolution-partial" and "gap-954-golden" in (result.get("error") or "")
    return {
        "name": "separate-project-partial-failure-aggregates",
        "ok": ok,
        "detail": f"result={result}",
    }


def check_set_index_status_propagates_resolution_partial() -> dict:
    """Interfaces: set_index_status forwards resolution-partial verbatim (distinct from generic partial)."""
    root = _sandbox({})
    subprocess.run(["git", "checkout", "-q", "-b", "docs/gap-resolution-golden"], cwd=str(root), check=True)
    (root / "docs" / "prds").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "prds" / "INDEX.md").write_text(
        "\n".join(
            [
                "# INDEX",
                "| # | Slug | PRD | Tasks | Status |",
                "|---|------|-----|-------|--------|",
                "| 057 | fixture | [prd](057-fixture/057-prd-fixture.md) | [tasks](057-fixture/tasks.md) | in-progress |",
                "",
            ]
        ),
        encoding="utf-8",
    )
    with mock.patch.object(
        gb, "resolve_for_prd", return_value={"verdict": "resolution-partial", "flipped": [], "error": "simulated"}
    ):
        result = rl.set_index_status(root, "057", "complete")
    ok = result.get("verdict") == "resolution-partial" and result.get("error") == "simulated"
    return {
        "name": "set-index-status-propagates-resolution-partial",
        "ok": ok,
        "detail": f"result={result}",
    }


def run() -> dict:
    """Entry point discovered by ``planning-file-store-parity/harness.py``."""
    checks = [
        check_file_store_resolve_for_prd_untouched(),
        check_same_repo_resolve_keeps_frontmatter_path(),
        check_separate_project_closes_and_labels(),
        check_separate_project_repeated_close_idempotent(),
        check_separate_project_partial_failure_aggregates(),
        check_set_index_status_propagates_resolution_partial(),
    ]
    failures = [c for c in checks if not c.get("ok")]
    return {"ok": not failures, "checks": checks, "failures": failures}


def main() -> int:
    outcome = run()
    report = {
        "fixture": "planning-file-store-parity.gap_resolution_close_label_golden",
        "rid": "R4",
        "verdict": "pass" if outcome["ok"] else "fail",
        "checks": outcome["checks"],
        "failures": outcome["failures"],
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if outcome["ok"] else 20


if __name__ == "__main__":
    raise SystemExit(main())
