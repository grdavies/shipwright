#!/usr/bin/env python3
"""Workflow package discovery and trusted resolution (PRD 272 R19)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from graph.packages.lockfile import (
    LockPin,
    LockfileError,
    load_lockfile,
    parse_lock_pins,
    validate_lock_transitive_closure,
)
from graph.packages.trust import (
    TrustAnchorError,
    TrustAnchorStore,
    package_content_digest,
    verify_package_signature,
)

PACKAGE_KIND = "WorkflowPackage"
PACKAGE_SCHEMA_VERSION = 1
DEFAULT_CATALOG_ROOT = Path(".sw/workflows/packages")


class PackageResolverError(RuntimeError):
    """Raised when package resolution or trust verification fails closed."""


@dataclass(frozen=True)
class DiscoveredPackage:
    pin: str
    path: Path
    semver: str


@dataclass(frozen=True)
class ResolvedPackage:
    pin: str
    digest: str
    document: Mapping[str, Any]
    trusted: bool


def discover_packages(catalog_root: str | Path) -> tuple[DiscoveredPackage, ...]:
    """List catalog entries without implying trust (R19 discover≠trust)."""
    root = Path(catalog_root)
    if not root.is_dir():
        return ()
    discovered: list[DiscoveredPackage] = []
    for path in sorted(root.glob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(document, Mapping):
            continue
        if document.get("kind") != PACKAGE_KIND:
            continue
        name = str(document.get("name") or "")
        version = str(document.get("version") or "")
        if not name or not version:
            continue
        discovered.append(
            DiscoveredPackage(
                pin=f"{name}@{version}",
                path=path,
                semver=version,
            )
        )
    return tuple(discovered)


class PackageResolver:
    """Resolve lock-pinned packages with signature and digest verification."""

    def __init__(
        self,
        *,
        lock_path: str | Path,
        trust_store: TrustAnchorStore,
        repo_root: str | Path,
    ) -> None:
        self._lock_path = Path(lock_path)
        self._trust_store = trust_store
        self._repo_root = Path(repo_root)
        self._lock = load_lockfile(self._lock_path)
        self._pins = parse_lock_pins(self._lock)
        self._catalog = self._repo_root / DEFAULT_CATALOG_ROOT

    @property
    def pins(self) -> tuple[LockPin, ...]:
        return self._pins

    def resolve_all(self) -> tuple[ResolvedPackage, ...]:
        resolved: list[ResolvedPackage] = []
        resolved_pins: list[str] = []
        for pin in self._pins:
            package = self._resolve_pin(pin)
            resolved.append(package)
            resolved_pins.append(pin.pin)
            resolved_pins.extend(pin.dependencies)
        validate_lock_transitive_closure(self._pins, resolved_pins=resolved_pins)
        return tuple(resolved)

    def resolve_pin(self, pin: str) -> ResolvedPackage:
        lock_pin = next((item for item in self._pins if item.pin == pin), None)
        if lock_pin is None:
            raise PackageResolverError(f"package not pinned in lockfile: {pin}")
        return self._resolve_pin(lock_pin)

    def _resolve_pin(self, lock_pin: LockPin) -> ResolvedPackage:
        document = self._load_package_document(lock_pin.pin)
        digest = package_content_digest(document)
        if digest != lock_pin.digest:
            raise PackageResolverError(
                f"package digest mismatch for {lock_pin.pin}: discovery≠trust"
            )
        try:
            verify_package_signature(document, trust_store=self._trust_store)
        except TrustAnchorError as exc:
            raise PackageResolverError(str(exc)) from exc
        signer = str((document.get("provenance") or {}).get("signerKeyId") or "")
        if signer != lock_pin.signer_key_id:
            raise PackageResolverError(
                f"lock signer mismatch for {lock_pin.pin}: {signer}!={lock_pin.signer_key_id}"
            )
        return ResolvedPackage(
            pin=lock_pin.pin,
            digest=digest,
            document=document,
            trusted=True,
        )

    def _load_package_document(self, pin: str) -> dict[str, Any]:
        path = self._catalog / f"{pin}.json"
        if not path.is_file():
            raise PackageResolverError(f"package artifact missing: {pin}")
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PackageResolverError(f"cannot load package {pin}: {exc}") from exc
        if not isinstance(document, dict):
            raise PackageResolverError(f"package {pin} must be an object")
        if int(document.get("schemaVersion") or 0) != PACKAGE_SCHEMA_VERSION:
            raise PackageResolverError(f"unsupported package schema: {pin}")
        if document.get("kind") != PACKAGE_KIND:
            raise PackageResolverError(f"invalid package kind: {pin}")
        identity = f"{document.get('name')}@{document.get('version')}"
        if identity != pin:
            raise PackageResolverError(f"package identity mismatch: {identity}!={pin}")
        return document
