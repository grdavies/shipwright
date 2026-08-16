#!/usr/bin/env python3
"""Out-of-band trust anchors for signed workflow packages (PRD 272 R21)."""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

TRUST_ANCHOR_SCHEMA_VERSION = 1
DEFAULT_TRUST_ANCHOR_PATH = Path(".cursor/sw-package-trust-anchors.json")
KEY_STATUSES = frozenset({"active", "expired", "revoked"})


class TrustAnchorError(RuntimeError):
    """Raised when trust anchor configuration or verification fails closed."""


@dataclass(frozen=True)
class TrustKey:
    key_id: str
    status: str
    secret: bytes
    not_before: str
    not_after: str


@dataclass(frozen=True)
class TrustAnchorStore:
    """Configured trust anchors — never sourced from packs or registries (R21)."""

    keys: Mapping[str, TrustKey]

    def key_status(self, key_id: str) -> str:
        key = self.keys.get(key_id)
        if key is None:
            return "unknown"
        return key.status

    def require_active_key(self, key_id: str) -> TrustKey:
        key = self.keys.get(key_id)
        if key is None:
            raise TrustAnchorError(f"unknown signer key: {key_id}")
        if key.status == "revoked":
            raise TrustAnchorError(f"revoked signer key: {key_id}")
        if key.status == "expired":
            raise TrustAnchorError(f"expired signer key: {key_id}")
        if key.status != "active":
            raise TrustAnchorError(f"unavailable signer key status: {key_id}")
        now = datetime.now(timezone.utc)
        not_before = _parse_iso(key.not_before)
        not_after = _parse_iso(key.not_after)
        if now < not_before:
            raise TrustAnchorError(f"signer key not yet valid: {key_id}")
        if now > not_after:
            raise TrustAnchorError(f"signer key expired: {key_id}")
        return key


def _parse_iso(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def load_trust_anchors(path: str | Path) -> TrustAnchorStore:
    """Load out-of-band trust anchors from operator configuration."""
    anchor_path = Path(path)
    if not anchor_path.is_file():
        raise TrustAnchorError(f"trust anchor file missing: {anchor_path}")
    try:
        payload = json.loads(anchor_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TrustAnchorError(f"cannot load trust anchors: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise TrustAnchorError("trust anchor document must be an object")
    if int(payload.get("schemaVersion") or 0) != TRUST_ANCHOR_SCHEMA_VERSION:
        raise TrustAnchorError("unsupported trust anchor schema version")
    raw_keys = payload.get("keys")
    if not isinstance(raw_keys, Mapping):
        raise TrustAnchorError("trust anchor keys must be an object")
    keys: dict[str, TrustKey] = {}
    for key_id, raw in raw_keys.items():
        if not isinstance(raw, Mapping):
            raise TrustAnchorError(f"trust key {key_id} must be an object")
        status = str(raw.get("status") or "unknown")
        if status not in KEY_STATUSES:
            raise TrustAnchorError(f"invalid trust key status for {key_id}: {status}")
        secret_text = str(raw.get("secret") or "")
        if not secret_text:
            raise TrustAnchorError(f"trust key {key_id} missing secret")
        keys[str(key_id)] = TrustKey(
            key_id=str(key_id),
            status=status,
            secret=secret_text.encode("utf-8"),
            not_before=str(raw.get("notBefore") or "1970-01-01T00:00:00Z"),
            not_after=str(raw.get("notAfter") or "2099-12-31T23:59:59Z"),
        )
    return TrustAnchorStore(keys=keys)


def package_content_digest(content: Mapping[str, Any]) -> str:
    """Digest of unsigned package body used for signing and lock pins."""
    unsigned = {
        key: value
        for key, value in content.items()
        if key not in {"provenance", "signature"}
    }
    return hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()


def sign_package_content(
    content: Mapping[str, Any],
    *,
    key_id: str,
    secret: bytes,
) -> dict[str, str]:
    digest = package_content_digest(content)
    signature = hmac.new(secret, digest.encode("utf-8"), hashlib.sha256).hexdigest()
    return {"signerKeyId": key_id, "signature": signature, "contentDigest": digest}


def verify_package_signature(
    content: Mapping[str, Any],
    *,
    trust_store: TrustAnchorStore,
) -> None:
    """Fail closed on missing, unknown, expired, or revoked signatures (R21)."""
    provenance = content.get("provenance")
    if not isinstance(provenance, Mapping):
        raise TrustAnchorError("package missing signed provenance")
    signature = str(provenance.get("signature") or "")
    if not signature:
        raise TrustAnchorError("package missing signature")
    key_id = str(provenance.get("signerKeyId") or "")
    key = trust_store.require_active_key(key_id)
    digest = package_content_digest(content)
    expected = hmac.new(key.secret, digest.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise TrustAnchorError("package signature mismatch")
