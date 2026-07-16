#!/usr/bin/env python3
"""Merge-boundary close-out: PR-to-delivery mapping, closure manifests, metadata hardening (PRD 070)."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from host_lib import load_workflow_config
from inflight_signal import prd_unit_id_from_state
from wave_json_io import read_json, write_json
from wave_state import load_deliver_state

CLOSEOUT_ROOT_REL = ".sw/deliver-closeout"
PR_MAP_DIR = "pr-delivery-map"
MANIFEST_DIR = "closure-manifests"
CLOSE_MARKER_DIR = "close-markers"
INDEX_REL = f"{CLOSEOUT_ROOT_REL}/index.json"
DEFAULT_POLL_SECONDS = 45
DEFAULT_MAX_WAIT_MINUTES = 20

_METADATA_PATTERNS = {
    "prNumber": re.compile(r"^\d{1,10}$"),
    "mergeSha": re.compile(r"^[0-9a-f]{40}$", re.I),
    "prdUnitId": re.compile(r"^prd-\d{3}-[a-z0-9][-a-z0-9]*$"),
    "prdNumber": re.compile(r"^\d{3}$"),
    "deliverySlug": re.compile(r"^[a-z0-9][-a-z0-9]{0,120}$"),
    "targetBranch": re.compile(r"^[a-zA-Z0-9][-a-zA-Z0-9._/]{0,200}$"),
    "headSha": re.compile(r"^[0-9a-f]{40}$", re.I),
    "prUrl": re.compile(r"^https://[^\s\"\'`;$|&<>]+$"),
    "runSlug": re.compile(r"^[a-z0-9][-a-z0-9]{0,120}$"),
    "recordedAt": re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"),
}

_SAFE_TEXT_FIELDS = frozenset({"prTitle", "mergeMethod"})


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(obj, exit_code=0):
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error, exit_code=2, **extra):
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def closeout_root(root: Path) -> Path:
    return root / CLOSEOUT_ROOT_REL


def pr_map_path(root: Path, pr_number) -> Path:
    return closeout_root(root) / PR_MAP_DIR / f"pr-{int(pr_number)}.json"


def manifest_path(root: Path, prd_unit_id: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9._-]", "-", prd_unit_id)
    return closeout_root(root) / MANIFEST_DIR / f"{safe}.json"


def close_marker_path(root: Path, prd_unit_id: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9._-]", "-", prd_unit_id)
    return closeout_root(root) / CLOSE_MARKER_DIR / f"{safe}.json"


def slug_from_target_branch(branch: str) -> str:
    if "/" not in branch:
        return branch
    return branch.split("/", 1)[1]


def deliver_run_id_from_state(state: dict[str, Any]) -> str | None:
    prd = state.get("prd_number")
    if prd is None:
        return None
    prd_str = str(prd).zfill(3)
    target = state.get("target") or {}
    slug = target.get("slug") or slug_from_target_branch(str(target.get("branch") or ""))
    if not slug:
        return None
    return f"sw-deliver-{prd_str}-{slug}"


def deliver_wake_sentinel(run_id: str) -> str:
    return f"DELIVER_WAKE_{run_id}"


def watch_config(cfg: dict[str, Any]) -> dict[str, int]:
    watch = (cfg.get("checks") or {}).get("watch") or {}
    return {
        "pollSeconds": int(watch.get("pollSeconds") or DEFAULT_POLL_SECONDS),
        "maxWaitMinutes": int(watch.get("maxWaitMinutes") or DEFAULT_MAX_WAIT_MINUTES),
    }


def is_pending_merge_completion(state: dict[str, Any]) -> bool:
    completion = state.get("completion") or {}
    return completion.get("status") == "completed-pending-merge"


def resolve_state_by_run_id(root: Path, run_id: str) -> tuple[dict[str, Any] | None, Path | None, str | None]:
    from wave_state import enumerate_scoped_runs

    for run in enumerate_scoped_runs(root):
        state_path = root / str(run["statePath"])
        state = read_json(state_path) if state_path.is_file() else {}
        if deliver_run_id_from_state(state) == run_id:
            return state, state_path, str(run.get("slug") or "")
    match = re.fullmatch(r"sw-deliver-(\d{3})-(.+)", run_id)
    if match:
        slug = match.group(2)
        state_path = root / ".cursor" / f"sw-deliver-state.{slug}.json"
        if state_path.is_file():
            state = read_json(state_path)
            if deliver_run_id_from_state(state) == run_id:
                return state, state_path, slug
    return None, None, None


def load_close_marker(root: Path, prd_unit_id: str) -> dict[str, Any] | None:
    data = read_json(close_marker_path(root, prd_unit_id))
    return data if data else None


def write_close_marker(root: Path, prd_unit_id: str, merge_sha: str, *, audit: dict[str, Any]) -> dict[str, Any]:
    marker = {
        "version": 1,
        "prdUnitId": prd_unit_id,
        "mergeSha": merge_sha.lower(),
        "writtenAt": utc_now(),
        "auditVerdict": audit.get("verdict"),
    }
    write_json(close_marker_path(root, prd_unit_id), marker)
    return marker


def short_circuit_closeout(
    root: Path,
    cfg: dict[str, Any],
    prd_unit_id: str,
    merge_sha: str,
    *,
    state: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    marker = load_close_marker(root, prd_unit_id)
    if not marker:
        return None
    if str(marker.get("mergeSha") or "").lower() != str(merge_sha).lower():
        return None
    from planning_store import audit_closure_completeness

    audit = audit_closure_completeness(root, cfg, prd_unit_id, state=state)
    if audit.get("verdict") != "ready":
        return None
    return {
        "verdict": "ready",
        "action": "closeout-short-circuit",
        "noop": True,
        "prdUnitId": prd_unit_id,
        "mergeSha": merge_sha.lower(),
        "marker": marker,
        "closureAudit": audit,
    }


def extract_merge_sha(root: Path, merge_info: dict[str, Any]) -> str:
    merge_commit = merge_info.get("mergeCommit")
    if merge_commit:
        return str(merge_commit).lower()
    default_ref = merge_info.get("defaultRef") or merge_info.get("default")
    if not default_ref:
        return ""
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", str(default_ref)],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip().lower()
    return ""


def emit_self_wake_sentinel(run_id: str, payload: dict[str, Any] | None = None) -> str:
    sentinel = deliver_wake_sentinel(run_id)
    body = payload or {"phase": "terminal-merge-closeout", "runId": run_id}
    print(f"{sentinel} {json.dumps(body, ensure_ascii=False)}", file=sys.stderr)
    return sentinel


def index_path(root: Path) -> Path:
    return root / INDEX_REL


def validate_metadata_field(field: str, value):
    if value is None:
        return {"verdict": "fail", "field": field, "error": "missing-value"}
    text = str(value).strip()
    if not text:
        return {"verdict": "fail", "field": field, "error": "empty-value"}
    if field in _SAFE_TEXT_FIELDS:
        if any(ord(ch) < 32 for ch in text):
            return {"verdict": "fail", "field": field, "error": "control-characters"}
        if len(text) > 500:
            return {"verdict": "fail", "field": field, "error": "too-long"}
        return {"verdict": "pass", "field": field}
    pattern = _METADATA_PATTERNS.get(field)
    if pattern is None:
        return {"verdict": "fail", "field": field, "error": "unknown-field"}
    if not pattern.fullmatch(text):
        return {"verdict": "fail", "field": field, "error": "pattern-mismatch", "value": text[:80]}
    return {"verdict": "pass", "field": field}


def validate_metadata_payload(payload, *, fields=None):
    required = fields or sorted(_METADATA_PATTERNS.keys())
    failures = []
    for field in required:
        if field not in payload:
            failures.append({"field": field, "error": "missing-key"})
            continue
        result = validate_metadata_field(field, payload.get(field))
        if result.get("verdict") != "pass":
            failures.append(result)
    if failures:
        return {"verdict": "fail", "action": "validate-metadata", "failures": failures}
    return {"verdict": "pass", "action": "validate-metadata"}


def _canonical_mapping(payload):
    return {
        "version": 1,
        "prNumber": int(payload["prNumber"]),
        "prUrl": str(payload.get("prUrl") or ""),
        "prdUnitId": str(payload["prdUnitId"]),
        "prdNumber": str(payload.get("prdNumber") or "").zfill(3)[-3:],
        "deliverySlug": str(payload["deliverySlug"]),
        "targetBranch": str(payload["targetBranch"]),
        "headSha": str(payload.get("headSha") or "").lower(),
        "runSlug": str(payload.get("runSlug") or payload["deliverySlug"]),
        "recordedAt": str(payload.get("recordedAt") or utc_now()),
    }


def _load_index(root: Path):
    data = read_json(index_path(root))
    if not data:
        return {"version": 1, "byPr": {}, "byPrdUnit": {}}
    data.setdefault("version", 1)
    data.setdefault("byPr", {})
    data.setdefault("byPrdUnit", {})
    return data


def _save_index(root: Path, index):
    write_json(index_path(root), index)


def record_pr_delivery_mapping(root: Path, payload, *, dry_run=False):
    validated = validate_metadata_payload(payload, fields=["prNumber", "prdUnitId", "deliverySlug", "targetBranch", "headSha", "runSlug"])
    if validated.get("verdict") != "pass":
        return {**validated, "action": "record-pr-delivery-mapping"}
    mapping = _canonical_mapping(payload)
    if payload.get("prUrl"):
        url_check = validate_metadata_field("prUrl", payload["prUrl"])
        if url_check.get("verdict") != "pass":
            return {**url_check, "action": "record-pr-delivery-mapping"}
        mapping["prUrl"] = str(payload["prUrl"])
    pr_number = mapping["prNumber"]
    path = pr_map_path(root, pr_number)
    existing = read_json(path) if path.is_file() else {}
    if existing:
        for key in ("prdUnitId", "deliverySlug", "targetBranch", "runSlug"):
            if str(existing.get(key) or "") != str(mapping.get(key) or ""):
                return {"verdict": "fail", "action": "record-pr-delivery-mapping", "error": "mapping-immutable-conflict", "prNumber": pr_number}
        return {"verdict": "pass", "action": "record-pr-delivery-mapping", "immutable": True, "reused": True, "prNumber": pr_number, "path": str(path), "mapping": existing}
    if dry_run:
        return {"verdict": "pass", "action": "record-pr-delivery-mapping", "dryRun": True, "prNumber": pr_number, "wouldWrite": str(path), "mapping": mapping}
    write_json(path, mapping)
    index = _load_index(root)
    rel = str(path.relative_to(root))
    index["byPr"][str(pr_number)] = rel
    index["byPrdUnit"][mapping["prdUnitId"]] = {"prNumber": pr_number, "path": rel}
    _save_index(root, index)
    return {"verdict": "pass", "action": "record-pr-delivery-mapping", "immutable": True, "prNumber": pr_number, "path": str(path), "mapping": mapping}


def load_pr_delivery_mapping(root: Path, pr_number):
    data = read_json(pr_map_path(root, pr_number))
    return data if data else None


def resolve_delivery_for_pr(root: Path, pr_number):
    mapping = load_pr_delivery_mapping(root, pr_number)
    if not mapping:
        return {"verdict": "fail", "action": "resolve-delivery-for-pr", "error": "no-delivery-mapping", "prNumber": int(pr_number)}
    return {"verdict": "pass", "action": "resolve-delivery-for-pr", "prNumber": int(pr_number), "prdUnitId": mapping.get("prdUnitId"), "deliverySlug": mapping.get("deliverySlug"), "targetBranch": mapping.get("targetBranch"), "mappingPath": str(pr_map_path(root, pr_number)), "mapping": mapping}


def resolve_delivery_for_merge(root: Path, *, pr_number=None, merge_sha=None):
    if pr_number is not None:
        return resolve_delivery_for_pr(root, pr_number)
    if merge_sha:
        merge_check = validate_metadata_field("mergeSha", merge_sha)
        if merge_check.get("verdict") != "pass":
            return {**merge_check, "action": "resolve-delivery-for-merge"}
        manifests_dir = closeout_root(root) / MANIFEST_DIR
        if manifests_dir.is_dir():
            for manifest_file in sorted(manifests_dir.glob("*.json")):
                data = read_json(manifest_file)
                if str(data.get("mergeSha") or "").lower() == str(merge_sha).lower():
                    return {"verdict": "pass", "action": "resolve-delivery-for-merge", "mergeSha": merge_sha.lower(), "prdUnitId": data.get("prdUnitId"), "manifestPath": str(manifest_file), "source": "closure-manifest"}
    return {"verdict": "fail", "action": "resolve-delivery-for-merge", "error": "unresolved", "prNumber": pr_number, "mergeSha": merge_sha}


def build_closure_manifest(*, prd_unit_id, merge_sha, delivery_set, closure_result=None, pr_number=None, provenance=None):
    meta_check = validate_metadata_payload({"prdUnitId": prd_unit_id, "mergeSha": merge_sha}, fields=["prdUnitId", "mergeSha"])
    if meta_check.get("verdict") != "pass":
        return {**meta_check, "action": "build-closure-manifest"}
    units = []
    for item in delivery_set:
        if not isinstance(item, dict):
            continue
        units.append(
            {
                "unitId": item.get("unitId"),
                "artifactType": item.get("artifactType"),
                "priorState": item.get("priorState"),
                "resultingState": item.get("resultingState"),
                "closureProvenance": {
                    "action": item.get("action"),
                    "verdict": item.get("verdict"),
                    "mergeSha": str(merge_sha).lower(),
                    "prdUnitId": prd_unit_id,
                },
            }
        )
    manifest = {"version": 1, "prdUnitId": prd_unit_id, "mergeSha": merge_sha.lower(), "deliverySet": units, "unitCount": len(units), "writtenAt": utc_now(), "provenance": provenance or {}}
    if pr_number is not None:
        manifest["prNumber"] = int(pr_number)
    if closure_result:
        manifest["closureAudit"] = {"verdict": closure_result.get("verdict"), "considered": closure_result.get("considered"), "closed": closure_result.get("closed"), "skipped": closure_result.get("skipped"), "openRemaining": closure_result.get("openRemaining")}
    return manifest


def persist_closure_manifest(root: Path, manifest, *, dry_run=False):
    prd_unit_id = str(manifest.get("prdUnitId") or "")
    merge_sha = str(manifest.get("mergeSha") or "")
    meta_check = validate_metadata_payload({"prdUnitId": prd_unit_id, "mergeSha": merge_sha}, fields=["prdUnitId", "mergeSha"])
    if meta_check.get("verdict") != "pass":
        return {**meta_check, "action": "persist-closure-manifest"}
    path = manifest_path(root, prd_unit_id)
    if dry_run:
        return {"verdict": "pass", "action": "persist-closure-manifest", "dryRun": True, "path": str(path), "manifest": manifest}
    write_json(path, manifest)
    return {"verdict": "pass", "action": "persist-closure-manifest", "path": str(path), "prdUnitId": prd_unit_id, "mergeSha": merge_sha}


def load_closure_manifest(root: Path, prd_unit_id: str):
    data = read_json(manifest_path(root, prd_unit_id))
    return data if data else None


REVERT_TAXONOMY: dict[str, Any] = {
    "patterns": [
        {"id": "git-revert-merge-pr", "description": 'Revert "Merge pull request #N …" commit messages'},
        {"id": "git-revert-squash-pr", "description": 'Revert "… (#N)" squash-merge subject lines'},
        {"id": "git-revert-prefix", "description": 'Any commit message beginning with Revert "'},
        {"id": "structural-merge-absent", "description": "Recorded merge SHA no longer ancestor of default HEAD"},
    ],
    "limits": [
        "Only git-revert-style messages and structural merge-absence are recognized.",
        "Force-pushed history rewrites without a revert commit are out of scope.",
        "Reopen is provenance-scoped to the closure manifest delivery set for the reverted merge.",
    ],
}

_REVERT_MERGE_PR_RE = re.compile(r'^Revert "Merge pull request #(\d+)', re.I)
_REVERT_SQUASH_PR_RE = re.compile(r'^Revert ".+\(#(\d+)\)"', re.I)
_REVERT_PREFIX_RE = re.compile(r'^Revert "', re.I)


def revert_taxonomy() -> dict[str, Any]:
    return dict(REVERT_TAXONOMY)


def extract_revert_pr_numbers(message: str) -> list[int]:
    found: set[int] = set()
    for pattern in (_REVERT_MERGE_PR_RE, _REVERT_SQUASH_PR_RE):
        match = pattern.match(message.strip())
        if match:
            found.add(int(match.group(1)))
    return sorted(found)


def detect_revert_from_event(event: dict[str, Any]) -> dict[str, Any]:
    """Recognizable-revert taxonomy (PRD 070 R12/R18)."""
    if not event:
        return {"verdict": "none", "action": "detect-revert", "recognized": False}
    head = event.get("head_commit") or {}
    message = str(head.get("message") or "")
    pr_numbers = extract_revert_pr_numbers(message)
    recognized = bool(pr_numbers) or bool(_REVERT_PREFIX_RE.match(message.strip()))
    taxonomy_ids: list[str] = []
    if pr_numbers:
        taxonomy_ids.append("git-revert-merge-pr" if _REVERT_MERGE_PR_RE.match(message.strip()) else "git-revert-squash-pr")
    elif _REVERT_PREFIX_RE.match(message.strip()):
        taxonomy_ids.append("git-revert-prefix")
    return {
        "verdict": "revert" if recognized else "none",
        "action": "detect-revert",
        "recognized": recognized,
        "prNumbers": pr_numbers,
        "taxonomyIds": taxonomy_ids,
        "message": message[:200],
        "limits": REVERT_TAXONOMY["limits"],
    }


def _default_branch_name(cfg: dict[str, Any]) -> str:
    branch = str(cfg.get("defaultBaseBranch") or "main").strip()
    return branch or "main"


def merge_sha_on_default(root: Path, merge_sha: str, *, cfg: dict[str, Any] | None = None) -> bool:
    cfg = cfg or load_workflow_config(root)
    default = _default_branch_name(cfg)
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", f"refs/heads/{default}"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", default],
            capture_output=True,
            text=True,
        )
    default_sha = proc.stdout.strip().lower() if proc.returncode == 0 else ""
    merge_sha = str(merge_sha or "").lower()
    if not default_sha or not merge_sha:
        return False
    anc = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", merge_sha, default_sha],
        capture_output=True,
    )
    return anc.returncode == 0


def list_closure_manifests(root: Path) -> list[dict[str, Any]]:
    manifests_dir = closeout_root(root) / MANIFEST_DIR
    if not manifests_dir.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for manifest_file in sorted(manifests_dir.glob("*.json")):
        data = read_json(manifest_file)
        if data:
            data = dict(data)
            data["_path"] = str(manifest_file)
            out.append(data)
    return out


def clear_close_marker(root: Path, prd_unit_id: str, *, merge_sha: str | None = None) -> dict[str, Any]:
    path = close_marker_path(root, prd_unit_id)
    marker = load_close_marker(root, prd_unit_id)
    if not marker:
        return {"verdict": "pass", "action": "clear-close-marker", "noop": True}
    if merge_sha and str(marker.get("mergeSha") or "").lower() != str(merge_sha).lower():
        return {"verdict": "pass", "action": "clear-close-marker", "noop": True, "reason": "merge-sha-mismatch"}
    if path.is_file():
        path.unlink()
    return {"verdict": "pass", "action": "clear-close-marker", "prdUnitId": prd_unit_id, "cleared": True}


def unit_carries_delivery_provenance(unit_entry: dict[str, Any], manifest: dict[str, Any]) -> bool:
    provenance = unit_entry.get("closureProvenance") or {}
    manifest_sha = str(manifest.get("mergeSha") or "").lower()
    manifest_unit = str(manifest.get("prdUnitId") or "")
    if provenance.get("mergeSha") and str(provenance.get("mergeSha")).lower() != manifest_sha:
        return False
    if provenance.get("prdUnitId") and str(provenance.get("prdUnitId")) != manifest_unit:
        return False
    return True


def _superseded_by_active_delivery(root: Path, unit_id: str, manifest: dict[str, Any], *, cfg: dict[str, Any]) -> bool:
    reverting_sha = str(manifest.get("mergeSha") or "").lower()
    reverting_at = str(manifest.get("writtenAt") or "")
    for other in list_closure_manifests(root):
        other_sha = str(other.get("mergeSha") or "").lower()
        if not other_sha or other_sha == reverting_sha:
            continue
        if not merge_sha_on_default(root, other_sha, cfg=cfg):
            continue
        other_units = {str(item.get("unitId") or "") for item in (other.get("deliverySet") or [])}
        if unit_id not in other_units:
            continue
        if str(other.get("writtenAt") or "") >= reverting_at:
            return True
    return False


def _reopen_labels_for_unit(unit_entry: dict[str, Any], record: Any) -> tuple[list[str], str]:
    from planning_canonical import (
        GAP_LABEL_OPEN,
        GAP_LABEL_RESOLVED,
        GAP_LABEL_SCHEDULED,
        gap_status_label,
        status_from_labels,
        status_label,
    )

    artifact_type = str(unit_entry.get("artifactType") or "")
    prior = str(unit_entry.get("priorState") or "open")
    labels = [label for label in list(getattr(record, "labels", []) or []) if not label.startswith("sw:status:")]
    labels = [label for label in labels if label not in {GAP_LABEL_RESOLVED, GAP_LABEL_SCHEDULED}]
    if artifact_type == "gap":
        gap_label = gap_status_label(prior if prior in {"open", "planned", "scheduled", "resolved"} else "open")
        if gap_label:
            labels.append(gap_label)
        if GAP_LABEL_OPEN not in labels:
            labels.append(GAP_LABEL_OPEN)
        return sorted(set(labels)), "open"
    target_status = prior if prior not in ("closed", "complete", "unknown") else "open"
    if status_from_labels(list(getattr(record, "labels", []) or [])) == "complete":
        labels = [label for label in labels if not label.startswith("sw:status:")]
    labels.append(status_label(target_status))
    return sorted(set(labels)), "open"


def reopen_delivery_units(
    root: Path,
    manifest: dict[str, Any],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    from planning_store import IssueStoreBackend, get_backend, _lookup_issue_record

    cfg = load_workflow_config(root)
    prd_unit_id = str(manifest.get("prdUnitId") or "")
    merge_sha = str(manifest.get("mergeSha") or "").lower()
    backend = get_backend(root, cfg, override="issue-store")
    if not isinstance(backend, IssueStoreBackend):
        return {"verdict": "fail", "action": "reopen-delivery-units", "error": "issue-store-backend-required"}

    reopened: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for unit_entry in manifest.get("deliverySet") or []:
        if not isinstance(unit_entry, dict):
            continue
        unit_id = str(unit_entry.get("unitId") or "")
        if not unit_id:
            continue
        if not unit_carries_delivery_provenance(unit_entry, manifest):
            skipped.append({"unitId": unit_id, "reason": "provenance-mismatch"})
            continue
        if _superseded_by_active_delivery(root, unit_id, manifest, cfg=cfg):
            skipped.append({"unitId": unit_id, "reason": "superseded-by-active-delivery"})
            continue
        artifact_type = str(unit_entry.get("artifactType") or "")
        body_path = unit_entry.get("bodyPath") or ""
        record = _lookup_issue_record(backend, unit_id, str(body_path))
        if record is None:
            skipped.append({"unitId": unit_id, "reason": "unit-not-found"})
            continue
        if str(getattr(record, "state", "") or "") != "closed":
            skipped.append({"unitId": unit_id, "reason": "already-open"})
            continue
        target_labels, target_state = _reopen_labels_for_unit(unit_entry, record)
        if dry_run:
            reopened.append(
                {
                    "unitId": unit_id,
                    "artifactType": artifact_type,
                    "action": "would-reopen",
                    "priorState": unit_entry.get("priorState"),
                }
            )
            continue
        try:
            updated = backend._client.issue_update(
                record.id,
                labels=target_labels,
                state=target_state,
                if_match=record.etag,
                allow_locked=True,
            )
        except Exception as exc:  # noqa: BLE001
            skipped.append({"unitId": unit_id, "reason": "reopen-failed", "error": str(exc)})
            continue
        reopened.append(
            {
                "unitId": unit_id,
                "artifactType": artifact_type,
                "action": "reopen",
                "issueId": updated.id,
                "state": updated.state,
            }
        )

    marker_clear = {"noop": True}
    if reopened and not dry_run:
        marker_clear = clear_close_marker(root, prd_unit_id, merge_sha=merge_sha)

    return {
        "verdict": "ready" if reopened else "noop",
        "action": "reopen-delivery-units",
        "prdUnitId": prd_unit_id,
        "mergeSha": merge_sha,
        "dryRun": dry_run,
        "reopened": reopened,
        "skipped": skipped,
        "markerClear": marker_clear,
        "resumeCommand": (
            f"python3 scripts/deliver_closeout.py reconcile-safety --prd-unit {prd_unit_id}"
            if skipped and reopened
            else None
        ),
    }


def handle_delivery_revert(
    root: Path,
    *,
    manifest: dict[str, Any],
    dry_run: bool = False,
    source: str = "revert-detect",
) -> dict[str, Any]:
    merge_sha = str(manifest.get("mergeSha") or "").lower()
    cfg = load_workflow_config(root)
    if merge_sha_on_default(root, merge_sha, cfg=cfg):
        return {
            "verdict": "noop",
            "action": "handle-delivery-revert",
            "reason": "merge-still-on-default",
            "mergeSha": merge_sha,
            "source": source,
        }
    reopen = reopen_delivery_units(root, manifest, dry_run=dry_run)
    return {
        "verdict": reopen.get("verdict"),
        "action": "handle-delivery-revert",
        "source": source,
        "mergeSha": merge_sha,
        "prdUnitId": manifest.get("prdUnitId"),
        "reopen": reopen,
        "taxonomy": revert_taxonomy(),
    }


def reconcile_missed_reverts(
    root: Path,
    *,
    dry_run: bool = False,
    event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = load_workflow_config(root)
    handled: list[dict[str, Any]] = []
    revert_detect = detect_revert_from_event(event or {})
    if revert_detect.get("recognized") and revert_detect.get("prNumbers"):
        for pr_number in revert_detect["prNumbers"]:
            resolution = resolve_delivery_for_pr(root, pr_number)
            if resolution.get("verdict") != "pass":
                continue
            prd_unit_id = str(resolution.get("prdUnitId") or "")
            manifest = load_closure_manifest(root, prd_unit_id)
            if not manifest:
                continue
            handled.append(
                handle_delivery_revert(
                    root,
                    manifest=manifest,
                    dry_run=dry_run,
                    source="ci-revert-event",
                )
            )

    for manifest in list_closure_manifests(root):
        merge_sha = str(manifest.get("mergeSha") or "").lower()
        prd_unit_id = str(manifest.get("prdUnitId") or "")
        if not merge_sha or not prd_unit_id:
            continue
        marker = load_close_marker(root, prd_unit_id)
        if not marker:
            continue
        if str(marker.get("mergeSha") or "").lower() != merge_sha:
            continue
        if merge_sha_on_default(root, merge_sha, cfg=cfg):
            continue
        if any(
            item.get("prdUnitId") == prd_unit_id and item.get("source") == "structural-missed-revert"
            for item in handled
        ):
            continue
        handled.append(
            handle_delivery_revert(
                root,
                manifest=manifest,
                dry_run=dry_run,
                source="structural-missed-revert",
            )
        )

    if not handled:
        return {"verdict": "noop", "action": "reconcile-missed-reverts", "handled": [], "revertDetect": revert_detect}
    verdicts = {str(item.get("verdict") or "noop") for item in handled}
    verdict = "ready" if "ready" in verdicts else "noop"
    return {
        "verdict": verdict,
        "action": "reconcile-missed-reverts",
        "handled": handled,
        "revertDetect": revert_detect,
        "resumeCommand": next(
            (item.get("reopen", {}).get("resumeCommand") for item in handled if item.get("reopen", {}).get("resumeCommand")),
            None,
        ),
    }


def _load_github_event_from_env() -> dict[str, Any]:
    path = os.environ.get("GITHUB_EVENT_PATH", "").strip()
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _terminal_pr_abandoned(
    root: Path,
    state: dict[str, Any],
    *,
    pr_probe: Callable[[Path, int], dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    completion = state.get("completion") or {}
    if completion.get("status") != "completed-pending-merge":
        return None
    terminal = state.get("terminalPr") or {}
    pr_number = terminal.get("number")
    if pr_number is None:
        return None

    def default_probe(r: Path, number: int) -> dict[str, Any]:
        from host_lib import host_verb

        viewed = host_verb(r, "pr-view", number=str(number))
        if viewed.get("verdict") != "ok":
            return {"verdict": "unknown", "state": None}
        payload = viewed.get("data") or {}
        return {"verdict": "ok", "state": str(payload.get("state") or "").upper()}

    probe = pr_probe or default_probe
    info = probe(root, int(pr_number))
    pr_state = str(info.get("state") or "").upper()
    if pr_state == "MERGED":
        return None
    if pr_state == "CLOSED":
        slug = str((state.get("target") or {}).get("slug") or "")
        return {
            "verdict": "surface",
            "action": "abandoned-terminal-pr",
            "prNumber": int(pr_number),
            "prState": pr_state,
            "deliverySlug": slug,
            "completionStatus": completion.get("status"),
            "resumeCommand": (
                f"Review terminal PR #{pr_number} for delivery {slug}: closed without merge while "
                "completed-pending-merge — operator decision required (no auto-remediation)."
            ),
        }
    return None


def reconcile_abandoned_deliveries(
    root: Path,
    *,
    pr_probe: Callable[[Path, int], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from wave_state import enumerate_scoped_runs

    surfaced: list[dict[str, Any]] = []
    for run in enumerate_scoped_runs(root):
        state_path = root / str(run["statePath"])
        if not state_path.is_file():
            continue
        state = read_json(state_path)
        finding = _terminal_pr_abandoned(root, state, pr_probe=pr_probe)
        if finding:
            finding["runSlug"] = str(run.get("slug") or "")
            finding["statePath"] = str(run["statePath"])
            surfaced.append(finding)
    if not surfaced:
        return {"verdict": "noop", "action": "reconcile-abandoned-deliveries", "surfaced": []}
    return {
        "verdict": "surface",
        "action": "reconcile-abandoned-deliveries",
        "surfaced": surfaced,
        "resumeCommand": surfaced[0].get("resumeCommand"),
        "operatorDecisionRequired": True,
    }


def reconcile_closeout_safety_at_entry(
    root: Path,
    *,
    event: dict[str, Any] | None = None,
    dry_run: bool = False,
    pr_probe: Callable[[Path, int], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """On-demand safety reconciliation at CI/workflow entry (PRD 070 R12/R18/R30)."""
    event = event if event is not None else _load_github_event_from_env()
    missed = reconcile_missed_reverts(root, dry_run=dry_run, event=event)
    abandoned = reconcile_abandoned_deliveries(root, pr_probe=pr_probe)
    verdict = "ready" if missed.get("verdict") == "ready" else abandoned.get("verdict", "noop")
    if missed.get("verdict") == "noop" and abandoned.get("verdict") == "noop":
        verdict = "noop"
    return {
        "verdict": verdict,
        "action": "reconcile-closeout-safety",
        "missedReverts": missed,
        "abandonedDeliveries": abandoned,
        "revertTaxonomy": revert_taxonomy(),
        "resumeCommand": abandoned.get("resumeCommand") or missed.get("resumeCommand"),
    }




def _prior_state_from_record(record, artifact_type: str) -> str:
    if record is None:
        return "unknown"
    labels = list(getattr(record, "labels", []) or [])
    state = str(getattr(record, "state", "") or "")
    if state == "closed" or "status:complete" in labels or "status:resolved" in labels:
        return "closed"
    return "open"


def run_closeout(root: Path, *, prd_unit_id, merge_sha, pr_number=None, dry_run=False, state=None):
    if os.environ.get("SW_CLOSEOUT_TRIGGER", "").startswith("ci") and not os.environ.get("SW_CLOSEOUT_SAFETY_DONE"):
        os.environ["SW_CLOSEOUT_SAFETY_DONE"] = "1"
        reconcile_closeout_safety_at_entry(root, dry_run=dry_run)
    meta = validate_metadata_payload({"prdUnitId": prd_unit_id, "mergeSha": merge_sha, **({"prNumber": str(pr_number)} if pr_number is not None else {})}, fields=["prdUnitId", "mergeSha"] + (["prNumber"] if pr_number is not None else []))
    if meta.get("verdict") != "pass":
        return {**meta, "action": "run-closeout"}
    from planning_store import close_delivery_units, get_backend, resolve_delivery_linked_units, IssueStoreBackend, _lookup_issue_record
    cfg = load_workflow_config(root)
    snapshot = resolve_delivery_linked_units(root, cfg, prd_unit_id)
    if snapshot.get("verdict") != "ok":
        return {**snapshot, "action": "run-closeout"}
    delivery_set = []
    backend = get_backend(root, cfg, override="issue-store")
    if isinstance(backend, IssueStoreBackend):
        for unit in snapshot.get("snapshot") or []:
            record = _lookup_issue_record(backend, unit["unitId"], unit["bodyPath"])
            delivery_set.append({**unit, "priorState": _prior_state_from_record(record, unit.get("artifactType", ""))})
    closure = close_delivery_units(root, cfg, prd_unit_id, dry_run=dry_run, state=state)
    manifest = build_closure_manifest(prd_unit_id=prd_unit_id, merge_sha=merge_sha, delivery_set=delivery_set, closure_result=closure, pr_number=pr_number, provenance={"trigger": os.environ.get("SW_CLOSEOUT_TRIGGER", "manual"), "dryRun": dry_run})
    persisted = persist_closure_manifest(root, manifest, dry_run=dry_run)
    verdict = closure.get("verdict", "not-ready")
    if persisted.get("verdict") != "pass":
        verdict = "not-ready"
    return {"verdict": verdict, "action": "run-closeout", "prdUnitId": prd_unit_id, "mergeSha": merge_sha.lower(), "dryRun": dry_run, "closure": closure, "manifest": manifest, "manifestPersist": persisted, "resumeCommand": closure.get("resumeCommand")}


def run_closeout_idempotent(
    root: Path,
    *,
    prd_unit_id: str,
    merge_sha: str,
    pr_number=None,
    dry_run: bool = False,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = load_workflow_config(root)
    short = short_circuit_closeout(root, cfg, prd_unit_id, merge_sha, state=state)
    if short:
        return short
    result = run_closeout(
        root,
        prd_unit_id=prd_unit_id,
        merge_sha=merge_sha,
        pr_number=pr_number,
        dry_run=dry_run,
        state=state,
    )
    if result.get("verdict") == "ready" and not dry_run:
        closure = result.get("closure") or {}
        audit = closure.get("closureAudit") or {}
        if audit.get("verdict") == "ready":
            write_close_marker(root, prd_unit_id, merge_sha, audit=audit)
    return result


def self_wake_poll_once(
    root: Path,
    run_id: str,
    *,
    state: dict[str, Any] | None = None,
    merge_probe: Callable[[Path, dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from wave_compound import target_merge_detected

    if state is None:
        state, _state_path, _slug = resolve_state_by_run_id(root, run_id)
    if not state:
        return {"verdict": "fail", "action": "self-wake-poll", "error": "run-id-not-found", "runId": run_id}
    emit_self_wake_sentinel(run_id)
    probe = merge_probe or target_merge_detected
    merge_info = probe(root, state)
    if not is_pending_merge_completion(state):
        return {
            "verdict": "wait",
            "action": "self-wake-poll",
            "runId": run_id,
            "mergeDetected": bool(merge_info.get("merged")),
            "completionGate": "not-pending-merge",
        }
    if not merge_info.get("merged"):
        return {
            "verdict": "wait",
            "action": "self-wake-poll",
            "runId": run_id,
            "mergeDetected": False,
            "completionGate": "completed-pending-merge",
        }
    prd_unit_id = prd_unit_id_from_state(state)
    if not prd_unit_id:
        return {"verdict": "fail", "action": "self-wake-poll", "error": "prd-unit-unresolved", "runId": run_id}
    merge_sha = extract_merge_sha(root, merge_info)
    if not merge_sha:
        return {"verdict": "fail", "action": "self-wake-poll", "error": "merge-sha-unresolved", "runId": run_id}
    pr_number = merge_info.get("prNumber") or (state.get("terminalPr") or {}).get("number")
    closeout = run_closeout_idempotent(
        root,
        prd_unit_id=prd_unit_id,
        merge_sha=merge_sha,
        pr_number=int(pr_number) if pr_number is not None else None,
        state=state,
    )
    return {
        "verdict": closeout.get("verdict"),
        "action": "self-wake-closeout",
        "runId": run_id,
        "mergeDetected": True,
        "prdUnitId": prd_unit_id,
        "mergeSha": merge_sha,
        "closeout": closeout,
        "noop": bool(closeout.get("noop")),
    }


def self_wake_poll_loop(
    root: Path,
    run_id: str,
    *,
    sleep_fn: Callable[[float], None] | None = None,
    merge_probe: Callable[[Path, dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cfg = load_workflow_config(root)
    watch = watch_config(cfg)
    poll_seconds = watch["pollSeconds"]
    deadline = time.monotonic() + (watch["maxWaitMinutes"] * 60)
    attempts = 0
    sleeper = sleep_fn or time.sleep
    last: dict[str, Any] = {"verdict": "wait", "action": "self-wake-poll", "runId": run_id}
    while time.monotonic() < deadline:
        last = self_wake_poll_once(root, run_id, merge_probe=merge_probe)
        attempts += 1
        if last.get("verdict") in ("ready", "fail", "not-ready"):
            last["attempts"] = attempts
            return last
        sleeper(poll_seconds)
    last["verdict"] = "wait-exhausted"
    last["attempts"] = attempts
    return last


def mapping_from_deliver_state(state, pr_info):
    pr_number = pr_info.get("number")
    if pr_number is None:
        return {"verdict": "fail", "error": "pr-number-missing"}
    prd_unit = prd_unit_id_from_state(state) or ""
    target = state.get("target") or {}
    slug = str(target.get("slug") or "")
    branch = str(target.get("branch") or "")
    prd_number = str(state.get("prd_number") or "").zfill(3)
    head = str(pr_info.get("head") or pr_info.get("headRefOid") or "")
    return {"prNumber": str(pr_number), "prUrl": str(pr_info.get("url") or ""), "prdUnitId": prd_unit, "prdNumber": prd_number, "deliverySlug": slug, "targetBranch": branch, "headSha": head, "runSlug": slug}


def _parse_kv(args, flag):
    if flag in args:
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else None
    return None


def main():
    parser = argparse.ArgumentParser(description="Deliver close-out driver (PRD 070)")
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("command", nargs="?", default="help")
    parser.add_argument("rest", nargs=argparse.REMAINDER)
    ns = parser.parse_args()
    root = Path(ns.root).resolve()
    cmd = ns.command
    rest = list(ns.rest)
    if cmd in ("record-mapping", "mapping", "record-pr-delivery-mapping"):
        pr = _parse_kv(rest, "--pr-number")
        if not pr:
            fail("--pr-number required")
        state = load_deliver_state(root)
        payload = mapping_from_deliver_state(state, {"number": int(pr), "url": _parse_kv(rest, "--pr-url") or "", "head": _parse_kv(rest, "--head") or ""})
        if payload.get("verdict") == "fail":
            fail(str(payload.get("error")))
        emit(record_pr_delivery_mapping(root, payload, dry_run="--dry-run" in rest), 0)
    elif cmd in ("resolve", "resolve-delivery"):
        pr = _parse_kv(rest, "--pr-number")
        merge_sha = _parse_kv(rest, "--merge-sha")
        if pr:
            result = resolve_delivery_for_pr(root, pr)
        elif merge_sha:
            result = resolve_delivery_for_merge(root, merge_sha=merge_sha)
        else:
            fail("--pr-number or --merge-sha required")
        emit(result, 0 if result.get("verdict") == "pass" else 20)
    elif cmd in ("run", "closeout"):
        prd_unit = _parse_kv(rest, "--prd-unit")
        merge_sha = _parse_kv(rest, "--merge-sha")
        if not prd_unit or not merge_sha:
            fail("--prd-unit and --merge-sha required")
        pr_raw = _parse_kv(rest, "--pr-number")
        pr_number = int(pr_raw) if pr_raw else None
        state = load_deliver_state(root)
        result = run_closeout(root, prd_unit_id=prd_unit, merge_sha=merge_sha, pr_number=pr_number, dry_run="--dry-run" in rest, state=state)
        emit(result, 0 if result.get("verdict") in ("ready", "dry-run") else 20)
    elif cmd in ("self-wake-poll", "self-wake"):
        run_id = _parse_kv(rest, "--run-id")
        if not run_id:
            fail("--run-id required")
        if "--loop" in rest:
            result = self_wake_poll_loop(root, run_id)
        else:
            result = self_wake_poll_once(root, run_id)
        emit(result, 0 if result.get("verdict") in ("ready", "wait", "wait-exhausted") else 20)
    elif cmd in ("reconcile-safety", "reconcile"):
        event_path = _parse_kv(rest, "--event-path")
        event = json.loads(Path(event_path).read_text(encoding="utf-8")) if event_path else None
        result = reconcile_closeout_safety_at_entry(root, event=event, dry_run="--dry-run" in rest)
        emit(result, 0 if result.get("verdict") in ("ready", "noop", "surface") else 20)
    elif cmd == "validate-metadata":
        raw = _parse_kv(rest, "--json")
        if not raw:
            fail("--json required")
        result = validate_metadata_payload(json.loads(raw))
        emit(result, 0 if result.get("verdict") == "pass" else 20)
    else:
        fail(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
