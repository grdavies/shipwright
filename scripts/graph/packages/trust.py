#!/usr/bin/env python3
"""Out-of-band trust anchors for signed workflow packages (PRD 272 R21).

Dist-only script trust (PRD 338 R28) validates zipapp + manifest digests against
signed install-root anchors — never from workspace marker files alone.
"""
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
DIST_TRUST_ANCHOR_SCHEMA_VERSION = 1
DIST_TRUST_ANCHOR_FILENAME = "shipwright-scripts-trust-anchors.json"
DIST_TRUST_STATUSES = frozenset({"active", "expired", "revoked"})
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


@dataclass(frozen=True)
class DistTrustAnchor:
    anchor_id: str
    status: str
    manifest_sha256: str
    zipapp_sha256: str
    signer_key_id: str
    signature: str
    not_before: str
    not_after: str


@dataclass(frozen=True)
class DistTrustAnchorStore:
    """Install-root dist trust anchors — bound to manifest + zipapp digests (R28)."""

    anchors: Mapping[str, DistTrustAnchor]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def resolve_zipapp_path(install_root: Path) -> Path:
    stable = install_root / "shipwright.pyz"
    if stable.is_file():
        return stable.resolve()
    candidates = sorted(install_root.glob("shipwright-*.pyz"))
    if not candidates:
        raise TrustAnchorError(f"zipapp missing under install root: {install_root}")
    return candidates[-1].resolve()


def resolve_manifest_path(install_root: Path) -> Path:
    stable = install_root / "shipwright.manifest.json"
    if stable.is_file():
        return stable.resolve()
    candidates = sorted(install_root.glob("shipwright-*.manifest.json"))
    if not candidates:
        raise TrustAnchorError(f"manifest missing under install root: {install_root}")
    return candidates[-1].resolve()


def dist_install_digests(install_root: Path) -> dict[str, str]:
    """Return canonical manifest and zipapp digests for an install root."""
    manifest = resolve_manifest_path(install_root)
    zipapp = resolve_zipapp_path(install_root)
    return {
        "manifestSha256": sha256_file(manifest),
        "zipappSha256": sha256_file(zipapp),
        "manifestPath": str(manifest),
        "zipappPath": str(zipapp),
    }


def dist_trust_signature_payload(
    *,
    anchor_id: str,
    manifest_sha256: str,
    zipapp_sha256: str,
) -> dict[str, str]:
    return {
        "anchorId": anchor_id,
        "manifestSha256": manifest_sha256,
        "zipappSha256": zipapp_sha256,
    }


def sign_dist_trust_anchor(
    *,
    anchor_id: str,
    manifest_sha256: str,
    zipapp_sha256: str,
    key_id: str,
    secret: bytes,
    status: str = "active",
    not_before: str = "2020-01-01T00:00:00Z",
    not_after: str = "2099-12-31T23:59:59Z",
) -> DistTrustAnchor:
    if status not in DIST_TRUST_STATUSES:
        raise TrustAnchorError(f"invalid dist trust anchor status: {status}")
    payload = dist_trust_signature_payload(
        anchor_id=anchor_id,
        manifest_sha256=manifest_sha256,
        zipapp_sha256=zipapp_sha256,
    )
    signature = hmac.new(
        secret, _canonical_bytes(payload), hashlib.sha256
    ).hexdigest()
    return DistTrustAnchor(
        anchor_id=anchor_id,
        status=status,
        manifest_sha256=manifest_sha256,
        zipapp_sha256=zipapp_sha256,
        signer_key_id=key_id,
        signature=signature,
        not_before=not_before,
        not_after=not_after,
    )


