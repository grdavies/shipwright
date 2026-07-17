#!/usr/bin/env python3
"""Single-sourced planning-unit lifecycle enum and transition classification (PRD 033 R1/R2/R23).

Replaces PRD 031's values-only stub at the same import surface. Transition semantics are data tables
consumed by the reconciler and scheduler — behavior lives in planning_graph / reconciler modules.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Final, Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

GAP_STATUSES: frozenset[str] = frozenset(
    {
        "open",
        "planned",
        "partially resolved",
        "resolved",
    }
)

LIFECYCLE_STATUSES: frozenset[str] = frozenset(
    {
        "proposed",
        "planned",
        "in-progress",
        "complete",
        "superseded",
        "cancelled",
        "deferred",
        "blocked",
    }
)

GAP_TYPE: Final[str] = "gap"
LIFECYCLE_TYPES: frozenset[str] = frozenset({"brainstorm", "prd", "decision", "amendment"})

PLANNED_HOMONYM_NOTE: Final[str] = (
    "planned is a homonym: gap units use planned (scheduled for work); "
    "lifecycle units use planned (accepted but not started / frozen)."
)

# R2 — transition classification (data only; reconciler never invents in-progress without deliver evidence).
MECHANICAL_DERIVED_STATUSES: frozenset[str] = frozenset({"in-progress", "complete", "blocked"})
FREEZE_GATE: tuple[str, str] = ("proposed", "planned")
HUMAN_GATED_STATUSES: frozenset[str] = frozenset({"superseded", "cancelled", "deferred"})

TRANSITION_CLASSIFICATION: dict[str, str] = {
    "in-progress": "mechanical",
    "complete": "mechanical",
    "blocked": "mechanical",
    "proposed->planned": "freeze-gate",
    "superseded": "human-gated",
    "cancelled": "human-gated",
    "deferred": "human-gated",
}


def allowed_statuses(unit_type: str) -> frozenset[str]:
    if unit_type == GAP_TYPE:
        return GAP_STATUSES
    if unit_type in LIFECYCLE_TYPES:
        return LIFECYCLE_STATUSES
    return frozenset()


def is_cross_enum_token(unit_type: str, status: str) -> bool:
    """True when status belongs exclusively to the other enum (not homonyms like planned)."""
    if unit_type == GAP_TYPE:
        return status in LIFECYCLE_STATUSES and status not in GAP_STATUSES
    if unit_type in LIFECYCLE_TYPES:
        return status in GAP_STATUSES and status not in LIFECYCLE_STATUSES
    return False


def validate_status(unit_type: str, status: str) -> str | None:
    """Closed-world status validation; rejects unknown tokens."""
    allowed = allowed_statuses(unit_type)
    if not allowed:
        return f"unknown unit type: {unit_type!r}"
    if is_cross_enum_token(unit_type, status):
        return f"cross-enum status {status!r} for type {unit_type!r}"
    if status not in allowed:
        return f"unknown status {status!r} for type {unit_type!r}"
    return None


def transition_kind(from_status: str, to_status: str) -> str | None:
    """Classify a transition edge for reconciler policy lookup."""
    if from_status == "proposed" and to_status == "planned":
        return TRANSITION_CLASSIFICATION["proposed->planned"]
    if to_status in MECHANICAL_DERIVED_STATUSES:
        return TRANSITION_CLASSIFICATION.get(to_status)
    if to_status in HUMAN_GATED_STATUSES:
        return TRANSITION_CLASSIFICATION.get(to_status)
    return None


def is_mechanical_status(status: str) -> bool:
    return status in MECHANICAL_DERIVED_STATUSES


def is_human_gated_status(status: str) -> bool:
    return status in HUMAN_GATED_STATUSES

def gap_absorption_target(absorber_derived: str, gap_status: str) -> str:
    """R11 — mechanical gap progression when an absorbing unit advances."""
    if absorber_derived == "complete":
        return "resolved"
    if absorber_derived == "in-progress":
        if gap_status == "resolved":
            return gap_status
        return "partially resolved"
    if absorber_derived == "planned" and gap_status == "open":
        return "planned"
    return gap_status


# PRD 071 R8/R9 — MemPalace PRD 010 cancel + number-slot retirement (not superseded-by-071).
PRD_010_NUMBER: Final[str] = "010"
PRD_010_PRD_UNIT_ID: Final[str] = "010-prd-mempalace-memory-provider"
PRD_010_TASKS_UNIT_ID: Final[str] = "tasks-010-mempalace-memory-provider"
PRD_071_UNIT_ID: Final[str] = "071-prd-pluggable-memory-adapter-framework"
PRD_071_NUMBER: Final[str] = "071"
PRD_010_PLANNING_ISSUE_NUMBERS: tuple[int, ...] = (139, 140)
PRD_010_CANCEL_RATIONALE: Final[str] = (
    "Cancelled for foundation PRD 071 (pluggable memory adapter framework); "
    "MemPalace will be re-authored on a new PRD number after 071 completes."
)
RESERVED_PRD_NUMBER_SLOTS: frozenset[int] = frozenset({10})

_PRD_NUMBER_RE = re.compile(r"^(?:prd-)?(\d{3})-")


def prd_number_from_unit_id(unit_id: str) -> int | None:
    """Extract a three-digit PRD number from canonical unit ids."""
    unit = unit_id.strip()
    if unit.startswith("tasks-"):
        unit = unit[len("tasks-") :]
    m = _PRD_NUMBER_RE.match(unit)
    if m:
        return int(m.group(1))
    m = re.match(r"^(\d{3})$", unit)
    if m:
        return int(m.group(1))
    return None


def collect_occupied_prd_numbers(unit_ids: Iterable[str]) -> set[int]:
    occupied: set[int] = set()
    for unit_id in unit_ids:
        number = prd_number_from_unit_id(unit_id)
        if number is not None:
            occupied.add(number)
    return occupied


def next_free_prd_number(
    occupied: set[int],
    *,
    reserved: frozenset[int] | None = None,
) -> int:
    """Return the next allocatable PRD display number (R9 — never reuses reserved slots)."""
    reserved_slots = reserved if reserved is not None else RESERVED_PRD_NUMBER_SLOTS
    floor = max(occupied | reserved_slots, default=0) + 1
    candidate = floor
    while candidate in reserved_slots:
        candidate += 1
    return candidate


def _parse_depends_list(raw: str) -> list[str]:
    import planning_store as ps

    return ps._parse_absorbs_targets(raw or "")


def _depends_aliases_for_foundation(foundation_unit_id: str, foundation_number: str) -> set[str]:
    aliases = {
        foundation_unit_id,
        foundation_number,
        f"prd-{foundation_number}",
        f"{foundation_number}-prd",
    }
    slug = foundation_unit_id
    if foundation_unit_id.startswith(f"{foundation_number}-prd-"):
        slug = foundation_unit_id[len(f"{foundation_number}-prd-") :]
        aliases.add(f"tasks-{foundation_number}-{slug}")
    return {item.lower() for item in aliases if item}


def depends_includes_foundation(depends_raw: str, foundation_unit_id: str, foundation_number: str) -> bool:
    aliases = _depends_aliases_for_foundation(foundation_unit_id, foundation_number)
    return any(item.lower() in aliases for item in _parse_depends_list(depends_raw))


def _supersedes_points_at_foundation(supersedes_raw: str, foundation_unit_id: str, foundation_number: str) -> bool:
    aliases = _depends_aliases_for_foundation(foundation_unit_id, foundation_number)
    return any(item.lower() in aliases for item in _parse_depends_list(supersedes_raw))


def apply_cancel_with_depends(
    content: str,
    *,
    depends_target: str,
    rationale: str | None = None,
) -> tuple[str, bool]:
    """Human-gated cancel transition with depends-on/prerequisite edge (not supersede)."""
    from gap_backlog import update_frontmatter_field
    from planning_migrate_issue_store import parse_frontmatter_fields

    fm = parse_frontmatter_fields(content)
    unit_type = str(fm.get("type") or "prd")
    current_status = str(fm.get("status") or "").strip().lower()
    depends = _parse_depends_list(fm.get("depends", ""))
    supersedes = _parse_depends_list(fm.get("supersedes", ""))
    foundation_number = prd_number_from_unit_id(depends_target)
    foundation_number_str = f"{foundation_number:03d}" if foundation_number is not None else PRD_071_NUMBER

    already_cancelled = current_status == "cancelled"
    has_depends = depends_target in depends or depends_includes_foundation(
        fm.get("depends", ""),
        depends_target,
        foundation_number_str,
    )
    if _supersedes_points_at_foundation(fm.get("supersedes", ""), depends_target, foundation_number_str):
        raise ValueError("cancelled unit must not supersede foundation PRD")

    if already_cancelled and has_depends:
        return content, False

    err = validate_status(unit_type if unit_type in LIFECYCLE_TYPES else "prd", "cancelled")
    if err:
        raise ValueError(err)

    updated = content
    changed = False
    if current_status != "cancelled":
        updated = update_frontmatter_field(updated, "status", "cancelled")
        changed = True
    if depends_target not in depends:
        depends.append(depends_target)
        updated = update_frontmatter_field(updated, "depends", "[" + ", ".join(depends) + "]")
        changed = True
    if supersedes:
        remaining = [item for item in supersedes if item.lower() not in _depends_aliases_for_foundation(depends_target, foundation_number_str)]
        if len(remaining) != len(supersedes):
            value = "[" + ", ".join(remaining) + "]" if remaining else ""
            updated = update_frontmatter_field(updated, "supersedes", value)
            changed = True
    if rationale and rationale not in updated:
        note = f"\n\n<!-- cancel-rationale: {rationale} -->\n"
        if note.strip() not in updated:
            updated = updated.rstrip() + note
            changed = True
    return updated, changed


def _list_planning_unit_ids(root: Path, cfg: dict[str, Any]) -> list[str]:
    from planning_migrate_issue_store import issue_store_effective

    if not issue_store_effective(root, cfg):
        return []
    import planning_store as ps

    backend = ps.get_backend(root, cfg, override="issue-store")
    client = getattr(backend, "_client", None)
    search = getattr(client, "issue_search", None)
    if not callable(search):
        return []
    project_key = getattr(backend, "project_key", "")
    records = search(project_key=project_key)
    unit_ids: list[str] = []
    for record in records:
        unit_id = str(getattr(record, "unit_id", "") or "").strip()
        if unit_id:
            unit_ids.append(unit_id)
    return unit_ids


def cancel_prd_010_for_071_foundation(
    root: Path,
    cfg: dict[str, Any] | None = None,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Cancel MemPalace PRD 010 + tasks with depends-on → 071 (PRD 071 R8)."""
    import planning_store as ps
    from planning_migrate_issue_store import issue_store_effective

    root = ps.git_root(root)
    cfg = cfg or ps.load_workflow_config(root)
    if not issue_store_effective(root, cfg):
        return {
            "verdict": "skipped",
            "action": "cancel-prd-010-for-071",
            "reason": "not-issue-store",
        }

    backend = ps.get_backend(root, cfg, override="issue-store")
    targets = (
        (PRD_010_PRD_UNIT_ID, "prd"),
        (PRD_010_TASKS_UNIT_ID, "tasks"),
    )
    updates: dict[str, Any] = {}
    for unit_id, artifact_type in targets:
        body_path = ps._default_body_path(unit_id, artifact_type)
        fetched = backend.get(unit_id, body_path)
        if fetched.verdict != "ok" or not fetched.content:
            return {
                "verdict": "fail",
                "action": "cancel-prd-010-for-071",
                "error": "unit-missing",
                "unitId": unit_id,
            }
        try:
            updated, changed = apply_cancel_with_depends(
                fetched.content,
                depends_target=PRD_071_UNIT_ID,
                rationale=PRD_010_CANCEL_RATIONALE,
            )
        except ValueError as exc:
            return {
                "verdict": "fail",
                "action": "cancel-prd-010-for-071",
                "error": str(exc),
                "unitId": unit_id,
            }
        updates[unit_id] = {"changed": changed, "bodyPath": body_path}
        if changed and not dry_run:
            put_result = backend.put(unit_id, body_path, updated)
            if put_result.verdict != "ok":
                return {
                    "verdict": "fail",
                    "action": "cancel-prd-010-for-071",
                    "error": "put-failed",
                    "unitId": unit_id,
                    "put": put_result.__dict__,
                }

    return {
        "verdict": "ok",
        "action": "cancel-prd-010-for-071",
        "dryRun": dry_run,
        "foundationUnitId": PRD_071_UNIT_ID,
        "unitIds": [unit_id for unit_id, _ in targets],
        "planningIssues": list(PRD_010_PLANNING_ISSUE_NUMBERS),
        "updates": updates,
    }


