#!/usr/bin/env python3
"""Hard-block when living-doc ledger drifts from durable deliver state for the current run (R50). """
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main

# Documentation artifacts that must ship in the same release as the code they describe (PRD 081 R21/R24).
# Consumed by phase-18 fixtures (`scripts/unit_tests/docs/test_docs_currency_081.py`).
COMMAND_DOC_CURRENCY_ARTIFACTS: tuple[dict[str, object], ...] = (
    {
        "id": "sw-doc",
        "doc": "core/commands/sw-doc.md",
        "code": (
            "scripts/doc_loop.py",
            "scripts/wave_spec_seed.py",
            "scripts/docs_worktree.py",
            "scripts/docs_pr.py",
        ),
        "needles": (
            "sw-doc-runs",
            "Durable doc-run driver",
            "Publication path by store mode",
            "UNREACHABLE_PUBLICATION_STAGES",
            "docs_pr.py",
        ),
    },
    {
        "id": "sw-tasks",
        "doc": "core/commands/sw-tasks.md",
        "code": ("scripts/doc_loop.py", "scripts/check_frozen_lib.py"),
        "needles": ("noFreeze", "Freeze ownership", "related-work", "doc-loop"),
    },
    {
        "id": "sw-freeze",
        "doc": "core/commands/sw-freeze.md",
        "code": ("scripts/check_frozen_lib.py", "scripts/check-frozen.py", "scripts/planning_store.py"),
        "needles": (
            "Freeze receipt",
            "durabilityState",
            "driverInvoked",
            "durability-not-verified",
        ),
    },
    {
        "id": "sw-deliver",
        "doc": "core/commands/sw-deliver.md",
        "code": (
            "scripts/wave_deliver.py",
            "scripts/wave_terminal.py",
            "scripts/wave_run_adopt.py",
            "scripts/wave_deliver_loop.py",
        ),
        "needles": (
            "list, resume, finalize",
            "Resume cardinality",
            "Drain-budget",
            "Run finalization vs",
            "finalize:merge-unverified",
        ),
    },
)


def enumerate_command_doc_currency_artifacts() -> tuple[dict[str, object], ...]:
    """Return the canonical command-documentation currency artifact set."""
    return COMMAND_DOC_CURRENCY_ARTIFACTS


