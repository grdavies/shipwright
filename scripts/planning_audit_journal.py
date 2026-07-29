#!/usr/bin/env python3
"""PRD 082 phase 9 — hash-chained authority audit journal (R26)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from host_lib import load_workflow_config
import planning_visibility as pv

AUDIT_JOURNAL_SCHEMA_VERSION = 1
DEFAULT_AUDIT_JOURNAL_REL = Path(".cursor") / "sw-authority-audit-journal"
JOURNAL_FILENAME = "journal.jsonl"
GENESIS_DIGEST = "0" * 64
JOURNAL_DIR_MODE = 0o700
JOURNAL_FILE_MODE = 0o600

TRANSITION_AUTHORITY_DISABLE = "authority-disable"
TRANSITION_AUTHORITY_ENABLE = "authority-enable"
TRANSITION_AUTHORITY_BLOCK = "authority-block"
TRANSITION_SPLIT_BRAIN = "split-brain-detected"
TRANSITION_SENSITIVITY_DECLASSIFICATION = "sensitivity-declassification"
TRANSITION_LEDGER_PURGE = "ledger-purge"

AUTHORITY_TRANSITIONS = frozenset(
    {
        TRANSITION_AUTHORITY_DISABLE,
        TRANSITION_AUTHORITY_ENABLE,
        TRANSITION_AUTHORITY_BLOCK,
        TRANSITION_SPLIT_BRAIN,
        TRANSITION_SENSITIVITY_DECLASSIFICATION,
        TRANSITION_LEDGER_PURGE,
    }
)

BODY_FIELD_NAMES = frozenset(
    {
        "body",
        "content",
        "intendedBody",
        "redactedBody",
        "displayBody",
        "unitBody",
        "markdown",
        "text",
    }
)

CHAIN_INVALID_ERROR = "audit-journal-chain-invalid"
CHAIN_MISSING_ERROR = "audit-journal-chain-missing"


class AuditJournalError(RuntimeError):
    """Authority audit journal contract violation."""


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def audit_journal_section(cfg: dict[str, Any]) -> dict[str, Any]:
    planning = cfg.get("planning")
    if not isinstance(planning, dict):
        return {}
    section = planning.get("auditJournal")
    return section if isinstance(section, dict) else {}


def resolve_journal_dir(root: Path, cfg: dict[str, Any] | None = None) -> Path:
    cfg = cfg if cfg is not None else load_workflow_config(root)
    section = audit_journal_section(cfg)
    rel = section.get("path", str(DEFAULT_AUDIT_JOURNAL_REL))
    if not isinstance(rel, str) or not rel.strip():
        rel = str(DEFAULT_AUDIT_JOURNAL_REL)
    candidate = Path(rel.strip())
    return candidate if candidate.is_absolute() else (root / candidate)


def journal_path(root: Path, cfg: dict[str, Any] | None = None) -> Path:
    return resolve_journal_dir(root, cfg) / JOURNAL_FILENAME


def _assert_owner_only_path(path: Path) -> None:
    owner = os.getuid()
    if path.is_symlink():
        raise AuditJournalError(f"audit-journal path must not be symlinked: {path}")
    if not path.exists():
        return
    stat = path.stat()
    if stat.st_uid != owner:
        raise AuditJournalError(f"audit-journal path must be owned by current user: {path}")
    mode = stat.st_mode & 0o777
    if path.is_file() and mode != JOURNAL_FILE_MODE:
        raise AuditJournalError(f"audit-journal file must be mode {oct(JOURNAL_FILE_MODE)}")
    if path.is_dir() and mode != JOURNAL_DIR_MODE:
        raise AuditJournalError(f"audit-journal directory must be mode {oct(JOURNAL_DIR_MODE)}")


def ensure_journal_layout(root: Path, cfg: dict[str, Any] | None = None) -> Path:
    journal_dir = resolve_journal_dir(root, cfg)
    journal_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(journal_dir, JOURNAL_DIR_MODE)
    path = journal_dir / JOURNAL_FILENAME
    if not path.exists():
        path.touch()
        os.chmod(path, JOURNAL_FILE_MODE)
    _assert_owner_only_path(journal_dir)
    _assert_owner_only_path(path)
    return path


def _redact_committed_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    destination = pv.resolve_emission_destination("index-active")
    payload = json.dumps(metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    proc = subprocess.run(
        [str(SCRIPT_DIR / "memory-redact.py"), "--destination", destination],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AuditJournalError(proc.stderr.strip() or "memory-redact failed")
    redacted = json.loads(proc.stdout)
    if not isinstance(redacted, dict):
        raise AuditJournalError("redacted metadata must be a JSON object")
    return redacted


def _scrub_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in metadata.items():
        if key in BODY_FIELD_NAMES:
            raise AuditJournalError(f"audit-journal metadata must not carry body field: {key}")
        if isinstance(value, str) and len(value) > 4096:
            cleaned[key] = hashlib.sha256(value.encode("utf-8")).hexdigest()
            cleaned[f"{key}Digest"] = cleaned[key]
            continue
        if isinstance(value, dict):
            cleaned[key] = _scrub_metadata(value)
            continue
        if isinstance(value, list):
            cleaned[key] = [
                _scrub_metadata(item) if isinstance(item, dict) else item for item in value
            ]
            continue
        cleaned[key] = value
    return _redact_committed_metadata(cleaned)


def _entry_digest(entry: dict[str, Any]) -> str:
    body = {k: v for k, v in entry.items() if k != "digest"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_entries(path: Path) -> list[dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        return []
    entries: list[dict[str, Any]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AuditJournalError(f"audit-journal line {line_no}: invalid json") from exc
        if not isinstance(parsed, dict):
            raise AuditJournalError(f"audit-journal line {line_no}: entry must be object")
        entries.append(parsed)
    return entries


def _write_entries(path: Path, entries: list[dict[str, Any]]) -> None:
    payload = "\n".join(
        json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        for entry in entries
    )
    if payload:
        payload += "\n"
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.chmod(tmp, JOURNAL_FILE_MODE)
    tmp.replace(path)


def verify_chain(root: Path, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    path = journal_path(root, cfg)
    if not path.is_file() or path.stat().st_size == 0:
        return {
            "verdict": "ok",
            "action": "verify-chain",
            "chainState": "empty",
            "entryCount": 0,
            "journalPath": str(path),
        }
    try:
        entries = _load_entries(path)
    except AuditJournalError as exc:
        return {
            "verdict": "fail",
            "action": "verify-chain",
            "error": CHAIN_INVALID_ERROR,
            "cause": str(exc),
            "journalPath": str(path),
        }
    prev_digest = GENESIS_DIGEST
    for index, entry in enumerate(entries, start=1):
        for forbidden in BODY_FIELD_NAMES:
            if forbidden in entry or forbidden in (entry.get("metadata") or {}):
                return {
                    "verdict": "fail",
                    "action": "verify-chain",
                    "error": CHAIN_INVALID_ERROR,
                    "cause": f"entry {index} carries forbidden body field",
                    "journalPath": str(path),
                }
        if entry.get("prevDigest") != prev_digest:
            return {
                "verdict": "fail",
                "action": "verify-chain",
                "error": CHAIN_INVALID_ERROR,
                "cause": f"entry {index} prevDigest mismatch",
                "journalPath": str(path),
            }
        expected = _entry_digest(entry)
        actual = str(entry.get("digest") or "")
        if actual != expected:
            return {
                "verdict": "fail",
                "action": "verify-chain",
                "error": CHAIN_INVALID_ERROR,
                "cause": f"entry {index} digest mismatch",
                "journalPath": str(path),
            }
        prev_digest = actual
    return {
        "verdict": "ok",
        "action": "verify-chain",
        "chainState": "valid",
        "entryCount": len(entries),
        "headDigest": prev_digest if entries else GENESIS_DIGEST,
        "journalPath": str(path),
    }


def require_valid_chain(root: Path, cfg: dict[str, Any] | None = None) -> dict[str, Any] | None:
    result = verify_chain(root, cfg)
    if result.get("verdict") == "ok":
        return None
    return {
        "verdict": "fail",
        "action": "require-valid-chain",
        "error": result.get("error") or CHAIN_INVALID_ERROR,
        "cause": result.get("cause"),
        "verify": result,
    }


def append_transition(
    root: Path,
    transition: str,
    metadata: dict[str, Any] | None = None,
    *,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if transition not in AUTHORITY_TRANSITIONS:
        return {
            "verdict": "fail",
            "action": "append-transition",
            "error": "audit-journal-unknown-transition",
            "transition": transition,
        }
    blocked = require_valid_chain(root, cfg)
    if blocked is not None:
        return {**blocked, "action": "append-transition", "transition": transition}
    cfg = cfg if cfg is not None else load_workflow_config(root)
    path = ensure_journal_layout(root, cfg)
    entries = _load_entries(path)
    prev_digest = entries[-1]["digest"] if entries else GENESIS_DIGEST
    scrubbed = _scrub_metadata(dict(metadata or {}))
    entry: dict[str, Any] = {
        "schemaVersion": AUDIT_JOURNAL_SCHEMA_VERSION,
        "sequence": len(entries) + 1,
        "recordedAt": _utc_now(),
        "transition": transition,
        "metadata": scrubbed,
        "prevDigest": prev_digest,
    }
    entry["digest"] = _entry_digest(entry)
    entries.append(entry)
    _write_entries(path, entries)
    return {
        "verdict": "ok",
        "action": "append-transition",
        "transition": transition,
        "entry": entry,
        "journalPath": str(path),
    }


def append_authority_disable(
    root: Path,
    *,
    set_by: str,
    reason: str,
    repo_scope: str | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return append_transition(
        root,
        TRANSITION_AUTHORITY_DISABLE,
        {
            "setBy": set_by.strip(),
            "reason": reason.strip(),
            "repoScope": (repo_scope or "").strip() or None,
        },
        cfg=cfg,
    )


def append_authority_enable(
    root: Path,
    *,
    repo_scope: str | None = None,
    removed: bool = False,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return append_transition(
        root,
        TRANSITION_AUTHORITY_ENABLE,
        {
            "repoScope": (repo_scope or "").strip() or None,
            "removed": bool(removed),
        },
        cfg=cfg,
    )


def append_authority_block(
    root: Path,
    *,
    authority_state: str,
    reason: str | None,
    operation: str,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return append_transition(
        root,
        TRANSITION_AUTHORITY_BLOCK,
        {
            "authorityState": authority_state.strip(),
            "reason": (reason or "").strip() or None,
            "operation": operation.strip(),
        },
        cfg=cfg,
    )


def append_split_brain_detection(
    root: Path,
    *,
    error: str,
    action: str | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return append_transition(
        root,
        TRANSITION_SPLIT_BRAIN,
        {
            "error": error.strip(),
            "action": (action or "").strip() or None,
        },
        cfg=cfg,
    )


def append_sensitivity_declassification(
    root: Path,
    *,
    stable_id: str,
    from_tier: str,
    to_tier: str,
    approver: str,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return append_transition(
        root,
        TRANSITION_SENSITIVITY_DECLASSIFICATION,
        {
            "stableId": stable_id.strip(),
            "fromTier": from_tier.strip(),
            "toTier": to_tier.strip(),
            "approver": approver.strip(),
        },
        cfg=cfg,
    )


def append_ledger_purge(
    root: Path,
    *,
    purged_count: int,
    reason: str = "purge",
    entry_ids: list[str] | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "purgedCount": int(purged_count),
        "reason": reason.strip(),
    }
    if entry_ids:
        metadata["entryIdDigests"] = [
            hashlib.sha256(entry_id.strip().encode("utf-8")).hexdigest()
            for entry_id in entry_ids
            if entry_id.strip()
        ]
    return append_transition(root, TRANSITION_LEDGER_PURGE, metadata, cfg=cfg)


def journal_doctor_finding(root: Path, cfg: dict[str, Any] | None = None) -> dict[str, Any] | None:
    result = verify_chain(root, cfg)
    if result.get("verdict") == "ok":
        return None
    return {
        "check": "authority-audit-journal-chain",
        "status": "fail",
        "error": result.get("error") or CHAIN_INVALID_ERROR,
        "cause": result.get("cause"),
        "journalPath": result.get("journalPath"),
        "remediation": "repair or truncate the audit journal, then re-run verify",
    }
