#!/usr/bin/env python3
"""Shared authoring-guard preflight for unit-writing commands (PRD 032 R5-R9/R14)."""
from __future__ import annotations

import getpass
import hashlib
import json
import re
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from inflight_signal import InflightTuple, is_run_live, read_tuples  # noqa: E402
import planning_index_gen as pig  # noqa: E402
import planning_paths as pp  # noqa: E402
from wave_json_io import read_json, write_json  # noqa: E402

HANDOFFS_REL = ".cursor/authoring-handoffs.json"
UNIT_ID_RE = re.compile(r"docs/prds/(\d+)-([^/]+)/")
PLANNING_UNIT_RE = re.compile(
    r"docs/planning/(brainstorm|gap|prd|decision|amendment)/([^/]+)/"
)
AMEND_ALLOWED_STATUSES = frozenset({"planned", "in-progress"})
CLOSED_LIFECYCLE_STATUSES = frozenset({"complete", "superseded", "cancelled", "deferred"})
LEGACY_UNIT_ID_RE = re.compile(r"^prd-(\d{3})-")
# Pre-031 cutover: legacy INDEX uses not-started; frozen-but-unshipped PRDs amend as planned.
LEGACY_INDEX_AMEND_STATUS = {"not-started": "planned"}

# PRD 366 (linear-markdown-equiv-222) extending-unit stance ledger (D1–D5).
PRD363_COMPLETE_PARENT_UNIT_ID = "363-prd-linear-markdown-equiv-221"
PRD366_EXTENDING_UNIT_ID = "366-prd-linear-markdown-equiv-222"
PRD366_BINDING_STANCE = "A"
PRD366_REJECTED_STANCES = frozenset({"B", "C", "D"})
PRD366_STANCE_SUMMARY: dict[str, str] = {
    "A": "dual-gate named-family allowlist continuation for leftover 2.22.0 reconstruct",
    "B": "witness unification only — required slice of A, not a substitute for leftover families",
    "C": "identity-only reconstruct-ok — rejected; dual-gate remains binding",
    "D": "parser-grade CommonMark/GFM AST compare — out of scope for this follow-up",
}
PRD366_IMMUTABLE_PATH_MARKERS = (
    "docs/prds/363-linear-markdown-equiv-221/",
    PRD363_COMPLETE_PARENT_UNIT_ID,
    "test_prd363_linear_markdown_equiv.py",
    "test_prd363_live_prove_after_package_install.py",
    "prd363_fixture_lib.py",
    "markdown-repro-2.21.0-family-map.json",
    "prd363-redacted-comparison-families.json",
)
PRD366_ALLOWED_MUTATION_MARKERS = (
    "366-linear-markdown-equiv-222",
    PRD366_EXTENDING_UNIT_ID,
    "test_prd366",
    "prd366_fixture_lib.py",
    "markdown-repro-2.22.0",
    "planning_linear_canonical.py",
    "planning/backends/issues_helpers.py",
    "authoring-guard.py",
    "authoring_guard.py",
    "canonical-serialization.md",
    "core/providers/issues/linear.md",
    "dist/",
)


def prd366_extending_unit_policy() -> dict[str, Any]:
    """Machine-readable PRD 366 extending-unit stance contract (phase 11 / D1–D5)."""
    return {
        "parentCompleteUnitId": PRD363_COMPLETE_PARENT_UNIT_ID,
        "extendingUnitId": PRD366_EXTENDING_UNIT_ID,
        "bindingStance": PRD366_BINDING_STANCE,
        "rejectedStances": sorted(PRD366_REJECTED_STANCES),
        "stanceSummary": dict(PRD366_STANCE_SUMMARY),
        "immutablePathMarkers": list(PRD366_IMMUTABLE_PATH_MARKERS),
        "allowedMutationMarkers": list(PRD366_ALLOWED_MUTATION_MARKERS),
        "method": "dual-gate-named-family-allowlist-continuation",
    }


