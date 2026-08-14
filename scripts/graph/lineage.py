#!/usr/bin/env python3
"""Artifact lineage queries, edge-reduction advice, and content-addressed cache keys."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from graph.artifact_registry import ArtifactRegistry, receipt_satisfies_cache_hit
from graph.execution_receipts import ExecutionReceiptJournal
from graph.typed_dataflow import TypedEdge


class LineageError(ValueError):
    """Raised when durable provenance is missing or internally inconsistent."""


class CacheKeyError(LineageError):
    """Raised when a content-addressed cache key cannot be formed."""


@dataclass(frozen=True)
class LineageRecord:
    artifact_id: str
    producing_node: str
    model: str
    input_revision: str
    content_hash: str
    input_artifacts: tuple[str, ...]
    verification_evidence: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifactId": self.artifact_id,
            "producingNode": self.producing_node,
            "model": self.model,
            "inputRevision": self.input_revision,
            "contentHash": self.content_hash,
            "inputArtifacts": list(self.input_artifacts),
            "verificationEvidence": list(self.verification_evidence),
        }


@dataclass(frozen=True)
class CacheKeyMaterial:
    """Inputs that form a stable, runId-independent content-addressed key (R6)."""

    node_definition: Mapping[str, Any]
    input_hashes: Mapping[str, str]
    prompt_version: str
    model_version: str
    tool_configuration: Mapping[str, Any]
    policy_version: str
    credential_capability_set: tuple[str, ...]
    resolved_scope_identity: str
    repository_identity: str
    trust_domain: str
    tool_binary_identity: str
    repo_state_identity: str

    def stable_payload(self) -> dict[str, Any]:
        node = _canonical_mapping(self.node_definition)
        node.pop("runId", None)
        return {
            "credentialCapabilitySet": list(self.credential_capability_set),
            "inputHashes": _canonical_mapping(self.input_hashes),
            "modelVersion": self.model_version,
            "nodeDefinition": node,
            "policyVersion": self.policy_version,
            "promptVersion": self.prompt_version,
            "repoStateIdentity": self.repo_state_identity,
            "repositoryIdentity": self.repository_identity,
            "resolvedScopeIdentity": self.resolved_scope_identity,
            "toolBinaryIdentity": self.tool_binary_identity,
            "toolConfiguration": _canonical_mapping(self.tool_configuration),
            "trustDomain": self.trust_domain,
        }


def _canonical_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def compute_stable_cache_key(material: CacheKeyMaterial) -> str:
    """Stable SHA-256 over canonical key material; never includes runId (R6)."""
    return hashlib.sha256(_canonical_bytes(material.stable_payload())).hexdigest()


def compute_cache_key(material: CacheKeyMaterial) -> str:
    """Alias for compute_stable_cache_key."""
    return compute_stable_cache_key(material)


def keyed_mac(payload: bytes, *, mac_key: bytes) -> str:
    """Keyed MAC used for cache/receipt integrity (R7) — not unkeyed SHA-256 alone."""
    if not mac_key:
        raise CacheKeyError("mac_key is required for integrity")
    return hmac.new(mac_key, payload, hashlib.sha256).hexdigest()


def receipt_is_cache_reusable(receipt: Mapping[str, Any]) -> bool:
    """Failed, retry-only, mutated, or cache-hit receipts are never reused."""
    if not isinstance(receipt, Mapping):
        return False
    return receipt_satisfies_cache_hit(dict(receipt))


def receipt_is_reusable(receipt: Mapping[str, Any]) -> bool:
    """Backward-compatible alias used by earlier phase scaffolding."""
    return receipt_is_cache_reusable(receipt)


def _receipt_models(
    receipts: Iterable[Mapping[str, Any]],
) -> dict[str, tuple[str, ...]]:
    models: dict[str, list[str]] = {}
    for receipt in receipts:
        node_id = receipt.get("nodeId")
        if not isinstance(node_id, str) or not node_id:
            raise LineageError("receipt is missing nodeId")
        model = receipt.get("model")
        if not isinstance(model, str) or not model:
            raise LineageError(f"receipt for {node_id} is missing model")
        models.setdefault(node_id, []).append(model)
    return {
        node_id: tuple(dict.fromkeys(values))
        for node_id, values in models.items()
    }


class ArtifactLineageView:
    """Join immutable artifact, typed-edge, and execution-receipt provenance."""

    def __init__(
        self,
        registry: ArtifactRegistry,
        edges: Iterable[TypedEdge],
        receipts: Iterable[Mapping[str, Any]],
    ) -> None:
        self._registry = registry
        self._edges = tuple(edges)
        self._models = _receipt_models(receipts)

    def query(self, artifact_id: str) -> LineageRecord:
        artifact = self._registry.read(artifact_id)
        models = self._models.get(artifact.producing_node, ())
        if not models:
            raise LineageError(
                f"no receipt model for producing node {artifact.producing_node}"
            )
        model = models[-1]
        inputs = tuple(
            dict.fromkeys(
                edge.artifact_id
                for edge in self._edges
                if edge.target == artifact.producing_node and edge.artifact_id
            )
        )
        return LineageRecord(
            artifact_id=artifact.artifact_id,
            producing_node=artifact.producing_node,
            model=model,
            input_revision=artifact.input_revision,
            content_hash=artifact.content_hash,
            input_artifacts=inputs,
            verification_evidence=artifact.verification_evidence,
        )

    def chain(self, artifact_id: str) -> tuple[LineageRecord, ...]:
        """Return a depth-first input-to-output chain, rejecting provenance cycles."""
        ordered: list[LineageRecord] = []
        visited: set[str] = set()
        active: set[str] = set()

        def visit(current_id: str) -> None:
            if current_id in active:
                raise LineageError(f"artifact lineage cycle at {current_id}")
            if current_id in visited:
                return
            active.add(current_id)
            record = self.query(current_id)
            for input_id in record.input_artifacts:
                visit(input_id)
            active.remove(current_id)
            visited.add(current_id)
            ordered.append(record)

        visit(artifact_id)
        return tuple(ordered)


def edge_reduction_advisory(
    edges: Iterable[TypedEdge],
    *,
    consumed_edge_ids: Iterable[str] = (),
    contention_relevant_edge_ids: Iterable[str] = (),
    kernel_required_edge_ids: Iterable[str] = (),
) -> tuple[dict[str, str], ...]:
    """Report possible reductions without mutating or authorizing edge deletion."""
    edge_list = tuple(edges)
    consumed = set(consumed_edge_ids)
    protected_contention = set(contention_relevant_edge_ids)
    protected_kernel = set(kernel_required_edge_ids)
    first_by_payload: dict[tuple[str, str, str, str, str], str] = {}
    advice: list[dict[str, str]] = []

    for edge in edge_list:
        protection = ""
        if edge.edge_id in protected_kernel:
            protection = "kernel-required"
        elif edge.edge_id in protected_contention:
            protection = "contention-relevant"

        signature = (
            edge.source,
            edge.target,
            edge.artifact_id,
            edge.schema,
            edge.selector,
        )
        duplicate_of = first_by_payload.get(signature)
        first_by_payload.setdefault(signature, edge.edge_id)

        reason = ""
        if not edge.artifact_id:
            reason = "edge carries no artifact"
        elif duplicate_of is not None:
            reason = f"duplicates artifact payload of {duplicate_of}"
        elif edge.edge_id not in consumed and not edge.required:
            reason = "optional artifact edge was not consumed"

        if protection:
            advice.append(
                {
                    "edgeId": edge.edge_id,
                    "reason": protection,
                    "recommendation": "keep",
                    "action": "advisory-only",
                }
            )
        elif reason:
            advice.append(
                {
                    "edgeId": edge.edge_id,
                    "reason": reason,
                    "recommendation": "review-for-removal",
                    "action": "advisory-only",
                }
            )
    return tuple(advice)


@dataclass(frozen=True)
class CachedArtifactSnapshot:
    artifact_id: str
    schema: str
    content: Any
    producing_node: str
    input_revision: str
    verification_evidence: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifactId": self.artifact_id,
            "schema": self.schema,
            "content": self.content,
            "producingNode": self.producing_node,
            "inputRevision": self.input_revision,
            "verificationEvidence": list(self.verification_evidence),
        }

    @classmethod
    def from_record(cls, record: Any) -> CachedArtifactSnapshot:
        return cls(
            artifact_id=record.artifact_id,
            schema=record.schema,
            content=record.content,
            producing_node=record.producing_node,
            input_revision=record.input_revision,
            verification_evidence=tuple(record.verification_evidence),
        )


class ContentAddressedLineageCache:
    """Run-scoped cache-hit receipts backed by stable, content-addressed entries."""

    def __init__(
        self,
        root: str | Path,
        *,
        registry: ArtifactRegistry,
        journal: ExecutionReceiptJournal,
    ) -> None:
        self.root = Path(root)
        self.cache_dir = self.root / "stable-cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._registry = registry
        self._journal = journal

    def _entry_path(self, stable_key: str) -> Path:
        return self.cache_dir / f"{stable_key}.json"

    def store_success(
        self,
        *,
        material: CacheKeyMaterial,
        source_receipt: Mapping[str, Any],
        artifacts: Sequence[CachedArtifactSnapshot],
    ) -> str:
        """Persist a reusable cache entry from a successful, non-retry execution."""
        if not receipt_is_cache_reusable(source_receipt):
            raise LineageError("source receipt is not cache-reusable")
        stable_key = compute_stable_cache_key(material)
        entry = {
            "stableCacheKey": stable_key,
            "sourceReceipt": _canonical_mapping(source_receipt),
            "artifacts": [artifact.as_dict() for artifact in artifacts],
        }
        encoded = (
            json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            + "\n"
        ).encode("utf-8")
        path = self._entry_path(stable_key)
        with path.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        return stable_key

    def _restore_artifacts(self, artifacts: Sequence[Mapping[str, Any]]) -> None:
        for artifact in artifacts:
            artifact_id = str(artifact["artifactId"])
            if artifact_id in self._registry.list_ids():
                continue
            self._registry.register(
                artifact_id=artifact_id,
                content=artifact["content"],
                schema=str(artifact["schema"]),
                producing_node=str(artifact["producingNode"]),
                input_revision=str(artifact["inputRevision"]),
                verification_evidence=list(artifact.get("verificationEvidence") or ()),
            )

    def try_cache_hit(
        self,
        *,
        run_id: str,
        node_id: str,
        material: CacheKeyMaterial,
        receipt_payload: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        """Write a run-scoped receipt with cacheHit=true when stable reuse applies."""
        stable_key = compute_stable_cache_key(material)
        path = self._entry_path(stable_key)
        if not path.is_file():
            return None
        entry = json.loads(path.read_text(encoding="utf-8"))
        source_receipt = entry.get("sourceReceipt")
        if not isinstance(source_receipt, Mapping) or not receipt_is_cache_reusable(
            source_receipt
        ):
            return None
        artifacts = entry.get("artifacts")
        if not isinstance(artifacts, list):
            raise LineageError(f"cache entry {stable_key} has invalid artifacts")
        self._restore_artifacts(artifacts)
        hit_payload = {
            **dict(receipt_payload),
            "cacheHit": True,
            "stableCacheKey": stable_key,
            "restoredArtifacts": [
                str(artifact["artifactId"]) for artifact in artifacts
            ],
        }
        idempotency_key = f"{run_id}:{stable_key}:{node_id}"
        return self._journal.record(node_id, idempotency_key, hit_payload)