def dist_trust_digest(manifest_sha256: str, zipapp_sha256: str) -> str:
    """Stable binding digest for dist-trusted script roots."""
    material = f"{manifest_sha256}:{zipapp_sha256}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def load_dist_trust_anchors(path: str | Path) -> DistTrustAnchorStore:
    anchor_path = Path(path)
    if not anchor_path.is_file():
        raise TrustAnchorError(f"dist trust anchor file missing: {anchor_path}")
    try:
        payload = json.loads(anchor_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TrustAnchorError(f"cannot load dist trust anchors: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise TrustAnchorError("dist trust anchor document must be an object")
    if int(payload.get("schemaVersion") or 0) != DIST_TRUST_ANCHOR_SCHEMA_VERSION:
        raise TrustAnchorError("unsupported dist trust anchor schema version")
    raw_anchors = payload.get("anchors")
    if not isinstance(raw_anchors, Mapping):
        raise TrustAnchorError("dist trust anchors must be an object")
    anchors: dict[str, DistTrustAnchor] = {}
    for anchor_id, raw in raw_anchors.items():
        if not isinstance(raw, Mapping):
            raise TrustAnchorError(f"dist trust anchor {anchor_id} must be an object")
        status = str(raw.get("status") or "unknown")
        if status not in DIST_TRUST_STATUSES:
            raise TrustAnchorError(
                f"invalid dist trust anchor status for {anchor_id}: {status}"
            )
        manifest_sha256 = str(raw.get("manifestSha256") or "")
        zipapp_sha256 = str(raw.get("zipappSha256") or "")
        if len(manifest_sha256) != 64 or len(zipapp_sha256) != 64:
            raise TrustAnchorError(f"dist trust anchor {anchor_id} missing digests")
        signature = str(raw.get("signature") or "")
        if not signature:
            raise TrustAnchorError(f"dist trust anchor {anchor_id} missing signature")
        anchors[str(anchor_id)] = DistTrustAnchor(
            anchor_id=str(anchor_id),
            status=status,
            manifest_sha256=manifest_sha256,
            zipapp_sha256=zipapp_sha256,
            signer_key_id=str(raw.get("signerKeyId") or ""),
            signature=signature,
            not_before=str(raw.get("notBefore") or "1970-01-01T00:00:00Z"),
            not_after=str(raw.get("notAfter") or "2099-12-31T23:59:59Z"),
        )
    return DistTrustAnchorStore(anchors=anchors)


def write_dist_trust_anchors(
    dest_dir: Path,
    anchors: Mapping[str, DistTrustAnchor],
) -> Path:
    payload = {
        "schemaVersion": DIST_TRUST_ANCHOR_SCHEMA_VERSION,
        "anchors": {
            anchor_id: {
                "status": anchor.status,
                "manifestSha256": anchor.manifest_sha256,
                "zipappSha256": anchor.zipapp_sha256,
                "signerKeyId": anchor.signer_key_id,
                "signature": anchor.signature,
                "notBefore": anchor.not_before,
                "notAfter": anchor.not_after,
            }
            for anchor_id, anchor in sorted(anchors.items())
        },
    }
    path = dest_dir / DIST_TRUST_ANCHOR_FILENAME
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _dist_anchor_is_active(anchor: DistTrustAnchor, now: datetime) -> bool:
    if anchor.status != "active":
        return False
    not_before = _parse_iso(anchor.not_before)
    not_after = _parse_iso(anchor.not_after)
    return not_before <= now <= not_after


def verify_dist_trust_anchor_record(
    anchor: DistTrustAnchor,
    *,
    manifest_sha256: str,
    zipapp_sha256: str,
    trust_store: TrustAnchorStore,
) -> None:
    if anchor.manifest_sha256 != manifest_sha256 or anchor.zipapp_sha256 != zipapp_sha256:
        raise TrustAnchorError("dist trust anchor digest mismatch")
    key = trust_store.require_active_key(anchor.signer_key_id)
    payload = dist_trust_signature_payload(
        anchor_id=anchor.anchor_id,
        manifest_sha256=manifest_sha256,
        zipapp_sha256=zipapp_sha256,
    )
    expected = hmac.new(key.secret, _canonical_bytes(payload), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(anchor.signature, expected):
        raise TrustAnchorError("dist trust anchor signature mismatch")


def resolve_dist_trust_verdict(
    install_root: Path,
    *,
    trust_store: TrustAnchorStore,
    dist_anchors_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Resolve canonical dist trust verdict for a pure install root (R28)."""
    root = install_root.resolve()
    anchor_path = dist_anchors_path or (root / DIST_TRUST_ANCHOR_FILENAME)
    digests = dist_install_digests(root)
    manifest_sha256 = digests["manifestSha256"]
    zipapp_sha256 = digests["zipappSha256"]
    store = load_dist_trust_anchors(anchor_path)
    instant = now or datetime.now(timezone.utc)
    matches = [
        anchor
        for anchor in store.anchors.values()
        if anchor.manifest_sha256 == manifest_sha256
        and anchor.zipapp_sha256 == zipapp_sha256
        and _dist_anchor_is_active(anchor, instant)
    ]
    if not matches:
        raise TrustAnchorError("no active dist trust anchor matches install digests")
    for anchor in sorted(matches, key=lambda item: item.anchor_id):
        try:
            verify_dist_trust_anchor_record(
                anchor,
                manifest_sha256=manifest_sha256,
                zipapp_sha256=zipapp_sha256,
                trust_store=trust_store,
            )
        except TrustAnchorError:
            continue
        return {
            "verdict": "ok",
            "anchorId": anchor.anchor_id,
            "signerKeyId": anchor.signer_key_id,
            "manifestSha256": manifest_sha256,
            "zipappSha256": zipapp_sha256,
            "trustDigest": dist_trust_digest(manifest_sha256, zipapp_sha256),
            "anchorsPath": str(anchor_path),
        }
    raise TrustAnchorError("dist trust anchors present but none verify")