def reject_prd366_stance_substitute(stance: str) -> dict[str, Any]:
    """Refuse stance B/C/D when proposed as the whole unit method (D2–D4)."""
    normalized = stance.strip().upper()
    if normalized == PRD366_BINDING_STANCE:
        return {"verdict": "pass", "stance": normalized, "binding": True}
    if normalized not in PRD366_REJECTED_STANCES:
        return {
            "verdict": "fail",
            "stance": normalized,
            "error": "unknown prd366 stance",
            "bindingStance": PRD366_BINDING_STANCE,
        }
    return {
        "verdict": "fail",
        "stance": normalized,
        "error": "prd366 stance rejected as unit substitute",
        "summary": PRD366_STANCE_SUMMARY[normalized],
        "bindingStance": PRD366_BINDING_STANCE,
        "requiredMethod": prd366_extending_unit_policy()["method"],
    }


def classify_prd366_mutation_path(rel_path: str) -> str:
    """Classify a repo-relative path for extending-unit mutation policy (R14/D5)."""
    norm = rel_path.replace("\\", "/")
    if any(marker in norm for marker in PRD366_IMMUTABLE_PATH_MARKERS):
        return "immutable-363"
    if any(marker in norm for marker in PRD366_ALLOWED_MUTATION_MARKERS):
        return "allowed-366"
    return "out-of-scope"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def actor_id() -> str:
    return f"{getpass.getuser()}@{socket.gethostname()}"


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 20, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, "halt": "authoring-guard", **extra}, exit_code)


def parse_kv(args: list[str], flag: str, default: str | None = None) -> str | None:
    if flag in args:
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else default
    return default


def unit_id_from_rel(rel: str) -> str | None:
    norm = rel.replace("\\", "/")
    match = PLANNING_UNIT_RE.search(norm)
    if match:
        return match.group(2)
    match = UNIT_ID_RE.search(norm)
    if not match:
        return None
    return f"prd-{match.group(1)}-{match.group(2)}"


def unit_folder_from_rel(rel: str) -> str | None:
    norm = rel.replace("\\", "/").rstrip("/")
    match = PLANNING_UNIT_RE.search(norm + "/")
    if match:
        return norm[: match.end()].rstrip("/")
    match = UNIT_ID_RE.search(norm + "/")
    if match:
        return norm[: match.end()].rstrip("/")
    return None


def resolve_unit_id(root: Path, args: list[str]) -> tuple[str, str | None]:
    unit = parse_kv(args, "--unit")
    artifact = parse_kv(args, "--path")
    if unit:
        return unit, artifact
    if artifact:
        try:
            rel = pp.rel_contained(root, artifact)
        except pp.PathEscapeError as exc:
            fail(str(exc))
        uid = unit_id_from_rel(rel)
        if not uid:
            fail(f"cannot resolve planning unit id from path: {rel}")
        return uid, rel
    fail("--unit or --path required")



def legacy_prd_index_status(root: Path, unit_id: str) -> str:
    """Read legacy docs/prds/INDEX.md Status for pre-planning-model units (PRD 032 R12)."""
    match = LEGACY_UNIT_ID_RE.match(unit_id)
    if not match:
        return ""
    prd_num = match.group(1)
    index_path = root / "docs" / "prds" / "INDEX.md"
    if not index_path.is_file():
        return ""
    for line in index_path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or line.startswith("| #") or line.startswith("|---"):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) >= 5 and parts[0] == prd_num:
            return parts[4]
    return ""


def legacy_prd_body_frozen(root: Path, unit_id: str) -> bool:
    match = LEGACY_UNIT_ID_RE.match(unit_id)
    if not match:
        return False
    prd_dir = root / "docs" / "prds"
    if not prd_dir.is_dir():
        return False
    prefix = f"{match.group(1)}-"
    for child in prd_dir.iterdir():
        if not child.is_dir() or not child.name.startswith(prefix):
            continue
        for md in child.glob("*-prd-*.md"):
            text = md.read_text(encoding="utf-8")
            if text.startswith("---") and "frozen: true" in text.split("---", 2)[1]:
                return True
    return False


def normalize_legacy_amend_status(index_status: str, *, frozen: bool) -> str:
    if frozen and index_status in LEGACY_INDEX_AMEND_STATUS:
        return LEGACY_INDEX_AMEND_STATUS[index_status]
    return index_status


def derived_region_populated(derived_body: str) -> bool:
    for line in derived_body.splitlines():
        line = line.strip()
        if not line or line.startswith("|") or line.startswith("-"):
            continue
        if ":" in line:
            return True
    return False