def _git_last_commit_epoch(root: Path, rel: str) -> int | None:
    import subprocess

    proc = subprocess.run(
        ["git", "log", "-1", "--format=%ct", "--", rel],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        return int(proc.stdout.strip())
    except ValueError:
        return None


def check_command_documentation_currency(root: Path) -> list[dict[str, object]]:
    """Fail when a listed command doc is missing, needle-incomplete, or older than its code surface."""
    drift: list[dict[str, object]] = []
    for entry in COMMAND_DOC_CURRENCY_ARTIFACTS:
        doc_rel = str(entry["doc"])
        doc_path = root / doc_rel
        artifact_id = str(entry.get("id") or doc_rel)
        if not doc_path.is_file():
            drift.append({"kind": "command-doc-missing", "artifact": artifact_id, "doc": doc_rel})
            continue
        text = doc_path.read_text(encoding="utf-8")
        for needle in entry.get("needles") or ():
            if str(needle) not in text:
                drift.append(
                    {
                        "kind": "command-doc-needle-missing",
                        "artifact": artifact_id,
                        "doc": doc_rel,
                        "needle": needle,
                    }
                )
        doc_epoch = _git_last_commit_epoch(root, doc_rel)
        code_paths = [str(p) for p in entry.get("code") or () if (root / str(p)).is_file()]
        code_epochs = [e for p in code_paths if (e := _git_last_commit_epoch(root, p)) is not None]
        if doc_epoch is not None and code_epochs and doc_epoch < max(code_epochs):
            drift.append(
                {
                    "kind": "command-doc-stale",
                    "artifact": artifact_id,
                    "doc": doc_rel,
                    "docCommitEpoch": doc_epoch,
                    "codePaths": code_paths,
                    "maxCodeCommitEpoch": max(code_epochs),
                }
            )
    return drift


def _parse_run_id(argv: list[str]) -> tuple[str | None, list[str]]:
    cleaned: list[str] = []
    run_id: str | None = None
    idx = 0
    while idx < len(argv):
        token = argv[idx]
        if token == "--run-id" and idx + 1 < len(argv):
            run_id = argv[idx + 1]
            idx += 2
            continue
        cleaned.append(token)
        idx += 1
    return run_id, cleaned


def resolve_plan_path(
    root: Path,
    state: dict[str, object],
    explicit_plan: Path | None = None,
    *,
    run_id: str | None = None,
) -> Path:
    """Resolve the deliver plan through the run helper when a run id is available (R18)."""
    from wave_run_paths import global_plan_path, is_repository_global_plan_path, plan_path as run_plan_path
    from wave_run_plan import resolve_run_id

    active_run_id = run_id or state.get("runId")
    if active_run_id:
        return run_plan_path(root, resolve_run_id({**state, "runId": active_run_id}))

    if state.get("planHash") and state.get("runId"):
        return run_plan_path(root, resolve_run_id(state))

    if explicit_plan is not None:
        resolved = explicit_plan.resolve()
        if is_repository_global_plan_path(root, resolved):
            return resolved
        return resolved

    return global_plan_path(root)


def _resolve_argv(argv: list[str]) -> list[str]:
    if len(argv) >= 3 and argv[1] == "--state-root":
        import sys as _sys

        _sys.stderr.write(
            "DEPRECATION: docs-currency-gate.py --state-root is deprecated; "
            "use four positional args (repo_root state_root state.json plan.json) or --run-id\n"
        )
        state_root = Path(argv[2])
        state_path = state_root / ".cursor" / "sw-deliver-state.json"
        if not state_path.is_file():
            matches = sorted((state_root / ".cursor").glob("sw-deliver-state.*.json"))
            state_path = matches[0] if len(matches) == 1 else state_path
        state: dict[str, object] = {}
        if state_path.is_file():
            try:
                loaded = json.loads(state_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    state = loaded
            except json.JSONDecodeError:
                state = {}
        plan_path = resolve_plan_path(state_root, state)
        return [argv[0], str(state_root), str(state_root), str(state_path), str(plan_path)]
    return argv


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(argv if argv is not None else sys.argv)
    run_id, stripped = _parse_run_id(raw_argv)
    resolved = _resolve_argv(stripped)
    root = Path(resolved[1])
    state_root = Path(resolved[2])
    state = json.loads(Path(resolved[3]).read_text())
    explicit_plan = Path(resolved[4]) if len(resolved) > 4 else None
    plan_file = resolve_plan_path(root, state, explicit_plan, run_id=run_id)
    plan = json.loads(plan_file.read_text(encoding="utf-8")) if plan_file.is_file() else {}

    prd = str(state.get("prd_number") or plan.get("prd_number") or "").zfill(3)
    if not prd or prd == "000":
        print(json.dumps({"verdict": "fail", "error": "prd_number missing"}))
        sys.exit(2)

    phases = state.get("phases") or {}
    from wave_living_docs import (
        derive_index_status,
        living_doc_write_banned,
        read_completion_evidence,
        read_index_status_evidence,
    )
    from wave_state import phase_complete

    all_green = bool(phases) and all(phase_complete((m or {}).get("status")) for m in phases.values())
    merged_main = False
    try:
        import subprocess

        proc = subprocess.run(
            [sys.executable, str(root / "scripts" / "wave_compound.py"), str(state_root), "completion", "check-merge"],
            cwd=str(state_root),
            text=True,
            capture_output=True,
        )
        if proc.returncode == 0:
            merged_main = bool(json.loads(proc.stdout).get("merged"))
    except Exception:
        pass

    expected = derive_index_status(state, merged_main)
    slug = str(
        (state.get("target") or {}).get("slug")
        or plan.get("slug")
        or ""
    ).strip() or None

    def _index_status_from_file() -> str | None:
        index_path = root / "docs" / "prds" / "INDEX.md"
        if not index_path.is_file():
            return None
        for line in index_path.read_text(encoding="utf-8").splitlines():
            if not line.startswith("|") or line.startswith("| #") or line.startswith("|---"):
                continue
            parts = [p.strip() for p in line.strip("|").split("|")]
            if len(parts) >= 4 and parts[0].zfill(3) == prd:
                return parts[4] if len(parts) >= 5 else parts[3]
        return None

    def _completion_in_log() -> bool:
        log_path = root / "docs" / "prds" / "COMPLETION-LOG.md"
        if not log_path.is_file():
            return False
        log_text = log_path.read_text(encoding="utf-8")
        return f"| {prd.lstrip('0')} |" in log_text or f"| {prd} |" in log_text

    banned = living_doc_write_banned(root)
    slug = str((state.get("target") or {}).get("slug") or "")
    file_row_status = _index_status_from_file()
    index_status = None
    if banned:
        ev = read_index_status_evidence(root, prd, slug=slug)
        if ev:
            index_status = str(ev.get("status") or "")
        else:
            index_status = file_row_status
    else:
        index_status = file_row_status

    # When issue projection lags but tracked INDEX + deliver state say complete, reconcile (R4).
    if (
        banned
        and all_green
        and expected == "complete"
        and index_status not in (None, expected)
        and file_row_status == expected
    ):
        index_status = file_row_status

    drift = []
    if index_status is None:
        drift.append({"kind": "index-missing-row", "prd": prd})
    elif index_status != expected:
        drift.append({"kind": "index-status", "prd": prd, "expected": expected, "actual": index_status})

    # COMPLETION-LOG / store completion events
    if all_green:
        has_completion = read_completion_evidence(root, prd) is not None if banned else False
        if banned and not has_completion:
            has_completion = _completion_in_log()
        elif not banned:
            has_completion = _completion_in_log()
        if not has_completion:
            drift.append({"kind": "completion-log-missing", "prd": prd})

    # GAP-BACKLOG: unresolved rows for this PRD when it is complete (R3 / PRD 048)
    gap_path = root / "docs" / "prds" / "GAP-BACKLOG.md"
    if expected == "complete" and not banned and gap_path.is_file():
        from gap_backlog import parse_gap_backlog

        backlog = parse_gap_backlog(gap_path.read_text(encoding="utf-8"))
        prd_n = str(int(prd)) if prd.isdigit() else prd.lstrip("0") or prd
        sched_re = re.compile(
            rf"^PRD\s+0*{re.escape(str(int(prd_n))) if prd_n.isdigit() else re.escape(prd_n)}(?:\s+A\d+)?$",
            re.I,
        )
        for row in backlog.rows:
            st = row.status.lower()
            if st == "open" or (st == "scheduled" and sched_re.match(row.schedule.strip())):
                drift.append({"kind": "gap-still-open", "prd": prd, "row": row.gap_id})

    # GAP-BACKLOG index/table integrity (R54) — skip read-only separate-project shim (R4 / PRD 062)
    import subprocess

    try:
        from planning_migrate_issue_store import gap_backlog_is_readonly
    except ImportError:
        gap_backlog_is_readonly = None  # type: ignore[assignment,misc]

    gap_backlog_readonly = (
        gap_backlog_is_readonly(root) if gap_backlog_is_readonly is not None else False
    )
    if not gap_backlog_readonly:
        gb = subprocess.run(
            [sys.executable, str(root / "scripts" / "gap_backlog.py"), "--root", str(root), "check"],
            text=True,
            capture_output=True,
        )
        if gb.returncode != 0:
            try:
                payload = json.loads(gb.stdout or gb.stderr)
            except json.JSONDecodeError:
                payload = {"error": gb.stderr or gb.stdout}
            drift.append({"kind": "gap-backlog-integrity", "detail": payload})

    from docs_currency_081 import check_release_guide_artifacts

    guide_drift = check_release_guide_artifacts(root)
    if guide_drift:
        drift.extend(guide_drift)

    if drift:
        print(json.dumps({"verdict": "fail", "action": "docs-currency-gate", "prd": prd, "drift": drift}))
        sys.exit(1)

    command_doc_drift = check_command_documentation_currency(root)
    if command_doc_drift:
        print(
            json.dumps(
                {
                    "verdict": "fail",
                    "action": "docs-currency-gate",
                    "prd": prd,
                    "drift": command_doc_drift,
                    "artifactSet": [str(e.get("id") or e.get("doc")) for e in COMMAND_DOC_CURRENCY_ARTIFACTS],
                }
            )
        )
        sys.exit(1)

    print(
        json.dumps(
            {
                "verdict": "pass",
                "action": "docs-currency-gate",
                "prd": prd,
                "indexStatus": index_status,
                "expected": expected,
                "planPath": str(plan_file),
                "artifactSet": [str(e.get("id") or e.get("doc")) for e in COMMAND_DOC_CURRENCY_ARTIFACTS],
            }
        )
    )
    return 0


if __name__ == "__main__":
    run_module_main(main)
