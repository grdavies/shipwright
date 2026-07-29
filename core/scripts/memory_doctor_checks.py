#!/usr/bin/env python3
"""Memory doctor checks scoped to PRD 082 R26–R32 (R34 unified inspection)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from host_lib import load_workflow_config

FAILURE_SOT_MIGRATION = "memory-source-of-truth-migration-required"
FAILURE_SCHEMA_DRIFT = "memory-schema-version-drift"
FAILURE_DUPLICATE_ACTIVE = "memory-duplicate-active"
FAILURE_CONTRADICTORY_ACTIVE = "memory-contradictory-active"
FAILURE_STALE_DECISION_POINTER = "memory-stale-decision-pointer"
FAILURE_ALIAS_COLLISION = "alias-collision"
FAILURE_DIST_STALE = "dist-stale"

SUPPORTED_SCHEMA_VERSIONS = frozenset({1, 2})


def _check(
    name: str,
    status: str,
    *,
    failure_code: str | None = None,
    remediation: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"check": name, "status": status, **extra}
    if failure_code:
        payload["failureCode"] = failure_code
    if remediation:
        payload["remediation"] = remediation
    return payload


def _memory_store_dir(root: Path) -> Path:
    return root / ".cursor" / "sw-memory"


def _parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}
    meta: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        meta[key.strip()] = val.strip()
    return meta


def _load_memory_records(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    store = _memory_store_dir(root)
    if not store.is_dir():
        return records
    for path in sorted(store.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix == ".json":
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(doc, dict):
                doc.setdefault("_path", str(path.relative_to(root)))
                records.append(doc)
            continue
        if path.suffix != ".md":
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        meta = _parse_frontmatter(text)
        stable_id = meta.get("stableId") or meta.get("id") or path.stem
        records.append(
            {
                "stableId": stable_id,
                "category": meta.get("category") or "learning",
                "status": meta.get("status") or "active",
                "schemaVersion": int(meta.get("schemaVersion") or 1),
                "fields": meta,
                "_path": str(path.relative_to(root)),
            }
        )
    return records


def check_schema_versions(root: Path) -> dict[str, Any]:
    records = _load_memory_records(root)
    drift = sorted(
        {
            int(record.get("schemaVersion") or 1)
            for record in records
            if int(record.get("schemaVersion") or 1) not in SUPPORTED_SCHEMA_VERSIONS
        }
    )
    if drift:
        return _check(
            "memory-schema-versions",
            "warn",
            failure_code=FAILURE_SCHEMA_DRIFT,
            remediation="upgrade or reconcile unsupported schema versions via memory_envelope_upgrade.py",
            unsupportedVersions=drift,
            recordCount=len(records),
        )
    versions = sorted({int(record.get("schemaVersion") or 1) for record in records}) or [2]
    return _check(
        "memory-schema-versions",
        "pass",
        versions=versions,
        recordCount=len(records),
    )


def check_duplicate_and_contradictory_active(root: Path) -> list[dict[str, Any]]:
    records = _load_memory_records(root)
    active_by_id: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if str(record.get("status") or "active") != "active":
            continue
        stable_id = str(record.get("stableId") or "").strip()
        if not stable_id:
            continue
        active_by_id.setdefault(stable_id, []).append(record)

    duplicates = {sid: items for sid, items in active_by_id.items() if len(items) > 1}
    contradictory: list[dict[str, Any]] = []
    for stable_id, items in duplicates.items():
        hashes = {
            str(item.get("contentHash") or item.get("_path") or "")
            for item in items
        }
        if len(hashes) > 1:
            contradictory.append(
                {
                    "stableId": stable_id,
                    "paths": [item.get("_path") for item in items],
                }
            )

    checks: list[dict[str, Any]] = []
    if duplicates:
        checks.append(
            _check(
                "memory-duplicate-active",
                "fail",
                failure_code=FAILURE_DUPLICATE_ACTIVE,
                remediation="supersede duplicate active records so only one active envelope remains per stableId",
                stableIds=sorted(duplicates),
                count=sum(len(v) for v in duplicates.values()),
            )
        )
    else:
        checks.append(_check("memory-duplicate-active", "pass", duplicateCount=0))

    if contradictory:
        checks.append(
            _check(
                "memory-contradictory-active",
                "fail",
                failure_code=FAILURE_CONTRADICTORY_ACTIVE,
                remediation="resolve contradictory active bodies for the same stableId before promotion",
                conflicts=contradictory,
            )
        )
    else:
        checks.append(_check("memory-contradictory-active", "pass", conflictCount=0))
    return checks


def check_stale_decision_pointers(root: Path) -> dict[str, Any]:
    from memory_sot_audit import scan_in_repo_decision_memories

    memories = scan_in_repo_decision_memories(root)
    stale = [
        mem
        for mem in memories
        if mem.get("likelyPointer") and not mem.get("relatedFiles")
    ]
    if stale:
        return _check(
            "memory-stale-decision-pointer",
            "warn",
            failure_code=FAILURE_STALE_DECISION_POINTER,
            remediation=(
                "add relatedFiles pointers to git decision records or collapse pointer-shaped "
                "decision memories via memory_sot_audit.py audit-conflicts"
            ),
            memories=[item.get("path") for item in stale],
            count=len(stale),
        )
    return _check(
        "memory-stale-decision-pointer",
        "pass",
        pointerCount=len(memories),
    )


def check_source_of_truth(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    from memory_sot import classify_source_of_truth

    finding = classify_source_of_truth(root, cfg)
    status = "pass"
    failure_code = None
    if finding.get("classification") == "migration-required":
        status = "fail"
        failure_code = FAILURE_SOT_MIGRATION
    return _check(
        "memory-source-of-truth",
        status,
        failure_code=failure_code,
        remediation=finding.get("remediation"),
        classification=finding.get("classification"),
        provider=finding.get("provider"),
        sourceOfTruth=finding.get("sourceOfTruth"),
        exportCommand=finding.get("exportCommand"),
    )


def check_alias_collisions(root: Path) -> dict[str, Any]:
    from memory_key_collision import KeyCollisionError, build_alias_index

    records = _load_memory_records(root)
    if not records:
        return _check("memory-alias-collision", "pass", collisionCount=0)
    try:
        build_alias_index(records)
    except KeyCollisionError as exc:
        return _check(
            "memory-alias-collision",
            "fail",
            failure_code=FAILURE_ALIAS_COLLISION,
            remediation=(
                "resolve alias collisions via memory_key_collision migration before writing "
                "new interchange records"
            ),
            cause=exc.cause,
            detail=str(exc),
        )
    return _check("memory-alias-collision", "pass", collisionCount=0)


def check_dist_freshness(root: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "build-chain-sync.py"), "--check"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return _check(
            "generated-distribution-freshness",
            "warn",
            failure_code=FAILURE_DIST_STALE,
            remediation="run `python3 scripts/build-chain-sync.py` to refresh generated dist output",
            detail=(proc.stderr or proc.stdout or "").strip()[:300],
        )
    return _check("generated-distribution-freshness", "pass")


def run_memory_checks(root: Path, cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Run memory doctor checks proving R26–R32 only."""
    cfg = cfg if cfg is not None else load_workflow_config(root)
    checks: list[dict[str, Any]] = [
        check_schema_versions(root),
        *check_duplicate_and_contradictory_active(root),
        check_stale_decision_pointers(root),
        check_source_of_truth(root, cfg),
        check_alias_collisions(root),
        check_dist_freshness(root),
    ]
    return checks


def aggregate_verdict(checks: list[dict[str, Any]]) -> str:
    if any(check.get("status") == "fail" for check in checks):
        return "fail"
    if any(check.get("status") == "warn" for check in checks):
        return "degraded"
    return "ok"
