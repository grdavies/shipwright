"""Sole redacting writer for Shipwright sw-* and shared-git-dir stores (PRD 041 R31)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from wave_json_io import StateCorruptError, read_json, write_json

import memory_redact

SCRIPT_DIR = Path(__file__).resolve().parent

STORE_SCHEMAS: dict[str, str] = {
    "failure-signatures": "core/sw-reference/failure-signature.schema.json",
    "meta-inbox-draft": "core/sw-reference/meta-inbox-draft.schema.json",
}
SHARED_GIT_DIR_STORES = frozenset({"failure-signatures"})
CURSOR_STORE_PREFIXES = (".cursor/sw-", ".cursor/sw-meta-inbox/")
WRITER_NAME = "sw_state_write_lib"
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


class StateWriteError(Exception):
    """Fail-closed writer error."""

    def __init__(self, message: str, *, halt: str = "writer-failed") -> None:
        super().__init__(message)
        self.halt = halt


def git_dir(root: Path) -> Path:
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--git-dir"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise StateWriteError(proc.stderr.strip() or "git-dir resolution failed", halt="no-git-dir")
    path = Path(proc.stdout.strip())
    if not path.is_absolute():
        path = (root / path).resolve()
    return path


def resolve_store_path(root: Path, store: str, *, rel: str | None = None) -> Path:
    if store in SHARED_GIT_DIR_STORES:
        return git_dir(root) / "shipwright-failure-signatures.json"
    if store == "meta-inbox-draft":
        if not rel:
            raise StateWriteError("--rel required for meta-inbox-draft store", halt="store-path-forbidden")
        return root / ".cursor" / "sw-meta-inbox" / rel
    if rel:
        candidate = root / rel
        rel_posix = candidate.as_posix()
        if not any(rel_posix.startswith(p.rstrip("/")) or f"{p}" in rel_posix for p in CURSOR_STORE_PREFIXES):
            raise StateWriteError(
                "refused path outside sw-* roots",
                halt="store-path-forbidden",
            )
        return candidate
    raise StateWriteError(f"unknown store: {store}", halt="store-path-forbidden")


def redact_text(text: str) -> str:
    try:
        return memory_redact.redact(text)
    except Exception as exc:
        raise StateWriteError(f"memory_redact failed: {exc}", halt="redaction-failed") from exc


def parse_json_payload(text: str) -> dict[str, Any]:
    redacted = redact_text(text)
    try:
        data = json.loads(redacted)
    except json.JSONDecodeError as exc:
        raise StateWriteError(f"invalid JSON payload: {exc}", halt="schema-invalid") from exc
    if not isinstance(data, dict):
        raise StateWriteError("payload root must be object", halt="schema-invalid")
    return data


def _validate_signature_key(key: Any) -> None:
    if not isinstance(key, dict):
        raise StateWriteError("record.key must be object", halt="schema-invalid")
    for field in ("checkId", "exitCode", "jobId", "messageClass"):
        if field not in key:
            raise StateWriteError(f"record.key missing {field}", halt="schema-invalid")
    if not isinstance(key["checkId"], str) or not key["checkId"]:
        raise StateWriteError("record.key.checkId invalid", halt="schema-invalid")
    if not isinstance(key["exitCode"], int):
        raise StateWriteError("record.key.exitCode invalid", halt="schema-invalid")
    if not isinstance(key["jobId"], str) or not key["jobId"]:
        raise StateWriteError("record.key.jobId invalid", halt="schema-invalid")
    if not isinstance(key["messageClass"], str) or not key["messageClass"]:
        raise StateWriteError("record.key.messageClass invalid", halt="schema-invalid")


def _validate_failure_record(rec: Any) -> None:
    if not isinstance(rec, dict):
        raise StateWriteError("record must be object", halt="schema-invalid")
    for field in ("key", "rawHash", "count", "runs", "firstSeen", "lastSeen", "source", "writer"):
        if field not in rec:
            raise StateWriteError(f"record missing {field}", halt="schema-invalid")
    _validate_signature_key(rec["key"])
    if not isinstance(rec["rawHash"], str) or not SHA256_RE.match(rec["rawHash"]):
        raise StateWriteError("record.rawHash invalid", halt="schema-invalid")
    if not isinstance(rec["count"], int) or rec["count"] < 1:
        raise StateWriteError("record.count invalid", halt="schema-invalid")
    if not isinstance(rec["runs"], list) or not all(isinstance(r, str) and r for r in rec["runs"]):
        raise StateWriteError("record.runs invalid", halt="schema-invalid")
    for ts_field in ("firstSeen", "lastSeen"):
        if not isinstance(rec[ts_field], str) or not rec[ts_field]:
            raise StateWriteError(f"record.{ts_field} invalid", halt="schema-invalid")
    if not isinstance(rec["source"], str) or not rec["source"]:
        raise StateWriteError("record.source invalid", halt="schema-invalid")
    if not isinstance(rec["writer"], str) or not rec["writer"]:
        raise StateWriteError("record.writer invalid", halt="schema-invalid")


def validate_failure_signatures(data: dict[str, Any]) -> None:
    if data.get("version") != 1:
        raise StateWriteError("failure-signatures version must be 1", halt="schema-invalid")
    records = data.get("records")
    if not isinstance(records, list):
        raise StateWriteError("failure-signatures records must be array", halt="schema-invalid")
    for rec in records:
        _validate_failure_record(rec)


def validate_meta_inbox_draft(data: dict[str, Any]) -> None:
    required = (
        "signalId",
        "destination",
        "gapClass",
        "title",
        "status",
        "capturedAt",
    )
    for field in required:
        if field not in data:
            raise StateWriteError(f"meta-inbox-draft missing {field}", halt="schema-invalid")
    if data.get("destination") != "meta-shipwright":
        raise StateWriteError("meta-inbox-draft destination must be meta-shipwright", halt="schema-invalid")
    if data.get("gapClass") != "plugin-self":
        raise StateWriteError("meta-inbox-draft gapClass must be plugin-self", halt="schema-invalid")
    if data.get("status") not in ("draft", "confirmed", "materialized"):
        raise StateWriteError("meta-inbox-draft status invalid", halt="schema-invalid")


def resolve_schema_path(root: Path, store: str) -> Path | None:
    schema_rel = STORE_SCHEMAS.get(store)
    if not schema_rel:
        return None
    for base in (root, root / "core", SCRIPT_DIR.parent):
        candidate = base / schema_rel
        if candidate.is_file():
            return candidate
    return None


def validate_store(root: Path, store: str, data: dict[str, Any]) -> None:
    schema_path = resolve_schema_path(root, store)
    if schema_path is None:
        if store in STORE_SCHEMAS:
            raise StateWriteError(
                f"schema missing: {STORE_SCHEMAS[store]}",
                halt="schema-missing",
            )
        return
    if store == "failure-signatures":
        validate_failure_signatures(data)
    elif store == "meta-inbox-draft":
        validate_meta_inbox_draft(data)


def load_store(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return read_json(path, absent_ok=True)
    except StateCorruptError as exc:
        raise StateWriteError(str(exc), halt="store-corrupt") from exc


def key_token(key: dict[str, Any]) -> str:
    return json.dumps(key, sort_keys=True, separators=(",", ":"))


def cmd_write(root: Path, *, store: str, data: dict[str, Any], rel: str | None = None) -> Path:
    validate_store(root, store, data)
    path = resolve_store_path(root, store, rel=rel)
    write_json(path, data)
    return path


def write_from_text(root: Path, *, store: str, text: str, rel: str | None = None) -> Path:
    data = parse_json_payload(text)
    return cmd_write(root, store=store, data=data, rel=rel)


def index_merge(root: Path, *, store: str, worktrees: list[str] | None = None) -> dict[str, Any]:
    if store != "failure-signatures":
        raise StateWriteError("index-merge only supported for failure-signatures", halt="unsupported-store")
    target_path = resolve_store_path(root, store)
    merged_records: dict[str, dict[str, Any]] = {}
    sources = [root, *[Path(w).resolve() for w in (worktrees or [])]]
    for src_root in sources:
        src_path = resolve_store_path(src_root, store)
        if not src_path.is_file():
            continue
        if src_path.resolve() == target_path.resolve() and src_root != root:
            continue
        doc = load_store(src_path)
        for rec in doc.get("records") or []:
            if not isinstance(rec, dict) or not isinstance(rec.get("key"), dict):
                continue
            token = key_token(rec["key"])
            existing = merged_records.get(token)
            if existing is None:
                merged_records[token] = dict(rec)
                continue
            runs = sorted(set(existing.get("runs") or []) | set(rec.get("runs") or []))
            existing["runs"] = runs
            existing["count"] = max(int(existing.get("count") or 1), int(rec.get("count") or 1), len(runs))
            if (rec.get("firstSeen") or "") < (existing.get("firstSeen") or "z"):
                existing["firstSeen"] = rec["firstSeen"]
            if (rec.get("lastSeen") or "") > (existing.get("lastSeen") or ""):
                existing["lastSeen"] = rec["lastSeen"]
    merged = {
        "version": 1,
        "records": sorted(merged_records.values(), key=lambda r: key_token(r["key"])),
    }
    validate_store(root, store, merged)
    write_json(target_path, merged)
    return {"path": str(target_path), "count": len(merged["records"])}
