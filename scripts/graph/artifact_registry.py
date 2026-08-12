#!/usr/bin/env python3
"""Durable, hash-verifying registry for WorkflowGraph artifacts."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ArtifactRegistryError(RuntimeError):
    """Base class for durable artifact registry errors."""


class ArtifactIntegrityError(ArtifactRegistryError):
    """Raised when persisted artifact content no longer matches its hash."""


@dataclass(frozen=True)
class ArtifactRecord:
    """One verified artifact and its provenance metadata."""

    artifact_id: str
    schema: str
    content_hash: str
    producing_node: str
    input_revision: str
    verification_evidence: tuple[str, ...]
    content: Any

    def metadata(self) -> dict[str, Any]:
        return {
            "artifactId": self.artifact_id,
            "schema": self.schema,
            "contentHash": self.content_hash,
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


def _write_durable(path: Path, payload: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


class ArtifactRegistry:
    """Directory-backed registry using one atomic bundle per artifact."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

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
    ) -> ArtifactRecord:
        """Atomically create an artifact bundle; existing ids are immutable."""
        artifact_dir = self._artifact_dir(artifact_id)
        if artifact_dir.exists():
            raise FileExistsError(f"artifact already exists: {artifact_id}")
        content_bytes = _canonical_content(content)
        content_hash = hashlib.sha256(content_bytes).hexdigest()
        record = ArtifactRecord(
            artifact_id=artifact_id,
            schema=schema,
            content_hash=content_hash,
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
        """Read an artifact only after verifying its persisted content hash."""
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
        if metadata.get("artifactId") != artifact_id:
            raise ArtifactIntegrityError(
                f"artifact {artifact_id} metadata identity mismatch"
            )
        return ArtifactRecord(
            artifact_id=artifact_id,
            schema=str(metadata["schema"]),
            content_hash=actual_hash,
            producing_node=str(metadata["producingNode"]),
            input_revision=str(metadata["inputRevision"]),
            verification_evidence=tuple(metadata["verificationEvidence"]),
            content=content,
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
