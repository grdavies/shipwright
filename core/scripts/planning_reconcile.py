#!/usr/bin/env python3
"""Deterministic maintenance reconciler for planning INDEX derived region (PRD 033 phase 2)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_graph as pg  # noqa: E402
import planning_index_gen as pig  # noqa: E402
import planning_index_issue as pii  # noqa: E402
import planning_legacy_projection as plp  # noqa: E402
import planning_visibility as pv  # noqa: E402
import planning_lifecycle as plc  # noqa: E402
import planning_paths as pp  # noqa: E402
from host_lib import load_workflow_config  # noqa: E402
from inflight_signal import InflightTuple, read_tuples  # noqa: E402
from planning_canonical import SCHEDULE_STALE_LABEL  # noqa: E402
from planning_migrate_issue_store import issue_store_separate_project  # noqa: E402
from wave_living_doc_lock import living_doc_write_lock  # noqa: E402

ARCHIVE_VIEW_STATUSES = frozenset({"complete", "superseded", "cancelled", "resolved"})
ACTIVE_VIEW_ALWAYS = frozenset({"deferred", "blocked"})
TERMINAL_MONOTONIC_STATUSES = frozenset({"complete", "superseded"})
RELIEF_ACCURACY_FLOOR = 0.95


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 20, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def has_flag(args: list[str], flag: str) -> bool:
    return flag in args


def current_branch(worktree: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def default_base_branch(root: Path) -> str:
    for candidate in (root / ".cursor/workflow.config.json", root / "workflow.config.json"):
        if candidate.is_file():
            try:
                cfg = json.loads(candidate.read_text(encoding="utf-8"))
                return str(cfg.get("defaultBaseBranch") or "main")
            except json.JSONDecodeError:
                pass
    return "main"


def is_ancestor(worktree: Path, ancestor: str, descendant: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(worktree), "merge-base", "--is-ancestor", ancestor, descendant],
        capture_output=True,
    )
    return proc.returncode == 0


def git_complete_unit_ids(root: Path, units: list[pg.GraphUnit]) -> set[str]:
    worktree = pp.git_root(root)
    base_sha = ""
    for candidate in (default_base_branch(root), "main", "master"):
        base_ref = subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", candidate],
            capture_output=True,
            text=True,
        )
        if base_ref.returncode == 0:
            base_sha = base_ref.stdout.strip()
            break
    if not base_sha:
        return set()
    complete: set[str] = set()
    for unit in units:
        if unit.unit_type != "prd":
            continue
        m = re.match(r"prd-\d+-(.+)", unit.id)
        if not m:
            continue
        slug = m.group(1)
        for prefix in ("feat", "fix", "docs", "chore"):
            branch = f"{prefix}/{slug}"
            tip = subprocess.run(
                ["git", "-C", str(worktree), "rev-parse", branch],
                capture_output=True,
                text=True,
            )
            if tip.returncode == 0 and is_ancestor(worktree, tip.stdout.strip(), base_sha):
                complete.add(unit.id)
                break
    return complete


def host_pr_complete_unit_ids(root: Path, units: list[pg.GraphUnit]) -> set[str]:
    """Host PR merge metadata corroborates git-primary complete (R29)."""
    worktree = pp.git_root(root)
    host_py = worktree / "scripts" / "host.py"
    if not host_py.is_file():
        return set()
    proc = subprocess.run(
        [sys.executable, str(host_py), "--root", str(worktree), "pr-list", "--state", "closed", "--limit", "100"],
        cwd=str(worktree),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return set()
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return set()
    prs = payload.get("data") if payload.get("verdict") == "ok" else []
    if not isinstance(prs, list):
        return set()
    complete: set[str] = set()
    for unit in units:
        if unit.unit_type != "prd":
            continue
        m = re.match(r"prd-\d+-(.+)", unit.id)
        if not m:
            continue
        slug = m.group(1)
        slug_esc = re.escape(slug)
        integration_pat = re.compile(
            rf"^(?:feat|fix|perf|revert|docs|chore|refactor|test)/{slug_esc}$",
            re.IGNORECASE,
        )
        for pr in prs:
            head = str(pr.get("headRefName") or "")
            if integration_pat.match(head) and pr.get("mergedAt"):
                complete.add(unit.id)
                break
    return complete


def resolve_git_complete_unit_ids(root: Path, units: list[pg.GraphUnit]) -> set[str]:
    return git_complete_unit_ids(root, units) | host_pr_complete_unit_ids(root, units)


def read_prior_derived_map(root: Path) -> dict[str, str]:
    index_path = pig.index_path(root)
    if not index_path.is_file():
        return {}
    regions = pig.parse_regions(index_path.read_text(encoding="utf-8"))
    return pig.parse_derived_status_map(regions.derived)


def parse_override_status(args: list[str]) -> dict[str, str] | None:
    if "--override-status" not in args:
        return None
    idx = args.index("--override-status")
    if idx + 3 >= len(args):
        fail("--override-status requires <unit-id> <from-status> <to-status> --reason <text>")
    reason_idx = args.index("--reason") if "--reason" in args else -1
    if reason_idx < 0 or reason_idx + 1 >= len(args):
        fail("--override-status requires --reason <text>")
    return {
        "unit": args[idx + 1],
        "from": args[idx + 2],
        "to": args[idx + 3],
        "reason": args[reason_idx + 1],
    }


def apply_monotonic_terminal(
    prior: dict[str, str],
    proposed: dict[str, str],
    override: dict[str, str] | None,
) -> dict[str, str]:
    """Terminal derived rows never downgrade without explicit override (R30)."""
    merged = dict(proposed)
    if override:
        uid = override["unit"]
        if prior.get(uid) == override["from"] and merged.get(uid) == override["to"]:
            return merged
    for uid, prior_status in prior.items():
        if prior_status not in TERMINAL_MONOTONIC_STATUSES:
            continue
        new_status = merged.get(uid, prior_status)
        if new_status == prior_status:
            continue
        if override and uid == override["unit"]:
            continue
        merged[uid] = prior_status
    return merged


def derive_status(
    unit: pg.GraphUnit,
    by_id: dict[str, pg.GraphUnit],
    inflight: dict[str, InflightTuple],
    git_complete: set[str],
) -> str:
    if unit.unit_type == plc.GAP_TYPE:
        return unit.status

    if unit.id in git_complete:
        return "complete"

    if unit.id in inflight:
        return "in-progress"

    if pg.derive_blocked(unit, by_id):
        return "blocked"

    return unit.status


def build_base_derived_map(
    units: list[pg.GraphUnit],
    inflight: dict[str, InflightTuple],
    git_complete: set[str],
) -> dict[str, str]:
    by_id = pg.index_units(units)
    return {u.id: derive_status(u, by_id, inflight, git_complete) for u in units if u.id}


def build_derived_map(
    units: list[pg.GraphUnit],
    inflight: dict[str, InflightTuple],
    git_complete: set[str],
) -> dict[str, str]:
    base = build_base_derived_map(units, inflight, git_complete)
    return pg.apply_edge_effects(units, base).derived


def edge_effects_for_units(
    units: list[pg.GraphUnit],
    inflight: dict[str, InflightTuple],
    git_complete: set[str],
) -> pg.EdgeEffects:
    base = build_base_derived_map(units, inflight, git_complete)
    return pg.apply_edge_effects(units, base)


def render_derived_body(status_map: dict[str, str], *, active_only: bool = False) -> str:
    lines: list[str] = []
    for unit_id in sorted(status_map):
        status = status_map[unit_id]
        if active_only and status in ARCHIVE_VIEW_STATUSES and status not in ACTIVE_VIEW_ALWAYS:
            continue
        lines.append(f"{unit_id}: {status}")
    return "\n".join(lines) + ("\n" if lines else "")


def archive_index_path(root: Path) -> Path:
    dirs = pp.load_planning_dirs(root)
    worktree = pp.git_root(root)
    return worktree / dirs.prds / "INDEX-archive.md"


def render_archive_markdown(root: Path, units: list[pg.GraphUnit], status_map: dict[str, str]) -> str:
    pig_units = {u.id: u for u in pig.discover_units(root)}
    lines = [
        "# Planning INDEX — archived units",
        "",
        "_Generated by planning-graph reconcile (PRD 033 R14; PRD 034 R4 redaction)._",
        "",
        "| id | type | title | derived status | visibility |",
        "| --- | --- | --- | --- | --- |",
    ]
    unit_by_id = {u.id: u for u in units}
    for unit_id in sorted(status_map):
        status = status_map[unit_id]
        if status not in ARCHIVE_VIEW_STATUSES:
            continue
        unit = unit_by_id.get(unit_id)
        if not unit:
            continue
        du = pig_units.get(unit_id)
        title = du.title.replace("|", "\\|") if du else unit_id
        lines.append(f"| {unit_id} | {unit.unit_type} | {title} | {status} |")
    lines.append("")
    return "\n".join(lines)


def render_superseded_manifest(
    units: list[pg.GraphUnit],
    status_map: dict[str, str],
    effects: pg.EdgeEffects | None = None,
) -> str:
    effects = effects or pg.apply_edge_effects(units, status_map)
    superseded_by: dict[str, str] = {}
    for target_id, by_id in effects.supersede_edges:
        superseded_by.setdefault(target_id, by_id)
    lines = [
        "# Superseded planning units",
        "",
        "_Generated manifest (PRD 033 R10/R21)._",
        "",
        "| id | status | superseded_by |",
        "| --- | --- | --- |",
    ]
    for unit_id in sorted(status_map):
        if status_map[unit_id] == "superseded":
            lines.append(f"| {unit_id} | superseded | {superseded_by.get(unit_id, '')} |")
    if effects.extend_edges:
        lines.extend(["", "## Extends lineage", "", "| target | extended_by |", "| --- | --- |"])
        for target_id, by_id in effects.extend_edges:
            lines.append(f"| {target_id} | {by_id} |")
    lines.append("")
    return "\n".join(lines)


def load_deliver_phase_status(root: Path) -> dict[str, str]:
    worktree = pp.git_root(root)
    status: dict[str, str] = {}
    cursor = worktree / ".cursor"
    if not cursor.is_dir():
        return status
    for path in cursor.glob("sw-deliver-state*.json"):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for meta in (state.get("phases") or {}).values():
            if not isinstance(meta, dict):
                continue
            slug = str(meta.get("slug") or "")
            phase_status = str(meta.get("status") or "")
            if slug:
                status[slug] = phase_status
    return status


def relief_acceptance_check(root: Path, derived: dict[str, str]) -> dict[str, Any]:
    deliver = load_deliver_phase_status(root)
    mismatches: list[dict[str, str]] = []
    checked = 0
    for unit_id, derived_status in derived.items():
        phase_slug = unit_id.replace("prd-", "", 1) if unit_id.startswith("prd-") else unit_id
        if phase_slug not in deliver:
            continue
        checked += 1
        mapped = (
            "complete"
            if deliver[phase_slug]
            in ("green-merged", "teardown-complete", "teardown-pending", "merge-ready-green")
            else "in-progress"
        )
        if derived_status != mapped:
            mismatches.append({"unit": unit_id, "derived": derived_status, "deliver": mapped})
    accuracy = 1.0 if checked == 0 else (checked - len(mismatches)) / checked
    verdict = "pass" if not mismatches and accuracy >= RELIEF_ACCURACY_FLOOR else "fail"
    return {
        "verdict": verdict,
        "mismatches": mismatches,
        "checked": checked,
        "accuracy": round(accuracy, 4),
        "floor": RELIEF_ACCURACY_FLOOR,
    }


def dependency_dead_warnings(units: list[pg.GraphUnit]) -> list[dict[str, str]]:
    by_id = pg.index_units(units)
    warnings: list[dict[str, str]] = []
    for unit in units:
        if not pg.is_dependency_dead(unit, by_id):
            continue
        dead_deps = [
            dep_id
            for dep_id in unit.depends
            if dep_id in by_id and by_id[dep_id].status in pg.DEPENDENCY_DEAD_TARGET_STATUSES
        ]
        warnings.append(
            {
                "unit": unit.id,
                "cause": "dependency-dead",
                "deadDepends": ",".join(dead_deps),
                "hint": "retract or repoint depends edge (PRD 035 may auto-propose)",
            }
        )
    return warnings


_SCHEDULE_HINT_IGNORE_PREFIXES = ("deferred", "config:")


def _schedule_hint_target(schedule: str) -> str:
    """Normalize a `schedule:` hint (or decoded `sw:gap-schedule:*` label) to
    the absorber's numeric id prefix for comparison (PRD 057 R17).

    Accepts both the legacy `gap_backlog.schedule_label` form (``PRD 057`` /
    ``PRD 057 A1``) and the canonical `<NNN>-<slug>` unit-id form; an empty,
    placeholder (``—``/``-``), or policy-prefixed (``deferred``/``config:``)
    hint has no absorber to reconcile against and is skipped.
    """
    schedule = schedule.strip()
    if not schedule or schedule in {"—", "-"}:
        return ""
    if schedule.lower().startswith(_SCHEDULE_HINT_IGNORE_PREFIXES):
        return ""
    m = re.match(r"^PRD\s+0*(\d+)", schedule, re.I)
    if m:
        return m.group(1)
    m = re.match(r"^0*(\d+)-", schedule)
    if m:
        return m.group(1)
    return schedule


def _unit_number_prefix(unit_id: str) -> str:
    m = re.match(r"^0*(\d+)-", unit_id)
    return m.group(1) if m else ""


def schedule_stale_findings(units: Iterable[pg.GraphUnit]) -> list[dict[str, Any]]:
    """R17 -- flag gap units whose `schedule:` hint no longer matches an
    actual `absorbs` edge (gap-049).

    A gap's schedule hint names the absorber it expects to resolve it; the
    absorber's own `absorbs` edges are the ground truth. When the two
    disagree -- the hinted absorber doesn't currently absorb this gap, or no
    unit absorbs it at all -- surface `sw:schedule-stale` rather than trusting
    the (possibly rebased/renumbered) hint silently.
    """
    all_units = list(units)
    findings: list[dict[str, Any]] = []
    for unit in all_units:
        if unit.unit_type != "gap" or not unit.schedule:
            continue
        target = _schedule_hint_target(unit.schedule)
        if not target:
            continue
        absorbers = sorted(u.id for u in all_units if unit.id in u.absorbs)
        actual_targets = {_unit_number_prefix(a) for a in absorbers}
        if target in actual_targets:
            continue
        findings.append(
            {
                "unit": unit.id,
                "cause": "schedule-stale",
                "label": SCHEDULE_STALE_LABEL,
                "scheduleHint": unit.schedule,
                "actualAbsorbers": absorbers,
                "hint": "update the `schedule:` hint (or sw:gap-schedule:* label) to match the unit's actual absorbs edges",
            }
        )
    return findings


def reconcile_core(
    root: Path,
    *,
    dry_run: bool = False,
    before_serialize_hook: Callable[[], None] | None = None,
    override: dict[str, str] | None = None,
    force_legacy_projection: bool = False,
) -> dict[str, Any]:
    worktree = pp.git_root(root)
    cfg = load_workflow_config(worktree)
    # PRD 057 R3: separate-project issue-store never writes tracked derived
    # planning artifacts (INDEX.md / INDEX-archive.md / SUPERSEDED.md / legacy
    # projection); same-repo retains local writes unchanged (gap-041).
    separate_project = issue_store_separate_project(worktree, cfg)
    units = pg.discover_units(root)
    cycle = pg.detect_cycle(units)
    if cycle:
        fail("dependency cycle detected", cycle=cycle)

    prior_derived = read_prior_derived_map(root)
    git_complete = resolve_git_complete_unit_ids(root, units)

    index_path = pig.index_path(root)
    existing = ""
    inflight_bytes_before = ""
    if not separate_project:
        if not index_path.is_file():
            content_seed = pig.generate_index(root)
            if not dry_run:
                pig.write_index(root, content_seed, dry_run=False)
            existing = content_seed
        else:
            existing = index_path.read_text(encoding="utf-8")
        inflight_bytes_before = pig.parse_regions(existing).inFlight

    if before_serialize_hook:
        before_serialize_hook()

    if not separate_project and index_path.is_file():
        existing = index_path.read_text(encoding="utf-8")
    inflight_final = read_tuples(root)
    final_inflight_bytes = pig.parse_regions(existing).inFlight if existing else inflight_bytes_before
    effects = edge_effects_for_units(units, inflight_final, git_complete)
    derived = apply_monotonic_terminal(prior_derived, effects.derived, override)
    derived_body = render_derived_body(derived, active_only=True)

    store_projection: dict[str, Any] | None = None
    if separate_project:
        store_projection = pii.project_derived_map(worktree, derived, dry_run=dry_run)
    else:
        content = pig.read_merge_write(existing, writer="reconciler", new_region_body=derived_body)
        pig.write_index(root, content, dry_run=dry_run)

    archive_path = archive_index_path(root)
    if not separate_project:
        archive_content = render_archive_markdown(root, units, derived)
        if not dry_run:
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            archive_path.write_text(archive_content, encoding="utf-8")

    dirs = pp.load_planning_dirs(root)
    superseded_path = worktree / dirs.prds / "SUPERSEDED.md"
    if not separate_project and not dry_run:
        superseded_path.write_text(render_superseded_manifest(units, derived, effects), encoding="utf-8")

    if separate_project:
        legacy: dict[str, Any] = {
            "skipped": True,
            "reason": "separate-project-issue-store",
        }
    else:
        legacy = plp.project_all(root, dry_run=dry_run, force=force_legacy_projection)
    relief = relief_acceptance_check(root, derived)

    archived = [uid for uid, st in derived.items() if st in ARCHIVE_VIEW_STATUSES]
    result: dict[str, Any] = {
        "verdict": "pass",
        "action": "reconcile",
        "unitCount": len(units),
        "derivedCount": len(derived),
        "derived": derived,
        "archivedUnits": archived,
        "inflightPreserved": final_inflight_bytes == inflight_bytes_before,
        "archivePath": str(archive_path.relative_to(worktree)),
        "legacy": legacy,
        "relief": relief,
        "dependencyDead": dependency_dead_warnings(units),
        "scheduleStale": schedule_stale_findings(units),
    }
    if store_projection is not None:
        result["storeProjection"] = store_projection
    return result


def git_commit_reconcile(root: Path, *, dry_run: bool = False) -> str | None:
    if dry_run:
        return None
    worktree = pp.git_root(root)
    rel_index = pig.index_rel(root)
    dirs = pp.load_planning_dirs(root)
    paths = [rel_index, pp.join_rel(dirs.prds, "INDEX-archive.md"), pp.join_rel(dirs.prds, "SUPERSEDED.md")]
    env = {**os.environ, "SW_INDEX_REGION_WRITER": "reconciler"}
    subprocess.run(["git", "-C", str(worktree), "add", *paths], check=False, env=env)
    proc = subprocess.run(
        ["git", "-C", str(worktree), "status", "--porcelain"],
        capture_output=True,
        text=True,
    )
    if not proc.stdout.strip():
        return None
    commit = subprocess.run(
        ["git", "-C", str(worktree), "commit", "-m", "chore(planning): reconciler INDEX regen"],
        capture_output=True,
        text=True,
        env=env,
    )
    if commit.returncode != 0:
        fail(commit.stderr.strip() or "reconcile commit failed")
    sha = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return sha.stdout.strip()


def cmd_reconcile(root: Path, args: list[str]) -> None:
    if not pig.index_is_complete(root):
        fail("index-incomplete: reconciler refuses partial INDEX", exit_code=20)
    dry_run = has_flag(args, "--dry-run")
    do_commit = has_flag(args, "--commit")
    override = parse_override_status(args)
    worktree = pp.git_root(root)
    branch = current_branch(worktree)
    base = default_base_branch(root)
    allow_default = has_flag(args, "--allow-default-branch")
    if branch == base and not dry_run and not allow_default:
        fail(
            "reconcile refuses default branch commits (R31)",
            exit_code=20,
            branch=branch,
            remediation=(
                "single-unit post-merge: set-index-status + append-log-idempotent on a docs branch; "
                "full-corpus reconcile only on a non-default branch or via completion finalize-if-merged"
            ),
        )
    allow_log: dict[str, str] | None = None
    if allow_default and not dry_run:
        reason = ""
        if "--reason" in args:
            reason = args[args.index("--reason") + 1]
        allow_log = {
            "actor": os.environ.get("USER", "unknown"),
            "reason": reason or "unspecified",
        }

    with living_doc_write_lock(root, holder="planning-graph-reconcile"):
        result = reconcile_core(
            root,
            dry_run=dry_run,
            override=override,
            force_legacy_projection=has_flag(args, "--force"),
        )
        if allow_log:
            result["allowDefaultBranch"] = allow_log
        commit_sha = None
        if do_commit and not dry_run:
            commit_sha = git_commit_reconcile(root, dry_run=False)
        result["commit"] = commit_sha
        result["autoPr"] = False
        emit(result)


def cmd_doctor(root: Path, _args: list[str]) -> None:
    units = pg.discover_units(root)
    warnings = (
        dependency_dead_warnings(units)
        + plp.legacy_manual_edit_warnings(root)
        + schedule_stale_findings(units)
    )
    try:
        from planning_migrate_issue_store import diagnose_gap_projection_divergence

        divergences = diagnose_gap_projection_divergence(root)
    except ImportError:
        divergences = []
    if divergences:
        emit(
            {
                "verdict": "fail",
                "action": "planning-graph-doctor",
                "halt": "gap-projection-divergence",
                "issues": divergences,
                "warnings": warnings,
                "dependencyDeadCount": len(warnings),
                "remediation": "python3 scripts/planning_gap_capture.py refresh-projection <repo-root>",
            },
            exit_code=20,
        )
    emit(
        {
            "verdict": "pass",
            "action": "planning-graph-doctor",
            "warnings": warnings,
            "dependencyDeadCount": len(warnings),
            "scheduleStaleCount": len(schedule_stale_findings(units)),
        }
    )


def cmd_relief_check(root: Path, _args: list[str]) -> None:
    index_path = pig.index_path(root)
    if not index_path.is_file():
        fail("planning INDEX missing")
    regions = pig.parse_regions(index_path.read_text(encoding="utf-8"))
    derived = pig.parse_derived_status_map(regions.derived)
    relief = relief_acceptance_check(root, derived)
    if relief["verdict"] != "pass":
        emit(relief, exit_code=20)
    emit(relief)
