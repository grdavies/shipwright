#!/usr/bin/env python3
"""Merge-boundary close-out: PR-to-delivery mapping, closure manifests, metadata hardening (PRD 070)."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
INDEX_REL = f"{CLOSEOUT_ROOT_REL}/index.json"

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
        units.append({"unitId": item.get("unitId"), "artifactType": item.get("artifactType"), "priorState": item.get("priorState"), "resultingState": item.get("resultingState"), "closureProvenance": {"action": item.get("action"), "verdict": item.get("verdict")}})
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


def _prior_state_from_record(record, artifact_type: str) -> str:
    if record is None:
        return "unknown"
    labels = list(getattr(record, "labels", []) or [])
    state = str(getattr(record, "state", "") or "")
    if state == "closed" or "status:complete" in labels or "status:resolved" in labels:
        return "closed"
    return "open"


def run_closeout(root: Path, *, prd_unit_id, merge_sha, pr_number=None, dry_run=False, state=None):
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