def verify_prd_010_cancel_for_071(root: Path, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Verify PRD 010 cancel semantics + next-free MemPalace number (PRD 071 R8/R9)."""
    import planning_store as ps
    from planning_migrate_issue_store import issue_store_effective, parse_frontmatter_fields

    root = ps.git_root(root)
    cfg = cfg or ps.load_workflow_config(root)
    if not issue_store_effective(root, cfg):
        return {
            "verdict": "skipped",
            "action": "verify-prd-010-cancel-for-071",
            "reason": "not-issue-store",
        }

    backend = ps.get_backend(root, cfg, override="issue-store")
    client = getattr(backend, "_client", None)
    search = getattr(client, "issue_search", None)
    issue_numbers_present: set[int] = set()
    if callable(search):
        project_key = getattr(backend, "project_key", "")
        for record in search(project_key=project_key):
            number = int(getattr(record, "number", 0) or 0)
            if number:
                issue_numbers_present.add(number)
    missing_issues = [
        issue_number
        for issue_number in PRD_010_PLANNING_ISSUE_NUMBERS
        if issue_number not in issue_numbers_present
    ]

    checks: list[dict[str, str]] = []
    ok = True
    for unit_id, artifact_type in (
        (PRD_010_PRD_UNIT_ID, "prd"),
        (PRD_010_TASKS_UNIT_ID, "tasks"),
    ):
        body_path = ps._default_body_path(unit_id, artifact_type)
        fetched = backend.get(unit_id, body_path)
        if fetched.verdict != "ok" or not fetched.content:
            checks.append({"unitId": unit_id, "check": "present", "status": "fail"})
            ok = False
            continue
        fm = parse_frontmatter_fields(fetched.content)
        status = str(fm.get("status") or "").strip().lower()
        if status != "cancelled":
            checks.append({"unitId": unit_id, "check": "status-cancelled", "status": "fail"})
            ok = False
        else:
            checks.append({"unitId": unit_id, "check": "status-cancelled", "status": "ok"})
        if not depends_includes_foundation(fm.get("depends", ""), PRD_071_UNIT_ID, PRD_071_NUMBER):
            checks.append({"unitId": unit_id, "check": "depends-on-071", "status": "fail"})
            ok = False
        else:
            checks.append({"unitId": unit_id, "check": "depends-on-071", "status": "ok"})
        if _supersedes_points_at_foundation(fm.get("supersedes", ""), PRD_071_UNIT_ID, PRD_071_NUMBER):
            checks.append({"unitId": unit_id, "check": "not-superseded-by-071", "status": "fail"})
            ok = False
        else:
            checks.append({"unitId": unit_id, "check": "not-superseded-by-071", "status": "ok"})

    if missing_issues:
        checks.append({"check": "planning-issues-retained", "status": "fail", "missing": ",".join(map(str, missing_issues))})
        ok = False
    else:
        checks.append({"check": "planning-issues-retained", "status": "ok"})

    occupied = collect_occupied_prd_numbers(_list_planning_unit_ids(root, cfg))
    next_free = next_free_prd_number(occupied)
    if next_free == int(PRD_010_NUMBER):
        checks.append({"check": "next-free-not-010", "status": "fail"})
        ok = False
    else:
        checks.append({"check": "next-free-not-010", "status": "ok", "nextFree": str(next_free)})

    if int(PRD_010_NUMBER) not in RESERVED_PRD_NUMBER_SLOTS:
        checks.append({"check": "slot-010-reserved", "status": "fail"})
        ok = False
    else:
        checks.append({"check": "slot-010-reserved", "status": "ok"})

    return {
        "verdict": "ok" if ok else "fail",
        "action": "verify-prd-010-cancel-for-071",
        "checks": checks,
        "nextFreePrdNumber": next_free,
        "occupiedPrdNumbers": sorted(occupied),
    }


def mempalace_reauth_supersedes_target() -> str:
    """Canonical unit id that a future MemPalace PRD should supersede (cancelled 010)."""
    return PRD_010_PRD_UNIT_ID


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Planning lifecycle operations (PRD 033 / PRD 071 R8/R9).")
    sub = parser.add_subparsers(dest="command", required=True)

    cancel = sub.add_parser("cancel-prd-010-for-071", help="Cancel PRD 010 units with depends-on 071")
    cancel.add_argument("--root", default=".")
    cancel.add_argument("--dry-run", action="store_true")

    verify = sub.add_parser("verify-prd-010-cancel-for-071", help="Verify PRD 010 cancel close-out")
    verify.add_argument("--root", default=".")

    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    import planning_store as ps

    cfg = ps.load_workflow_config(root)
    if args.command == "cancel-prd-010-for-071":
        out = cancel_prd_010_for_071_foundation(root, cfg, dry_run=bool(args.dry_run))
    else:
        out = verify_prd_010_cancel_for_071(root, cfg)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("verdict") in ("ok", "skipped") else 20


if __name__ == "__main__":
    raise SystemExit(main())

