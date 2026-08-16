#!/usr/bin/env python3
"""Workflow package lockfile pins and approval-gated edits (PRD 272 R19/R21)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

LOCKFILE_SCHEMA_VERSION = 1
DEFAULT_LOCK_PATH = Path(".sw/workflows/lock.json")


class LockfileError(RuntimeError):
    """Raised when lockfile validation or approval fails closed."""


@dataclass(frozen=True)
class LockPin:
    pin: str
    digest: str
    signer_key_id: str
    dependencies: tuple[str, ...]


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def compute_lock_digest(document: Mapping[str, Any]) -> str:
    """Digest of lock body excluding approval metadata."""
    body = {
        "schemaVersion": document.get("schemaVersion"),
        "packages": document.get("packages"),
    }
    return hashlib.sha256(_canonical_bytes(body)).hexdigest()


def load_lockfile(path: str | Path) -> dict[str, Any]:
    lock_path = Path(path)
    if not lock_path.is_file():
        raise LockfileError(f"lockfile missing: {lock_path}")
    try:
        document = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LockfileError(f"cannot load lockfile: {exc}") from exc
    if not isinstance(document, dict):
        raise LockfileError("lockfile must be an object")
    if int(document.get("schemaVersion") or 0) != LOCKFILE_SCHEMA_VERSION:
        raise LockfileError("unsupported lockfile schema version")
    packages = document.get("packages")
    if not isinstance(packages, dict) or not packages:
        raise LockfileError("lockfile must pin at least one package")
    return document


def parse_lock_pins(document: Mapping[str, Any]) -> tuple[LockPin, ...]:
    packages = document.get("packages")
    if not isinstance(packages, Mapping):
        raise LockfileError("lockfile packages must be an object")
    pins: list[LockPin] = []
    for pin, raw in packages.items():
        if not isinstance(raw, Mapping):
            raise LockfileError(f"lock pin {pin} must be an object")
        digest = str(raw.get("digest") or "")
        if len(digest) != 64:
            raise LockfileError(f"lock pin {pin} missing digest")
        signer = str(raw.get("signerKeyId") or "")
        if not signer:
            raise LockfileError(f"lock pin {pin} missing signerKeyId")
        deps = tuple(str(item) for item in (raw.get("dependencies") or ()))
        pins.append(
            LockPin(
                pin=str(pin),
                digest=digest,
                signer_key_id=signer,
                dependencies=deps,
            )
        )
    return tuple(pins)


def validate_lock_transitive_closure(
    pins: Sequence[LockPin],
    *,
    resolved_pins: Sequence[str],
) -> None:
    """Refuse resolution when lock does not cover full transitive closure (R21)."""
    required = {pin.pin for pin in pins}
    for pin in pins:
        required.update(pin.dependencies)
    missing = sorted(required - set(resolved_pins))
    if missing:
        raise LockfileError(
            "lockfile does not cover transitive closure: " + ", ".join(missing)
        )


def require_lock_edit_approval(
    *,
    previous: Mapping[str, Any] | None,
    updated: Mapping[str, Any],
    approval: Mapping[str, Any] | None,
) -> None:
    """Lock edits require the same human/admin approval as pack approval (R21)."""
    previous_digest = compute_lock_digest(previous) if previous else None
    updated_digest = compute_lock_digest(updated)
    if previous_digest == updated_digest:
        return
    if not isinstance(approval, Mapping):
        raise LockfileError("lockfile edit requires human approval")
    if approval.get("approved") is not True:
        raise LockfileError("lockfile edit approval record incomplete")
    if str(approval.get("lockDigest") or "") != updated_digest:
        raise LockfileError("lockfile approval digest mismatch")
    if not approval.get("approvedBy") or not approval.get("approvedAt"):
        raise LockfileError("lockfile approval actor/timestamp required")
