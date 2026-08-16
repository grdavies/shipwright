#!/usr/bin/env python3
"""Durable, hash-and-MAC-verifying registry for WorkflowGraph artifacts."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
DEFAULT_MAC_KEY = b"shipwright-graph-artifact-mac-v1"
DEFAULT_RECEIPT_MAC_KEY = b"shipwright-graph-receipt-mac-v1"


class ArtifactRegistryError(RuntimeError):
    """Base class for durable artifact registry errors."""


class ArtifactIntegrityError(ArtifactRegistryError):
    """Raised when persisted artifact content no longer matches its hash/MAC."""


class PurityViolationError(ArtifactRegistryError):
    """Raised when a declared read-only node attempts to write (R15)."""


class SchemaVersionError(ArtifactRegistryError):
    """Raised when artifact schema versions cannot be reconciled."""


class SchemaCompatibilityError(SchemaVersionError):
    """Raised when producer and consumer schemas disagree without an upgrade path."""


class ProducerNewerThanConsumerError(SchemaVersionError):
    """Raised when producer major exceeds consumer major (no implicit downgrade)."""


_SCHEMA_AT_RE = re.compile(r"^(.+)@(\d+)(?:\.(\d+))?$")
_SCHEMA_LEGACY_V_RE = re.compile(r"^(.+)/v(\d+)$")


@dataclass(frozen=True)
class ArtifactSchemaVersion:
    """Artifact schema identity: name, integer major, optional additive minor."""

    name: str
    major: int
    minor: int = 0

    def __post_init__(self) -> None:
        if self.major < 0 or self.minor < 0:
            raise ValueError("schema major and minor must be non-negative integers")

    def cache_key_component(self) -> str:
        """Stable cache-key fragment: schema name plus major only (R6)."""
        return f"{self.name}@{self.major}"

    def __str__(self) -> str:
        if self.minor:
            return f"{self.name}@{self.major}.{self.minor}"
        return f"{self.name}@{self.major}"


SchemaUpgradeTransform = Callable[[Any], Any]


@dataclass(frozen=True)
class RegisteredSchemaUpgrade:
    """Pure, registered transform between schema majors."""

    schema_name: str
    from_major: int
    to_major: int
    transform: SchemaUpgradeTransform
    required_fields: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.to_major != self.from_major + 1:
            raise ValueError("registered upgrades must advance exactly one major")
        if self.from_major < 0 or self.to_major < 0:
            raise ValueError("schema majors must be non-negative integers")


class SchemaUpgradeRegistry:
    """Registry of explicit major-version upgrade transforms."""

    def __init__(self) -> None:
        self._upgrades: dict[tuple[str, int, int], RegisteredSchemaUpgrade] = {}

    def register(self, upgrade: RegisteredSchemaUpgrade) -> None:
        key = (upgrade.schema_name, upgrade.from_major, upgrade.to_major)
        if key in self._upgrades:
            raise ValueError(
                f"upgrade already registered for {upgrade.schema_name} "
                f"{upgrade.from_major}->{upgrade.to_major}"
            )
        self._upgrades[key] = upgrade

    def get(
        self, schema_name: str, from_major: int, to_major: int
    ) -> RegisteredSchemaUpgrade | None:
        if to_major != from_major + 1:
            return None
        return self._upgrades.get((schema_name, from_major, to_major))


class SchemaCompatibilityMatrix:
    """Same-major additive-minor compatibility declarations."""

    def is_compatible(
        self, consumer: ArtifactSchemaVersion, producer: ArtifactSchemaVersion
    ) -> bool:
        if consumer.name != producer.name or consumer.major != producer.major:
            return False
        return producer.minor >= consumer.minor


def parse_schema(schema: str) -> ArtifactSchemaVersion:
    """Parse canonical, legacy ``/vN``, or unversioned schema strings."""
    raw = schema.strip()
    at_match = _SCHEMA_AT_RE.fullmatch(raw)
    if at_match:
        return ArtifactSchemaVersion(
            at_match.group(1),
            int(at_match.group(2)),
            int(at_match.group(3) or 0),
        )
    legacy_match = _SCHEMA_LEGACY_V_RE.fullmatch(raw)
    if legacy_match:
        return ArtifactSchemaVersion(legacy_match.group(1), int(legacy_match.group(2)), 0)
    return ArtifactSchemaVersion(raw, 0, 0)


def format_schema(version: ArtifactSchemaVersion) -> str:
    """Render the canonical schema identity string."""
    return str(version)


def canonicalize_schema(schema: str) -> str:
    """Normalize legacy and unversioned schema strings to canonical form."""
    return format_schema(parse_schema(schema))


def migrate_legacy_schema(schema: str) -> str:
    """Alias for :func:`canonicalize_schema` (269-270 contract migration)."""
    return canonicalize_schema(schema)


def schema_major_cache_component(schema: str) -> str:
    """Return ``name@major`` for PRD 269 cache-key material."""
    return parse_schema(schema).cache_key_component()


def _verify_required_fields(content: Any, required_fields: frozenset[str]) -> None:
    if not required_fields:
        return
    if not isinstance(content, Mapping):
        raise SchemaCompatibilityError("upgrade output must be an object")
    missing = sorted(field for field in required_fields if field not in content)
    if missing:
        raise SchemaCompatibilityError(
            "upgrade output is missing required fields: " + ", ".join(missing)
        )


def resolve_schema_for_consumer(
    *,
    producer_schema: str,
    consumer_schema: str,
    content: Any,
    upgrades: SchemaUpgradeRegistry,
    matrix: SchemaCompatibilityMatrix | None = None,
) -> tuple[Any, str]:
    """Resolve producer content/schema to satisfy a consumer schema identity."""
    compatibility = matrix or SchemaCompatibilityMatrix()
    producer = parse_schema(producer_schema)
    consumer = parse_schema(consumer_schema)
    if producer.name != consumer.name:
        raise SchemaCompatibilityError(
            f"schema name mismatch: producer {producer.name!r}, "
            f"consumer {consumer.name!r}"
        )
    if producer.major == consumer.major:
        if compatibility.is_compatible(consumer, producer):
            return content, format_schema(consumer)
        raise SchemaCompatibilityError(
            f"incompatible schema minors for {consumer.name}: "
            f"consumer {consumer.minor}, producer {producer.minor}"
        )
    if producer.major > consumer.major:
        raise ProducerNewerThanConsumerError(
            f"producer schema {producer} is newer than consumer {consumer}; "
            "no implicit downgrade"
        )

    current_major = producer.major
    current_content = content
    while current_major < consumer.major:
        upgrade = upgrades.get(producer.name, current_major, current_major + 1)
        if upgrade is None:
            raise SchemaCompatibilityError(
                f"no registered upgrade for {producer.name} "
                f"@{current_major} -> @{current_major + 1}"
            )
        current_content = upgrade.transform(current_content)
        _verify_required_fields(current_content, upgrade.required_fields)
        current_major += 1

    upgraded = ArtifactSchemaVersion(consumer.name, consumer.major, 0)
    if not compatibility.is_compatible(consumer, upgraded):
        raise SchemaCompatibilityError(
            f"upgraded schema {upgraded} does not satisfy consumer {consumer}"
        )
    return current_content, format_schema(consumer)


@dataclass(frozen=True)
class ArtifactRecord:
    """One verified artifact and its provenance metadata."""

    artifact_id: str
    schema: str
    content_hash: str
    content_mac: str
    producing_node: str
    input_revision: str
    verification_evidence: tuple[str, ...]
    content: Any

    def metadata(self) -> dict[str, Any]:
        return {
            "artifactId": self.artifact_id,
            "schema": self.schema,
            "contentHash": self.content_hash,
            "contentMac": self.content_mac,
            "producingNode": self.producing_node,
            "inputRevision": self.input_revision,
            "verificationEvidence": list(self.verification_evidence),
        }


def _validate_id(artifact_id: str) -> str:
    if not _SAFE_ID.fullmatch(artifact_id):
        raise ValueError(f"invalid artifact id: {artifact_id!r}")
    return artifact_id


def _canonical_content(content: Any) -> bytes:
    try:
        encoded = json.dumps(
            content, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"artifact content must be JSON-compatible: {exc}") from exc
    return encoded.encode("utf-8")


def _content_mac(content_bytes: bytes, *, mac_key: bytes) -> str:
    return hmac.new(mac_key, content_bytes, hashlib.sha256).hexdigest()


def receipt_satisfies_cache_hit(
    receipt: dict[str, Any],
    *,
    mac_key: bytes | None = None,
) -> bool:
    """Return True only when a receipt may authorize a content-addressed cache hit."""
    if receipt.get("verdict") != "pass":
        return False
    if receipt.get("retryOnly"):
        return False
    if receipt.get("receiptMutated"):
        return False
    if receipt.get("cacheHit"):
        return False
    if receipt.get("state") not in (None, "complete"):
        return False
    stored_hash = receipt.get("receiptHash")
    if not isinstance(stored_hash, str):
        return False
    source = {
        key: value
        for key, value in receipt.items()
        if key not in {"receiptHash", "receiptMac"}
    }
    canonical = (
        json.dumps(source, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")
    if stored_hash != hashlib.sha256(canonical).hexdigest():
        return False
    stored_mac = receipt.get("receiptMac")
    key = mac_key if mac_key is not None else DEFAULT_RECEIPT_MAC_KEY
    if not stored_mac:
        return False
    expected_mac = hmac.new(key, canonical, hashlib.sha256).hexdigest()
    if stored_mac != expected_mac:
        return False
    return True


def receipt_is_reusable(
    receipt: Mapping[str, Any],
    *,
    mac_key: bytes | None = None,
) -> bool:
    """Backward-compatible alias for cache reuse checks."""
    return receipt_satisfies_cache_hit(dict(receipt), mac_key=mac_key)


def _write_durable(path: Path, payload: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


class ArtifactRegistry:
    """Directory-backed registry using one atomic bundle per artifact."""

    def __init__(self, root: str | Path, *, mac_key: bytes | None = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._mac_key = mac_key if mac_key is not None else DEFAULT_MAC_KEY

    def _artifact_dir(self, artifact_id: str) -> Path:
        return self.root / _validate_id(artifact_id)

    def content_path(self, artifact_id: str) -> Path:
        return self._artifact_dir(artifact_id) / "content.json"

    def metadata_path(self, artifact_id: str) -> Path:
        return self._artifact_dir(artifact_id) / "metadata.json"

    def register(
        self,
        *,
        artifact_id: str,
        content: Any,
        schema: str,
        producing_node: str,
        input_revision: str,
        verification_evidence: list[str] | tuple[str, ...],
        purity: str | None = None,
    ) -> ArtifactRecord:
        """Atomically create an artifact bundle; existing ids are immutable.

        Declared read-only producers fail closed and must not register writes (R15).
        """
        if purity == "read-only":
            raise PurityViolationError(
                f"read-only node {producing_node} cannot register artifact writes"
            )
        canonical_schema = canonicalize_schema(schema)
        artifact_dir = self._artifact_dir(artifact_id)
        if artifact_dir.exists():
            raise FileExistsError(f"artifact already exists: {artifact_id}")
        content_bytes = _canonical_content(content)
        content_hash = hashlib.sha256(content_bytes).hexdigest()
        content_mac = _content_mac(content_bytes, mac_key=self._mac_key)
        record = ArtifactRecord(
            artifact_id=artifact_id,
            schema=canonical_schema,
            content_hash=content_hash,
            content_mac=content_mac,
            producing_node=producing_node,
            input_revision=input_revision,
            verification_evidence=tuple(verification_evidence),
            content=content,
        )
        metadata_bytes = (
            json.dumps(
                record.metadata(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8")

        staging = Path(
            tempfile.mkdtemp(prefix=f".{artifact_id}.", dir=str(self.root))
        )
        try:
            _write_durable(staging / "content.json", content_bytes)
            _write_durable(staging / "metadata.json", metadata_bytes)
            os.replace(staging, artifact_dir)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return record

    def read(self, artifact_id: str) -> ArtifactRecord:
        """Read an artifact only after verifying hash and keyed MAC (R7)."""
        metadata_path = self.metadata_path(artifact_id)
        content_path = self.content_path(artifact_id)
        if not metadata_path.is_file() or not content_path.is_file():
            raise KeyError(artifact_id)
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            content_bytes = content_path.read_bytes()
            content = json.loads(content_bytes)
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactIntegrityError(
                f"artifact {artifact_id} is unreadable: {exc}"
            ) from exc
        actual_hash = hashlib.sha256(content_bytes).hexdigest()
        expected_hash = metadata.get("contentHash")
        if actual_hash != expected_hash:
            raise ArtifactIntegrityError(
                f"artifact {artifact_id} hash mismatch: "
                f"expected {expected_hash}, got {actual_hash}"
            )
        expected_mac = metadata.get("contentMac")
        actual_mac = _content_mac(content_bytes, mac_key=self._mac_key)
        if not expected_mac or actual_mac != expected_mac:
            raise ArtifactIntegrityError(
                f"artifact {artifact_id} MAC mismatch: "
                f"expected {expected_mac}, got {actual_mac}"
            )
        if metadata.get("artifactId") != artifact_id:
            raise ArtifactIntegrityError(
                f"artifact {artifact_id} metadata identity mismatch"
            )
        return ArtifactRecord(
            artifact_id=artifact_id,
            schema=str(metadata["schema"]),
            content_hash=actual_hash,
            content_mac=actual_mac,
            producing_node=str(metadata["producingNode"]),
            input_revision=str(metadata["inputRevision"]),
            verification_evidence=tuple(metadata["verificationEvidence"]),
            content=content,
        )

    def restore_copy(self, artifact_id: str, dest_id: str) -> ArtifactRecord:
        """Restore a verified artifact under a new id (cache-hit materialization)."""
        source = self.read(artifact_id)
        return self.register(
            artifact_id=dest_id,
            content=source.content,
            schema=source.schema,
            producing_node=source.producing_node,
            input_revision=source.input_revision,
            verification_evidence=source.verification_evidence,
        )

    def list_ids(self) -> list[str]:
        return sorted(
            path.name
            for path in self.root.iterdir()
            if path.is_dir()
            and not path.name.startswith(".")
            and (path / "metadata.json").is_file()
        )

    def fingerprint(self, artifact_id: str) -> str:
        """Return the verified content hash used by convergence dedupe."""
        return self.read(artifact_id).content_hash

    def delete(self, artifact_id: str) -> None:
        artifact_dir = self._artifact_dir(artifact_id)
        if not artifact_dir.is_dir():
            raise KeyError(artifact_id)
        shutil.rmtree(artifact_dir)