def reconcile_generation_token(root: Path, unit_id: str) -> dict[str, Any]:
    """Bind evaluation to derived+inFlight+structural snapshot (PRD 032 R9)."""
    index_path = pig.index_path(root)
    derived_body = ""
    inflight_body = ""
    if index_path.is_file():
        regions = pig.parse_regions(index_path.read_text(encoding="utf-8"))
        derived_body = regions.derived
        inflight_body = regions.inFlight

    units = {u.id: u for u in pig.discover_units(root)}
    unit = units.get(unit_id)
    structural_status = unit.status if unit else ""

    if derived_region_populated(derived_body):
        mode = "derived"
        consumer_status = (
            pig.resolve_consumer_status(unit, derived_body) if unit else ""
        )
    elif unit is None and LEGACY_UNIT_ID_RE.match(unit_id):
        legacy_status = legacy_prd_index_status(root, unit_id)
        mode = "legacy-index-degraded"
        consumer_status = normalize_legacy_amend_status(
            legacy_status, frozen=legacy_prd_body_frozen(root, unit_id)
        )
    else:
        mode = "structural-degraded"
        consumer_status = structural_status
        if unit and unit.type != "gap":
            tup = read_tuples(root).get(unit_id)
            if tup and is_run_live(root, tup.run_id):
                consumer_status = "in-progress"

    token_src = "\0".join(
        [derived_body, inflight_body, unit_id, structural_status, mode]
    )
    token = hashlib.sha256(token_src.encode("utf-8")).hexdigest()[:16]
    return {
        "token": token,
        "mode": mode,
        "consumerStatus": consumer_status,
        "unitId": unit_id,
        "structuralStatus": structural_status,
        "unitType": unit.type if unit else None,
    }


def unit_body_path(root: Path, unit_id: str) -> Path | None:
    """Resolve the canonical body path for a planning unit (planning model or legacy PRD)."""
    units = {u.id: u for u in pig.discover_units(root)}
    unit = units.get(unit_id)
    if unit:
        return root / unit.body_path
    match = LEGACY_UNIT_ID_RE.match(unit_id)
    if not match:
        return None
    prd_dir = root / "docs" / "prds"
    if not prd_dir.is_dir():
        return None
    prefix = f"{match.group(1)}-"
    for child in prd_dir.iterdir():
        if not child.is_dir() or not child.name.startswith(prefix):
            continue
        for md in child.glob("*-prd-*.md"):
            return md
    return None


def is_frozen_open_parent(root: Path, unit_id: str) -> bool:
    """True when parent body is frozen and lifecycle is not closed (PRD 339 R35)."""
    from check_frozen_lib import artifact_is_frozen

    body = unit_body_path(root, unit_id)
    if body is None or not body.is_file():
        return False
    return artifact_is_frozen(body)


def propose_complete_change_route(root: Path, unit_id: str) -> dict[str, Any]:
    """Route completed-unit change requests to a new unit or gap (PRD 032 R8)."""
    units = {u.id: u for u in pig.discover_units(root)}
    unit = units.get(unit_id)
    if not unit:
        fail(f"unit not found for route: {unit_id}")
    stamp = utc_now()[:10].replace("-", "")
    if unit.type == "gap":
        new_id = f"gap-{unit_id}-followup-{stamp}"
        return {
            "kind": "gap",
            "suggestedUnitId": new_id,
            "edges": {"depends": [unit_id]},
            "suggestedPath": f"docs/planning/gap/{new_id}/{new_id}.md",
            "message": (
                "Complete gap units cannot be amended in-place; "
                "file a follow-up gap unit."
            ),
        }
    new_id = f"{unit_id}-followup-{stamp}"
    return {
        "kind": "extending-unit",
        "suggestedUnitId": new_id,
        "edges": {"extends": [unit_id]},
        "suggestedPath": f"docs/planning/{unit.type}/{new_id}/{new_id}.md",
        "message": (
            "Complete units cannot be amended in-place; fork a new unit with "
            "extends:/supersedes: or append a gap unit."
        ),
    }


