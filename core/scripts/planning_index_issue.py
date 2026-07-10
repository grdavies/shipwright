#!/usr/bin/env python3
"""Issue-store projection for planning INDEX derived status (PRD 056 R8/R9)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_discover  # noqa: E402
import planning_index_gen as pig  # noqa: E402
import planning_paths as pp  # noqa: E402
from host_lib import load_workflow_config  # noqa: E402
from planning_cutover import region_authority  # noqa: E402
from planning_store import get_backend, resolve_effective_backend  # noqa: E402

DERIVED_CACHE_REL = ".cursor/hooks/state/planning-index-derived.json"
DERIVED_ARTIFACT_UNIT = "planning-index-derived"
DERIVED_ARTIFACT_BODY = ".cursor/hooks/state/planning-index-derived.md"
VALID_INDEX_STATUSES = frozenset({"not-started", "in-progress", "complete"})


def derived_cache_path(root: Path) -> Path:
    return pp.git_root(root) / DERIVED_CACHE_REL


def derived_authority_is_issue(root: Path) -> bool:
    worktree = pp.git_root(root)
    return region_authority(worktree, "derived") == "issue"


def load_derived_cache(root: Path) -> dict[str, str]:
    path = derived_cache_path(root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    mapping = data.get("statuses") if isinstance(data, dict) else None
    if not isinstance(mapping, dict):
        return {}
    return {str(k): str(v) for k, v in mapping.items() if isinstance(k, str) and isinstance(v, str)}


def save_derived_cache(root: Path, statuses: dict[str, str]) -> None:
    path = derived_cache_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 1, "statuses": dict(sorted(statuses.items()))}, indent=2) + "\n",
        encoding="utf-8",
    )


def render_derived_body(status_map: dict[str, str]) -> str:
    lines = [f"{unit_id}: {status}" for unit_id, status in sorted(status_map.items())]
    return "\n".join(lines) + ("\n" if lines else "")


def resolve_prd_unit_id(root: Path, prd: str, *, slug: str | None = None) -> str | None:
    """Map a legacy PRD number to a planning unit id."""
    prd = prd.zfill(3)
    worktree = pp.git_root(root)
    if slug:
        for candidate in (f"prd-{prd}-{slug}", f"{prd}-prd-{slug}"):
            for unit in planning_discover.discover_units_file(worktree):
                if unit.id == candidate and unit.type == "prd":
                    return unit.id
    for unit in planning_discover.discover_units_file(worktree):
        if unit.type != "prd":
            continue
        if unit.id.startswith(f"prd-{prd}-") or unit.id.startswith(f"{prd}-prd-"):
            return unit.id
        body_name = Path(unit.body_path).name
        if body_name.startswith(f"{prd}-") or f"/{prd}-" in unit.body_path.replace("\\", "/"):
            return unit.id
    return None


def project_index_status(
    root: Path,
    prd: str,
    status: str,
    *,
    slug: str | None = None,
    dry_run: bool = False,
    force_issue_store: bool = False,
) -> dict[str, Any]:
    """Project legacy PRD INDEX status to issue store when derived authority is issue."""
    if status not in VALID_INDEX_STATUSES:
        return {"verdict": "fail", "error": f"invalid status {status!r}"}
    prd = prd.zfill(3)
    if not force_issue_store and not derived_authority_is_issue(root):
        return {
            "verdict": "skipped",
            "action": "project-index-status",
            "authority": "file",
            "prd": prd,
            "status": status,
        }

    worktree = pp.git_root(root)
    cfg = load_workflow_config(worktree)
    effective = resolve_effective_backend(worktree, cfg)
    if effective.get("effective") != "issue-store":
        return {
            "verdict": "skipped",
            "action": "project-index-status",
            "reason": "issue-store-not-effective",
            "prd": prd,
            "status": status,
        }

    unit_id = resolve_prd_unit_id(worktree, prd, slug=slug)
    if not unit_id:
        return {
            "verdict": "degraded",
            "action": "project-index-status",
            "notice": f"prd-unit-not-found:{prd}",
            "prd": prd,
            "status": status,
        }

    statuses = load_derived_cache(worktree)
    statuses[unit_id] = status
    derived_body = render_derived_body(statuses)

    if dry_run:
        return {
            "verdict": "pass",
            "action": "project-index-status",
            "authority": "issue",
            "prd": prd,
            "unitId": unit_id,
            "status": status,
            "dryRun": True,
        }

    try:
        backend = get_backend(worktree, cfg)
        put_result = backend.put(DERIVED_ARTIFACT_UNIT, DERIVED_ARTIFACT_BODY, derived_body)
        if put_result.verdict not in {"ok", "degraded"}:
            return {
                "verdict": "degraded",
                "action": "project-index-status",
                "notice": put_result.reason or "planning-store-put-failed",
                "prd": prd,
                "unitId": unit_id,
                "status": status,
            }
        save_derived_cache(worktree, statuses)
        out: dict[str, Any] = {
            "verdict": "pass",
            "action": "project-index-status",
            "authority": "issue",
            "prd": prd,
            "unitId": unit_id,
            "status": status,
            "backend": put_result.backend,
        }
        if put_result.verdict == "degraded":
            out["notice"] = put_result.reason or "planning-store-degraded"
        return out
    except Exception as exc:  # noqa: BLE001 — graceful degradation for unreachable store
        return {
            "verdict": "degraded",
            "action": "project-index-status",
            "notice": f"issue-store-unreachable:{exc}",
            "prd": prd,
            "unitId": unit_id,
            "status": status,
        }


def project_derived_map(
    root: Path,
    derived: dict[str, str],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Project the full reconciler derived-status map to the issue store (PRD 056 R8)
    when the effective backend is issue-store (PRD 057 R3 reconcile guard). The
    authoritative-store update always runs for an effective issue-store backend;
    the gitignored derived cache is additionally refreshed only when the cutover
    ``derived`` region authority is issue (``derived_authority_is_issue``), so a
    reader (``read_derived_status_map``) sees a consistent view without ever
    requiring a tracked local write.
    """
    worktree = pp.git_root(root)
    cfg = load_workflow_config(worktree)
    effective = resolve_effective_backend(worktree, cfg)
    if effective.get("effective") != "issue-store":
        return {"verdict": "skipped", "action": "project-derived-map", "reason": "not-issue-store"}

    cache_authority = derived_authority_is_issue(worktree)
    if dry_run:
        return {
            "verdict": "pass",
            "action": "project-derived-map",
            "authority": "issue" if cache_authority else "store-only",
            "unitCount": len(derived),
            "dryRun": True,
        }

    derived_body = render_derived_body(derived)
    try:
        backend = get_backend(worktree, cfg)
        put_result = backend.put(DERIVED_ARTIFACT_UNIT, DERIVED_ARTIFACT_BODY, derived_body)
        if put_result.verdict not in {"ok", "degraded"}:
            return {
                "verdict": "degraded",
                "action": "project-derived-map",
                "notice": put_result.reason or "planning-store-put-failed",
                "unitCount": len(derived),
            }
        if cache_authority:
            save_derived_cache(worktree, derived)
        out: dict[str, Any] = {
            "verdict": "pass",
            "action": "project-derived-map",
            "authority": "issue" if cache_authority else "store-only",
            "unitCount": len(derived),
            "backend": put_result.backend,
            "cached": cache_authority,
        }
        if put_result.verdict == "degraded":
            out["notice"] = put_result.reason or "planning-store-degraded"
        return out
    except Exception as exc:  # noqa: BLE001 — graceful degradation for unreachable store
        return {
            "verdict": "degraded",
            "action": "project-derived-map",
            "notice": f"issue-store-unreachable:{exc}",
            "unitCount": len(derived),
        }


def read_derived_status_map(root: Path) -> dict[str, str]:
    """Read derived status map from cache when issue authority is active."""
    if not force_issue_store and not derived_authority_is_issue(root):
        index_path = pig.index_path(root)
        if not index_path.is_file():
            return {}
        regions = pig.parse_regions(index_path.read_text(encoding="utf-8"))
        return pig.parse_derived_status_map(regions.derived)
    return load_derived_cache(root)

def read_projected_index_status(
    root: Path, prd: str, *, slug: str | None = None
) -> dict[str, Any] | None:
    """Read INDEX status evidence from store projection cache (PRD 061 R4)."""
    from planning_artifact_handle import issue_store_is_effective

    prd = prd.zfill(3)
    unit_id = resolve_prd_unit_id(root, prd, slug=slug)
    if not unit_id:
        return None
    worktree = pp.git_root(root)
    if issue_store_is_effective(worktree):
        statuses = load_derived_cache(worktree)
        authority = "issue"
    else:
        statuses = read_derived_status_map(worktree)
        authority = "file"
    status = statuses.get(unit_id)
    if status is None:
        return None
    return {
        "verdict": "pass",
        "prd": prd,
        "unitId": unit_id,
        "status": status,
        "authority": authority,
    }

