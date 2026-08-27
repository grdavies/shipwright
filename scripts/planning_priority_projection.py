#!/usr/bin/env python3
"""Read-only projection of authoritative program priorities (PRD 333 R5/R6/R18/R20)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

AUTHORITY_REL_PATH = ".sw/program-priorities.json"
TIER_ORDER = ("P0", "P1", "P2", "P3")
RELEASE_TRAIN_IDS = ("v2.5.1", "v2.6", "v2.7")
PROVIDER_FOLLOW_ON_IDS = (
    "gitlab-planning-store",
    "remote-execution",
    "upstream-provenance",
    "workflow-package-marketplace",
)
NON_AUTHORITY_SUFFIXES = (
    "program-priorities.projection.json",
    "program-priorities.labels.json",
    "program-priorities.index.json",
)


def authority_path(root: Path) -> Path:
    return root / AUTHORITY_REL_PATH


def reject_projection_as_authority(path: Path | str) -> None:
    """Fail closed when a projection artifact is treated as authority."""
    text = str(path).replace("\\", "/")
    if text.endswith(AUTHORITY_REL_PATH):
        return
    for suffix in NON_AUTHORITY_SUFFIXES:
        if text.endswith(suffix):
            raise ValueError("projection-cannot-be-authority")
    if "projection" in Path(text).name and "program-priorit" in text:
        raise ValueError("projection-cannot-be-authority")


def _tier_ranks(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tiers = doc.get("priorityTiers")
    if not isinstance(tiers, dict):
        raise ValueError("priorityTiers-required")
    missing = [tier for tier in TIER_ORDER if tier not in tiers]
    if missing:
        raise ValueError(f"missing-priority-tiers:{','.join(missing)}")
    ranks: dict[str, dict[str, Any]] = {}
    seen_ranks: set[int] = set()
    seen_programs: set[str] = set()
    for tier in TIER_ORDER:
        entry = tiers[tier]
        if not isinstance(entry, dict):
            raise ValueError(f"invalid-tier:{tier}")
        rank = entry.get("rank")
        if not isinstance(rank, int):
            raise ValueError(f"invalid-tier-rank:{tier}")
        if rank in seen_ranks:
            raise ValueError("duplicate-priority-rank")
        seen_ranks.add(rank)
        programs = entry.get("programs")
        if not isinstance(programs, list) or not programs:
            raise ValueError(f"invalid-tier-programs:{tier}")
        for program in programs:
            pid = str(program).strip()
            if not pid:
                raise ValueError(f"empty-program:{tier}")
            if pid in seen_programs:
                raise ValueError("duplicate-program-across-tiers")
            seen_programs.add(pid)
        ranks[tier] = entry
    expected = set(range(len(TIER_ORDER)))
    if seen_ranks != expected:
        raise ValueError("invalid-priority-rank-order")
    return ranks


def _release_sequence(doc: dict[str, Any]) -> list[dict[str, Any]]:
    raw = doc.get("releaseSequence")
    if not isinstance(raw, list) or not raw:
        raise ValueError("releaseSequence-required")
    by_order: dict[int, dict[str, Any]] = {}
    seen_ids: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("invalid-release-sequence-entry")
        order = item.get("order")
        train_id = str(item.get("id") or "").strip()
        if not isinstance(order, int) or not train_id:
            raise ValueError("invalid-release-sequence-entry")
        if order in by_order or train_id in seen_ids:
            raise ValueError("duplicate-release-sequence")
        by_order[order] = item
        seen_ids.add(train_id)
    expected_orders = list(range(1, len(RELEASE_TRAIN_IDS) + 1))
    if sorted(by_order) != expected_orders:
        raise ValueError("release-sequence-order-inversion")
    ordered = [by_order[i] for i in expected_orders]
    ids = tuple(str(item.get("id")) for item in ordered)
    if ids != RELEASE_TRAIN_IDS:
        raise ValueError("unknown-release-train")
    return ordered


def _provider_follow_on(doc: dict[str, Any]) -> list[dict[str, Any]]:
    raw = doc.get("providerFollowOn")
    if not isinstance(raw, list) or not raw:
        raise ValueError("providerFollowOn-required")
    by_order: dict[int, dict[str, Any]] = {}
    seen_ids: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("invalid-provider-follow-on-entry")
        order = item.get("order")
        provider_id = str(item.get("id") or "").strip()
        if not isinstance(order, int) or not provider_id:
            raise ValueError("invalid-provider-follow-on-entry")
        if order in by_order or provider_id in seen_ids:
            raise ValueError("duplicate-provider-follow-on")
        by_order[order] = item
        seen_ids.add(provider_id)
    expected_orders = list(range(1, len(PROVIDER_FOLLOW_ON_IDS) + 1))
    if sorted(by_order) != expected_orders:
        raise ValueError("provider-follow-on-order-inversion")
    ordered = [by_order[i] for i in expected_orders]
    ids = tuple(str(item.get("id")) for item in ordered)
    if ids != PROVIDER_FOLLOW_ON_IDS:
        raise ValueError("unknown-provider-follow-on")
    if ids[-1] != "workflow-package-marketplace":
        raise ValueError("marketplace-not-last")
    return ordered


def validate_authority(doc: dict[str, Any], *, source: str = AUTHORITY_REL_PATH) -> dict[str, Any]:
    reject_projection_as_authority(source)
    if not isinstance(doc, dict):
        raise ValueError("authority-document-required")
    version = doc.get("version")
    if not isinstance(version, int) or version < 1:
        raise ValueError("authority-version-required")
    authority_path_value = str(doc.get("authorityPath") or "").strip()
    if authority_path_value != AUTHORITY_REL_PATH:
        raise ValueError("second-authority-path")
    _tier_ranks(doc)
    _release_sequence(doc)
    _provider_follow_on(doc)
    return doc


def load_authority(root: Path) -> dict[str, Any]:
    path = authority_path(root)
    if not path.is_file():
        raise FileNotFoundError("authority-missing")
    doc = json.loads(path.read_text(encoding="utf-8"))
    return validate_authority(doc, source=str(path))


def project_labels(doc: dict[str, Any]) -> list[str]:
    validated = validate_authority(doc)
    labels: list[str] = []
    for tier in TIER_ORDER:
        entry = validated["priorityTiers"][tier]
        labels.append(f"sw:program-tier:{tier}")
        for program in entry["programs"]:
            labels.append(f"sw:program:{program}")
    for train in validated["releaseSequence"]:
        labels.append(f"sw:release-train:{train['id']}")
    for provider in validated["providerFollowOn"]:
        labels.append(f"sw:provider-follow-on:{provider['id']}")
    return labels


def project_index_fields(doc: dict[str, Any]) -> dict[str, Any]:
    validated = validate_authority(doc)
    return {
        "programPriorityRevision": validated.get("revision"),
        "programPriorityVersion": validated.get("version"),
        "releaseSequence": [
            {"id": item["id"], "theme": item.get("theme"), "order": item["order"]}
            for item in validated["releaseSequence"]
        ],
        "providerFollowOn": [
            {"id": item["id"], "order": item["order"], "tier": item.get("tier")}
            for item in validated["providerFollowOn"]
        ],
        "priorityTiers": {
            tier: {"rank": validated["priorityTiers"][tier]["rank"]}
            for tier in TIER_ORDER
        },
        "authorityPath": AUTHORITY_REL_PATH,
        "projection": True,
    }


def project_graph_metadata(doc: dict[str, Any]) -> dict[str, Any]:
    validated = validate_authority(doc)
    return {
        "authorityPath": AUTHORITY_REL_PATH,
        "projection": True,
        "priorityTiers": {
            tier: {
                "rank": validated["priorityTiers"][tier]["rank"],
                "programs": list(validated["priorityTiers"][tier]["programs"]),
            }
            for tier in TIER_ORDER
        },
        "releaseSequence": list(validated["releaseSequence"]),
        "providerFollowOn": list(validated["providerFollowOn"]),
    }


def project_all(doc: dict[str, Any]) -> dict[str, Any]:
    validated = validate_authority(doc)
    return {
        "verdict": "ok",
        "action": "program-priority-projection",
        "authorityPath": AUTHORITY_REL_PATH,
        "projection": True,
        "revision": validated.get("revision"),
        "version": validated.get("version"),
        "labels": project_labels(validated),
        "indexFields": project_index_fields(validated),
        "graphMetadata": project_graph_metadata(validated),
    }


def project_from_repo(root: Path) -> dict[str, Any]:
    return project_all(load_authority(root))


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) < 1:
        emit({"verdict": "fail", "error": "usage: planning_priority_projection.py <repo-root>"}, 20)
    root = Path(args[0]).resolve()
    try:
        emit(project_from_repo(root))
    except FileNotFoundError as exc:
        emit({"verdict": "fail", "error": str(exc)}, 20)
    except ValueError as exc:
        emit({"verdict": "fail", "error": str(exc)}, 20)


if __name__ == "__main__":
    main()
