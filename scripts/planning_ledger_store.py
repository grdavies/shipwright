#!/usr/bin/env python3
"""PRD 082 phase 6 — owner-only bounded refusal-ledger storage (R26)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from host_lib import load_workflow_config

DEFAULT_LEDGER_REL = Path(".cursor") / "sw-refusal-ledger"
DEFAULT_TTL_SECONDS = 2_592_000
DEFAULT_MAX_SIZE_BYTES = 52_428_800
LEDGER_DIR_MODE = 0o700
LEDGER_FILE_MODE = 0o600
LEDGER_SCHEMA_VERSION = 1
ENTRIES_DIR_NAME = "entries"
EVICTION_JOURNAL_NAME = "eviction-journal.json"


class LedgerStoreError(RuntimeError):
    """Refusal-ledger storage contract violation."""


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso8601(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def refusal_ledger_section(cfg: dict[str, Any]) -> dict[str, Any]:
    planning = cfg.get("planning")
    if not isinstance(planning, dict):
        return {}
    section = planning.get("refusalLedger")
    return section if isinstance(section, dict) else {}


def resolve_ledger_path(root: Path, cfg: dict[str, Any] | None = None) -> Path:
    cfg = cfg if cfg is not None else load_workflow_config(root)
    section = refusal_ledger_section(cfg)
    rel = section.get("path", str(DEFAULT_LEDGER_REL))
    if not isinstance(rel, str) or not rel.strip():
        rel = str(DEFAULT_LEDGER_REL)
    candidate = Path(rel.strip())
    return candidate if candidate.is_absolute() else (root / candidate)


def resolve_ledger_bounds(cfg: dict[str, Any]) -> tuple[int, int]:
    section = refusal_ledger_section(cfg)
    ttl = section.get("ttlSeconds", DEFAULT_TTL_SECONDS)
    max_size = section.get("maxSizeBytes", DEFAULT_MAX_SIZE_BYTES)
    try:
        ttl_seconds = int(ttl)
    except (TypeError, ValueError):
        ttl_seconds = DEFAULT_TTL_SECONDS
    try:
        max_size_bytes = int(max_size)
    except (TypeError, ValueError):
        max_size_bytes = DEFAULT_MAX_SIZE_BYTES
    return max(ttl_seconds, 3600), max(max_size_bytes, 1_048_576)


def entries_dir(ledger_dir: Path) -> Path:
    return ledger_dir / ENTRIES_DIR_NAME


def eviction_journal_path(ledger_dir: Path) -> Path:
    return ledger_dir / EVICTION_JOURNAL_NAME


def _assert_owner_only_path(path: Path) -> None:
    owner = os.getuid()
    if path.is_symlink():
        raise LedgerStoreError(f"ledger path must not be symlinked: {path}")
    if not path.exists():
        return
    stat = path.stat()
    if stat.st_uid != owner:
        raise LedgerStoreError(f"ledger path must be owned by current user: {path}")
    mode = stat.st_mode & 0o777
    if path.is_file() and mode != LEDGER_FILE_MODE:
        raise LedgerStoreError(f"ledger file must be mode {oct(LEDGER_FILE_MODE)}: {path}")
    if path.is_dir() and mode != LEDGER_DIR_MODE:
        raise LedgerStoreError(f"ledger directory must be mode {oct(LEDGER_DIR_MODE)}: {path}")


def _chmod_harden(path: Path) -> None:
    try:
        if path.is_dir():
            os.chmod(path, LEDGER_DIR_MODE)
        elif path.is_file():
            os.chmod(path, LEDGER_FILE_MODE)
    except OSError:
        pass


def path_is_gitignored(root: Path, target: Path) -> bool:
    try:
        rel = target.relative_to(root.resolve())
        rel_text = rel.as_posix()
    except ValueError:
        rel_text = target.as_posix()
    proc = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "-q", rel_text],
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


def verify_ledger_path_contract(root: Path, ledger_dir: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    warnings: list[str] = []
    if ledger_dir.is_symlink():
        checks.append({"check": "symlink", "status": "fail"})
        return {
            "verdict": "fail",
            "path": str(ledger_dir),
            "checks": checks,
            "warnings": ["symlink-rejected"],
        }
    checks.append({"check": "symlink", "status": "ok"})
    ignored = path_is_gitignored(root, ledger_dir)
    checks.append({"check": "gitignore", "status": "ok" if ignored else "fail", "ignored": ignored})
    if not ignored:
        warnings.append("ledger-path-not-gitignored")
        return {"verdict": "fail", "path": str(ledger_dir), "checks": checks, "warnings": warnings}
    if not ledger_dir.exists():
        checks.append({"check": "owner-mode", "status": "skipped", "reason": "not-created"})
        return {"verdict": "ok", "path": str(ledger_dir), "checks": checks, "warnings": warnings}
    try:
        _assert_owner_only_path(ledger_dir)
        checks.append({"check": "owner-mode", "status": "ok"})
    except LedgerStoreError as exc:
        checks.append({"check": "owner-mode", "status": "fail", "error": str(exc)})
        warnings.append(str(exc))
        return {"verdict": "fail", "path": str(ledger_dir), "checks": checks, "warnings": warnings}
    return {"verdict": "ok", "path": str(ledger_dir), "checks": checks, "warnings": warnings}


def ensure_ledger_layout(ledger_dir: Path) -> Path:
    ledger_dir.mkdir(parents=True, exist_ok=True)
    _chmod_harden(ledger_dir)
    entry_root = entries_dir(ledger_dir)
    entry_root.mkdir(parents=True, exist_ok=True)
    _chmod_harden(entry_root)
    _assert_owner_only_path(ledger_dir)
    return entry_root


def _entry_file_path(entry_root: Path, entry_id: str) -> Path:
    safe = hashlib.sha256(entry_id.encode("utf-8")).hexdigest()
    return entry_root / f"{safe}.json"


def load_entry(entry_root: Path, entry_id: str) -> dict[str, Any] | None:
    path = _entry_file_path(entry_root, entry_id)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def save_entry(entry_root: Path, entry: dict[str, Any]) -> Path:
    entry_id = str(entry.get("entryId") or entry.get("idempotencyKey") or "")
    if not entry_id:
        raise LedgerStoreError("ledger entry missing entryId/idempotencyKey")
    path = _entry_file_path(entry_root, entry_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _chmod_harden(tmp)
    tmp.replace(path)
    _chmod_harden(path)
    return path


def list_entry_paths(entry_root: Path) -> list[Path]:
    if not entry_root.is_dir():
        return []
    return sorted(p for p in entry_root.glob("*.json") if p.is_file() and not p.name.endswith(".tmp"))


def load_all_entries(entry_root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in list_entry_paths(entry_root):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(doc, dict):
            out.append(doc)
    return out


def entry_recorded_at(entry: dict[str, Any]) -> datetime:
    parsed = _parse_iso8601(str(entry.get("recordedAt") or ""))
    return parsed or datetime.fromtimestamp(0, tz=UTC)


def entry_size_bytes(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def empty_eviction_journal() -> dict[str, Any]:
    return {"schemaVersion": LEDGER_SCHEMA_VERSION, "events": [], "updatedAt": _utc_now()}


def load_eviction_journal(ledger_dir: Path) -> dict[str, Any]:
    path = eviction_journal_path(ledger_dir)
    if not path.is_file():
        return empty_eviction_journal()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_eviction_journal()
    if not isinstance(doc, dict):
        return empty_eviction_journal()
    doc.setdefault("schemaVersion", LEDGER_SCHEMA_VERSION)
    doc.setdefault("events", [])
    return doc


def append_eviction_journal(ledger_dir: Path, events: list[dict[str, Any]]) -> Path:
    if not events:
        return eviction_journal_path(ledger_dir)
    journal = load_eviction_journal(ledger_dir)
    stamped = []
    now = _utc_now()
    for event in events:
        payload = dict(event)
        payload.setdefault("evictedAt", now)
        stamped.append(payload)
    journal["events"] = list(journal.get("events") or []) + stamped
    journal["updatedAt"] = now
    path = eviction_journal_path(ledger_dir)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(journal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _chmod_harden(tmp)
    tmp.replace(path)
    _chmod_harden(path)
    return path


def enforce_ledger_bounds(
    ledger_dir: Path,
    *,
    ttl_seconds: int,
    max_size_bytes: int,
) -> dict[str, Any]:
    entry_root = entries_dir(ledger_dir)
    if not entry_root.is_dir():
        return {"verdict": "ok", "evicted": [], "remainingBytes": 0}
    now = datetime.now(UTC)
    ttl_cutoff = now - timedelta(seconds=ttl_seconds)
    paths = list_entry_paths(entry_root)
    indexed: list[tuple[datetime, Path, dict[str, Any] | None]] = []
    for path in paths:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            doc = None
        recorded = entry_recorded_at(doc or {})
        indexed.append((recorded, path, doc if isinstance(doc, dict) else None))
    indexed.sort(key=lambda item: item[0])
    total_bytes = sum(entry_size_bytes(path) for _, path, _ in indexed)
    evicted: list[dict[str, Any]] = []
    for recorded, path, doc in indexed:
        expired = recorded < ttl_cutoff
        over_size = total_bytes > max_size_bytes
        if not expired and not over_size:
            break
        reason = "ttl" if expired else "size"
        event = {
            "entryId": (doc or {}).get("entryId"),
            "idempotencyKey": (doc or {}).get("idempotencyKey"),
            "recordedAt": (doc or {}).get("recordedAt"),
            "reason": reason,
            "path": path.name,
        }
        evicted.append(event)
        size = entry_size_bytes(path)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            continue
        total_bytes = max(0, total_bytes - size)
    if evicted:
        append_eviction_journal(ledger_dir, evicted)
    return {
        "verdict": "ok",
        "evicted": evicted,
        "remainingBytes": total_bytes,
        "ttlSeconds": ttl_seconds,
        "maxSizeBytes": max_size_bytes,
    }