def amend_status_guard(root: Path, unit_id: str, artifact: str | None) -> None:
    """Enforce /sw-amend allowed statuses and route complete-unit requests (R7/R8/R35)."""
    info = reconcile_generation_token(root, unit_id)
    status = info["consumerStatus"]
    token = info["token"]
    body = unit_body_path(root, unit_id)
    frozen_open = is_frozen_open_parent(root, unit_id)

    if status == "complete":
        route = propose_complete_change_route(root, unit_id)
        emit(
            {
                "verdict": "pass",
                "action": "authoring-guard-amend",
                "outcome": "route",
                "unitId": unit_id,
                "artifact": artifact,
                "generationToken": token,
                "route": route,
            },
            exit_code=21,
        )

    if status in CLOSED_LIFECYCLE_STATUSES:
        fail(
            f"/sw-amend refused: parent lifecycle is closed ({status!r})",
            cause="closed-parent",
            unitId=unit_id,
            consumerStatus=status,
            lifecycleState="closed",
            generationToken=token,
        )

    if body is None or not body.is_file():
        fail(
            f"/sw-amend refused: parent body not found for unit {unit_id!r}",
            cause="missing-parent",
            unitId=unit_id,
            consumerStatus=status,
            generationToken=token,
        )

    if frozen_open:
        return

    if status in AMEND_ALLOWED_STATUSES:
        return

    fail(
        f"/sw-amend refused: unit status is {status!r} "
        f"(requires frozen-open parent or status in {sorted(AMEND_ALLOWED_STATUSES)})",
        cause="status-not-allowed",
        unitId=unit_id,
        consumerStatus=status,
        lifecycleState="unfrozen",
        generationToken=token,
    )


def handoffs_path(root: Path) -> Path:
    return root / HANDOFFS_REL


def load_handoffs(root: Path) -> list[dict[str, Any]]:
    path = handoffs_path(root)
    if not path.is_file():
        return []
    try:
        data = read_json(path)
    except Exception:
        return []
    items = data.get("handoffs") if isinstance(data, dict) else None
    return list(items) if isinstance(items, list) else []


def save_handoffs(root: Path, handoffs: list[dict[str, Any]]) -> None:
    path = handoffs_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, {"version": 1, "updatedAt": utc_now(), "handoffs": handoffs})


def record_handoff(
    root: Path,
    *,
    unit_id: str,
    artifact: str | None,
    command: str | None,
    reason: str,
    run_id: str | None,
    branch: str | None,
) -> dict[str, Any]:
    entry = {
        "unitId": unit_id,
        "artifact": artifact,
        "command": command,
        "reason": reason,
        "runId": run_id,
        "branch": branch,
        "who": actor_id(),
        "when": utc_now(),
    }
    handoffs = load_handoffs(root)
    handoffs.append(entry)
    save_handoffs(root, handoffs)
    return entry


def inline_reconcile(root: Path, unit_id: str, *, commit: bool) -> None:
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "inflight_reconcile.py"),
        str(root),
        "reconcile",
        "--unit",
        unit_id,
    ]
    if commit:
        cmd.append("--commit")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        fail(
            "inline inflight reconcile failed",
            cause="reconcile-failed",
            stderr=proc.stderr.strip(),
            stdout=proc.stdout.strip(),
            exit_code=20,
        )


def provably_in_flight(root: Path, unit_id: str) -> dict[str, Any] | None:
    tuples = read_tuples(root)
    tup: InflightTuple | None = tuples.get(unit_id)
    if tup is None:
        return None
    if is_run_live(root, tup.run_id):
        return {
            "unitId": unit_id,
            "runId": tup.run_id,
            "branch": tup.branch,
            "branchToken": tup.branch_token,
            "epoch": tup.epoch,
        }
    return None


