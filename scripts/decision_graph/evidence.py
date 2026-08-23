"""Prototype and research evidence extraction, validation, and decision-node link-back."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = SCRIPT_DIR.parent
ROOT = SCRIPTS_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from gate_evidence import digest_bytes, digest_text, utc_now

API_VERSION = "decision-evidence/v1"
KIND_PROTOTYPE = "PrototypeEvidence"
KIND_RESEARCH = "ResearchEvidence"
REASON_EVIDENCE_REQUIRED = "evidence-required"
NODE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
RESEARCH_SCHEMA_PATH = ROOT / "core" / "sw-reference" / "research-evidence.schema.json"


class EvidenceSchemaError(ValueError):
    """Raised when an evidence record fails schema validation."""

    def __init__(self, message: str, *, code: str = "evidence:schema-invalid", path: list[str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.path = path or []


class RedactionRefusedError(RuntimeError):
    """Raised when memory-redact fail-closed refuses persisted evidence content."""

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_spec_content_hash(spec: dict[str, Any]) -> str:
    material = {key: value for key, value in spec.items() if key != "contentHash"}
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


def resolve_head_sha(worktree: Path) -> str:
    proc = _git(worktree, "rev-parse", "HEAD")
    return proc.stdout.strip() if proc.returncode == 0 else ""


def diff_digest(worktree: Path, base_ref: str) -> str:
    proc = _git(worktree, "diff", base_ref, "--binary")
    if proc.returncode != 0:
        return digest_text("")
    return digest_bytes((proc.stdout or "").encode("utf-8"))


def build_evidence_record(
    *,
    parent_decision_id: str,
    prototype_node_id: str,
    head_sha: str,
    content_hash: str,
    branch: str,
    worktree: str | None = None,
) -> dict[str, Any]:
    return {
        "apiVersion": API_VERSION,
        "kind": KIND_PROTOTYPE,
        "metadata": {
            "parentDecisionId": parent_decision_id,
            "prototypeNodeId": prototype_node_id,
            "linkedAt": utc_now(),
        },
        "spec": {
            "headSha": head_sha,
            "contentHash": content_hash,
            "branch": branch,
            "worktree": worktree,
            "linkBack": {
                "decisionNodeId": parent_decision_id,
                "hashLinked": True,
            },
        },
    }


def build_research_evidence_record(
    *,
    parent_decision_id: str,
    claim: str,
    sources: list[dict[str, Any]],
    source_kind: str,
    retrieved_at: str | None = None,
    linked_at: str | None = None,
) -> dict[str, Any]:
    retrieved = retrieved_at or utc_now()
    linked = linked_at or utc_now()
    normalized_sources: list[dict[str, Any]] = []
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise EvidenceSchemaError(
                f"sources[{index}] must be an object",
                path=["spec", "sources", str(index)],
            )
        entry: dict[str, Any] = {
            "uri": str(source.get("uri") or ""),
            "accessedAt": str(source.get("accessedAt") or ""),
            "digest": str(source.get("digest") or ""),
        }
        if "quote" in source and source.get("quote") is not None:
            entry["quote"] = str(source.get("quote"))
        normalized_sources.append(entry)

    spec_without_hash: dict[str, Any] = {
        "claim": str(claim or ""),
        "sources": normalized_sources,
        "retrievedAt": retrieved,
        "linkBack": {
            "decisionNodeId": parent_decision_id,
            "hashLinked": True,
        },
    }
    content_hash = compute_spec_content_hash(spec_without_hash)
    record = {
        "apiVersion": API_VERSION,
        "kind": KIND_RESEARCH,
        "metadata": {
            "parentDecisionId": parent_decision_id,
            "linkedAt": linked,
            "sourceKind": str(source_kind or ""),
        },
        "spec": {
            **spec_without_hash,
            "contentHash": content_hash,
        },
    }
    validate_research_evidence_record(record)
    return record


def _load_research_evidence_schema() -> dict[str, Any]:
    return json.loads(RESEARCH_SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate_node_id(value: str, path: list[str]) -> None:
    if not NODE_ID_PATTERN.fullmatch(value):
        raise EvidenceSchemaError("invalid node id", path=path)


def _validate_hash(value: str, path: list[str]) -> None:
    if not HASH_PATTERN.fullmatch(value):
        raise EvidenceSchemaError("invalid sha256 digest", path=path)


def validate_research_evidence_record(record: dict[str, Any]) -> None:
    if record.get("apiVersion") != API_VERSION:
        raise EvidenceSchemaError("invalid apiVersion", path=["apiVersion"])
    if record.get("kind") != KIND_RESEARCH:
        raise EvidenceSchemaError("invalid kind", path=["kind"])

    metadata = record.get("metadata")
    if not isinstance(metadata, dict):
        raise EvidenceSchemaError("metadata must be an object", path=["metadata"])
    parent_id = str(metadata.get("parentDecisionId") or "")
    _validate_node_id(parent_id, ["metadata", "parentDecisionId"])
    if not str(metadata.get("linkedAt") or "").strip():
        raise EvidenceSchemaError("metadata.linkedAt required", path=["metadata", "linkedAt"])
    if not str(metadata.get("sourceKind") or "").strip():
        raise EvidenceSchemaError("metadata.sourceKind required", path=["metadata", "sourceKind"])

    spec = record.get("spec")
    if not isinstance(spec, dict):
        raise EvidenceSchemaError("spec must be an object", path=["spec"])
    claim = str(spec.get("claim") or "")
    if not claim.strip():
        raise EvidenceSchemaError("spec.claim required", path=["spec", "claim"])

    sources = spec.get("sources")
    if not isinstance(sources, list) or not sources:
        raise EvidenceSchemaError("spec.sources must be a non-empty array", path=["spec", "sources"])
    for index, source in enumerate(sources):
        prefix = ["spec", "sources", str(index)]
        if not isinstance(source, dict):
            raise EvidenceSchemaError("source must be an object", path=prefix)
        if not str(source.get("uri") or "").strip():
            raise EvidenceSchemaError("source.uri required", path=prefix + ["uri"])
        if not str(source.get("accessedAt") or "").strip():
            raise EvidenceSchemaError("source.accessedAt required", path=prefix + ["accessedAt"])
        _validate_hash(str(source.get("digest") or ""), prefix + ["digest"])
        if "quote" in source and source["quote"] is not None and not isinstance(source["quote"], str):
            raise EvidenceSchemaError("source.quote must be a string", path=prefix + ["quote"])

    if not str(spec.get("retrievedAt") or "").strip():
        raise EvidenceSchemaError("spec.retrievedAt required", path=["spec", "retrievedAt"])
    content_hash = str(spec.get("contentHash") or "")
    _validate_hash(content_hash, ["spec", "contentHash"])
    expected_hash = compute_spec_content_hash(spec)
    if content_hash != expected_hash:
        raise EvidenceSchemaError(
            "spec.contentHash mismatch",
            code="evidence:content-hash-mismatch",
            path=["spec", "contentHash"],
        )

    link_back = spec.get("linkBack")
    if not isinstance(link_back, dict):
        raise EvidenceSchemaError("spec.linkBack must be an object", path=["spec", "linkBack"])
    link_id = str(link_back.get("decisionNodeId") or "")
    _validate_node_id(link_id, ["spec", "linkBack", "decisionNodeId"])
    if link_id != parent_id:
        raise EvidenceSchemaError(
            "spec.linkBack.decisionNodeId must equal metadata.parentDecisionId",
            path=["spec", "linkBack", "decisionNodeId"],
        )
    if link_back.get("hashLinked") is not True:
        raise EvidenceSchemaError("spec.linkBack.hashLinked must be true", path=["spec", "linkBack", "hashLinked"])

    try:
        import jsonschema

        schema = _load_research_evidence_schema()
        jsonschema.validate(record, schema)
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001 — surface validation failures
        raise EvidenceSchemaError(str(exc)) from exc


def redact_evidence_text(text: str, *, field: str) -> str:
    import memory_redact
    from planning_visibility import resolve_emission_destination

    destination = resolve_emission_destination("handoff-032")
    try:
        return memory_redact.redact(text, destination=destination)
    except memory_redact.RedactionError as exc:
        raise RedactionRefusedError(str(exc), field=field) from exc


def _redact_record_for_write(record: dict[str, Any]) -> dict[str, Any]:
    kind = str(record.get("kind") or "")
    redacted = json.loads(json.dumps(record))
    spec = redacted.get("spec")
    if not isinstance(spec, dict):
        raise EvidenceSchemaError("spec must be an object", path=["spec"])

    if kind == KIND_RESEARCH:
        claim = str(spec.get("claim") or "")
        spec["claim"] = redact_evidence_text(claim, field="spec.claim")
        sources = spec.get("sources")
        if isinstance(sources, list):
            for index, source in enumerate(sources):
                if not isinstance(source, dict):
                    continue
                if "quote" in source and source.get("quote") is not None:
                    field = f"spec.sources[{index}].quote"
                    source["quote"] = redact_evidence_text(str(source["quote"]), field=field)
        spec["contentHash"] = compute_spec_content_hash(spec)
        validate_research_evidence_record(redacted)
    return redacted


def node_requires_evidence(node: dict[str, Any]) -> bool:
    from decision_graph.schema import NodeKind

    if str(node.get("kind") or "") != NodeKind.DECISION.value:
        return False
    return node.get("requiresEvidence") is True


def list_linked_evidence_paths(root: Path, parent_decision_id: str) -> list[Path]:
    paths: list[Path] = []
    legacy = root / ".cursor" / "sw-decision-evidence" / f"{parent_decision_id}.json"
    if legacy.is_file():
        paths.append(legacy)
    base = root / ".cursor" / "sw-decision-evidence" / parent_decision_id
    if base.is_dir():
        for kind in (KIND_PROTOTYPE, KIND_RESEARCH):
            collection = base / kind
            if collection.is_dir():
                paths.extend(sorted(collection.glob("*.json")))
    return paths


def has_linked_evidence(root: Path, parent_decision_id: str) -> bool:
    return bool(list_linked_evidence_paths(root, parent_decision_id))


def _evidence_record_kind(record: dict[str, Any]) -> str:
    return str(record.get("kind") or "")


def _evidence_record_hash(record: dict[str, Any]) -> str:
    spec = record.get("spec") if isinstance(record.get("spec"), dict) else {}
    content_hash = str(spec.get("contentHash") or "")
    if content_hash:
        return content_hash
    head_sha = str(spec.get("headSha") or "")
    if head_sha:
        return head_sha
    return ""


def linked_evidence_records(
    root: Path,
    parent_decision_id: str,
    kind: str | None = None,
) -> list[dict[str, Any]]:
    """Return linked evidence records for a parent decision, optionally filtered by kind."""
    records: list[dict[str, Any]] = []
    for path in list_linked_evidence_paths(root, parent_decision_id):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(document, dict):
            continue
        if kind is not None and _evidence_record_kind(document) != kind:
            continue
        records.append(document)
    return records


def collect_linked_evidence_hashes(
    root: Path,
    parent_decision_id: str,
    kind: str,
) -> list[str]:
    """Sorted unique content hashes for linked evidence of the given kind."""
    hashes: list[str] = []
    for record in linked_evidence_records(root, parent_decision_id, kind):
        digest = _evidence_record_hash(record)
        if digest:
            hashes.append(digest)
    return sorted(set(hashes))


def has_linked_evidence_kind(root: Path, parent_decision_id: str, kind: str) -> bool:
    return bool(collect_linked_evidence_hashes(root, parent_decision_id, kind))


def check_evidence_required(document: dict[str, Any], root: Path) -> dict[str, Any]:
    """Fail closed when resolved decision nodes require evidence but have none linked."""
    spec = document.get("spec") if isinstance(document.get("spec"), dict) else {}
    nodes = spec.get("nodes") if isinstance(spec.get("nodes"), list) else []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if not node_requires_evidence(node):
            continue
        if str(node.get("status") or "") != "resolved":
            continue
        node_id = str(node.get("id") or "")
        if not node_id:
            continue
        if not has_linked_evidence(root, node_id):
            return {
                "verdict": "fail",
                "reason": REASON_EVIDENCE_REQUIRED,
                "nodeId": node_id,
            }
    return {"verdict": "pass"}


def evidence_store_path(
    root: Path,
    parent_decision_id: str,
    kind: str | None = None,
    content_hash: str | None = None,
) -> Path:
    base = root / ".cursor" / "sw-decision-evidence" / parent_decision_id
    if kind is None:
        return base
    collection = base / kind
    if content_hash is None:
        return collection
    return collection / f"{content_hash}.json"


def write_evidence_record(root: Path, record: dict[str, Any]) -> Path:
    prepared = _redact_record_for_write(record)
    kind = str(prepared.get("kind") or "unknown")
    parent = str(prepared.get("metadata", {}).get("parentDecisionId") or "unknown")
    spec = prepared.get("spec") if isinstance(prepared.get("spec"), dict) else {}
    content_hash = str(spec.get("contentHash") or "")
    if kind == KIND_RESEARCH:
        validate_research_evidence_record(prepared)
    out = evidence_store_path(root, parent, kind, content_hash)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.is_file():
        existing = json.loads(out.read_text(encoding="utf-8"))
        if existing == prepared:
            return out
    out.write_text(json.dumps(prepared, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def _evidence_outcome(record: dict[str, Any]) -> str:
    kind = str(record.get("kind") or "")
    spec = record.get("spec") if isinstance(record.get("spec"), dict) else {}
    content_hash = str(spec.get("contentHash") or "")
    if kind == KIND_PROTOTYPE:
        head_sha = str(spec.get("headSha") or "")
        return f"evidence:{kind}:{content_hash}:head:{head_sha}"
    return f"evidence:{kind}:{content_hash}"


def link_evidence_to_decision(
    document: dict[str, Any],
    parent_decision_id: str,
    record: dict[str, Any],
) -> dict[str, Any]:
    """Attach hash-linked evidence summary onto the parent decision node resolution."""
    spec = document.get("spec") if isinstance(document.get("spec"), dict) else {}
    nodes = spec.get("nodes") if isinstance(spec.get("nodes"), list) else []
    linked = False
    outcome = _evidence_outcome(record)
    record_spec = record.get("spec") if isinstance(record.get("spec"), dict) else {}
    content_hash = str(record_spec.get("contentHash") or "")
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if str(node.get("id") or "") != parent_decision_id:
            continue
        resolution = node.get("resolution")
        if isinstance(resolution, dict):
            existing_outcome = str(resolution.get("outcome") or "")
            if content_hash and content_hash in existing_outcome:
                linked = True
                break
        rationale_payload: dict[str, Any] = {
            "evidenceRecord": record.get("apiVersion"),
            "kind": record.get("kind"),
            "contentHash": content_hash,
        }
        if record.get("kind") == KIND_PROTOTYPE:
            rationale_payload["headSha"] = record_spec.get("headSha")
        node["resolution"] = {
            "outcome": outcome,
            "rationale": json.dumps(rationale_payload, sort_keys=True),
        }
        if node.get("status") == "open":
            node["status"] = "resolved"
        linked = True
        break
    if not linked:
        return {
            "verdict": "fail",
            "cause": "evidence:parent-decision-missing",
            "parentDecisionId": parent_decision_id,
        }
    return {"verdict": "pass", "parentDecisionId": parent_decision_id, "graph": document}


def extract_prototype_evidence(
    worktree: Path,
    *,
    parent_decision_id: str,
    prototype_node_id: str,
    branch: str,
    base_ref: str = "HEAD~1",
) -> dict[str, Any]:
    head = resolve_head_sha(worktree)
    content_hash = diff_digest(worktree, base_ref)
    record = build_evidence_record(
        parent_decision_id=parent_decision_id,
        prototype_node_id=prototype_node_id,
        head_sha=head,
        content_hash=content_hash,
        branch=branch,
        worktree=str(worktree),
    )
    return {"verdict": "pass", "record": record}


def extract_and_link(
    root: Path,
    graph_document: dict[str, Any],
    worktree: Path,
    *,
    parent_decision_id: str,
    prototype_node_id: str,
    branch: str,
    base_ref: str = "HEAD~1",
) -> dict[str, Any]:
    extracted = extract_prototype_evidence(
        worktree,
        parent_decision_id=parent_decision_id,
        prototype_node_id=prototype_node_id,
        branch=branch,
        base_ref=base_ref,
    )
    if extracted.get("verdict") != "pass":
        return extracted
    record = extracted["record"]
    path = write_evidence_record(root, record)
    linked = link_evidence_to_decision(graph_document, parent_decision_id, record)
    if linked.get("verdict") != "pass":
        return linked
    return {
        "verdict": "pass",
        "evidencePath": str(path),
        "parentDecisionId": parent_decision_id,
        "record": record,
        "graph": linked.get("graph"),
    }