def staged_unit_paths(root: Path) -> dict[str, list[str]]:
    proc = subprocess.run(
        ["git", "-C", str(root), "diff", "--cached", "--name-only"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        return {}
    grouped: dict[str, list[str]] = {}
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        rel = line.strip().replace("\\", "/")
        uid = unit_id_from_rel(rel)
        if not uid:
            continue
        grouped.setdefault(uid, []).append(rel)
    return grouped


def check_staged_mutations(root: Path, args: list[str]) -> None:
    """Pre-commit guard for complete-unit folder immutability (R9/R12)."""
    expect_token = parse_kv(args, "--expect-token")
    unit_filter = parse_kv(args, "--unit")
    warnings: list[str] = []
    violations: list[str] = []
    token_after: dict[str, Any] | None = None

    grouped = staged_unit_paths(root)
    if unit_filter:
        grouped = {unit_filter: grouped.get(unit_filter, [])}

    for unit_id, paths in grouped.items():
        if not paths:
            continue
        token_before = reconcile_generation_token(root, unit_id)
        inline_reconcile(root, unit_id, commit=False)
        token_after = reconcile_generation_token(root, unit_id)

        if expect_token and token_before["token"] != expect_token:
            violations.append(
                f"{unit_id}: reconcile-generation token mismatch (TOCTOU)"
            )
            continue
        if token_before["token"] != token_after["token"]:
            violations.append(
                f"{unit_id}: reconcile-generation token changed during evaluation"
            )
            continue

        status = token_after["consumerStatus"]
        if status != "complete":
            continue

        if token_after["mode"] == "structural-degraded":
            warnings.append(
                f"{unit_id}: structural-degraded mode — complete unit mutation "
                f"on {', '.join(paths)} (warning only; derived region empty)"
            )
            continue

        violations.append(
            f"{unit_id}: mutation rejected on complete unit — {', '.join(paths)}"
        )

    if violations:
        fail(
            "completed-unit immutability violation",
            violations=violations,
            generationToken=token_after.get("token") if token_after else None,
        )
    if warnings:
        for w in warnings:
            print(f"sw-completed-unit: warning: {w}", file=sys.stderr)
    emit(
        {
            "verdict": "pass",
            "action": "completed-unit-guard",
            "warnings": warnings,
            "checkedUnits": list(grouped.keys()),
        }
    )


def cmd_preflight(root: Path, args: list[str]) -> None:
    unit_id, artifact = resolve_unit_id(root, args)
    handoff = parse_kv(args, "--handoff")
    command = parse_kv(args, "--command")
    do_commit = parse_kv(args, "--no-commit") is None

    inline_reconcile(root, unit_id, commit=do_commit)
    live = provably_in_flight(root, unit_id)

    if command == "sw-amend":
        amend_status_guard(root, unit_id, artifact)

    if handoff:
        if not live:
            fail(
                "handoff requires a provably in-flight unit after reconcile",
                unitId=unit_id,
            )
        entry = record_handoff(
            root,
            unit_id=unit_id,
            artifact=artifact,
            command=command,
            reason=handoff,
            run_id=live.get("runId"),
            branch=live.get("branch"),
        )
        emit(
            {
                "verdict": "pass",
                "action": "authoring-guard-preflight",
                "outcome": "handoff",
                "unitId": unit_id,
                "handoff": entry,
            }
        )

    if live:
        fail(
            "unit is in-flight; wait for deliver run or pass --handoff <reason>",
            unitId=unit_id,
            runId=live.get("runId"),
            branch=live.get("branch"),
            exit_code=20,
        )
    emit(
        {
            "verdict": "pass",
            "action": "authoring-guard-preflight",
            "outcome": "proceed",
            "unitId": unit_id,
            "artifact": artifact,
        }
    )


def cmd_list_handoffs(root: Path, _args: list[str]) -> None:
    handoffs = load_handoffs(root)
    emit(
        {
            "verdict": "pass",
            "action": "authoring-guard-list-handoffs",
            "handoffs": handoffs,
            "pullInScan": [h.get("artifact") for h in handoffs if h.get("artifact")],
        }
    )


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        fail("usage: authoring_guard.py <repo-root> <command> [options]")
    root = Path(args[0]).resolve()
    rest = args[1:]
    if not rest:
        fail("subcommand required: preflight|list-handoffs|check-staged")
    cmd = rest[0]
    tail = rest[1:]
    if cmd == "preflight":
        cmd_preflight(root, tail)
    elif cmd == "list-handoffs":
        cmd_list_handoffs(root, tail)
    elif cmd == "check-staged":
        check_staged_mutations(root, tail)
    else:
        fail(f"unknown subcommand: {cmd}")


if __name__ == "__main__":
    main()
