"""Linear semantic CRUD backend (PRD 339 phase 9 / R33).

Maps planning-store create/get/update/search semantics onto LinearIssuesClient while
preserving unit ids, artifact types, statuses, labels, and canonical body hashes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from planning_canonical import (
    MARKER_ARTIFACT_TYPE,
    MARKER_UNIT_ID,
    artifact_type_from_labels,
    compose_issue_body,
    parse_body_marker,
    project_label,
    type_label,
    unit_id_from_labels,
)

from ._common import content_hash, finalize_materialize_from_get, log_operation
from ..model import StoreResult
from ..repository import PlanningStoreBackend

BACKEND_ID = "linear-semantic"
SPEC_REL_PATH = "core/providers/issues/linear.md"
PROGRAM_PRIORITY_ID = "linear-semantic-crud"


def _planning_store():
    import planning_store as ps

    return ps


def _semantic_labels(project_key: str, artifact_type: str, unit_id: str, content: str) -> list[str]:
    ps = _planning_store()
    labels = {project_label(project_key), type_label(artifact_type), ps.unit_id_label(unit_id)}
    labels.update(ps.structural_labels_from_content(content))
    return sorted(labels)


def _canonical_body_hash(record: Any) -> str:
    ps = _planning_store()
    snapshot = ps.IssueSnapshot(
        title=str(getattr(record, "title", "") or ""),
        body=str(getattr(record, "body", "") or ""),
        state=str(getattr(record, "state", "") or ""),
        labels=list(getattr(record, "labels", []) or []),
        comments=list(getattr(record, "comments", []) or []),
        native_links=list(getattr(record, "native_links", []) or []),
        etag=str(getattr(record, "etag", "") or ""),
        updated_at=str(getattr(record, "updated_at", "") or ""),
    )
    return ps.canonical_hash(snapshot)


def _semantic_payload(record: Any, *, project_key: str, unit_id: str, body_path: str) -> dict[str, Any]:
    ps = _planning_store()
    full_body = ps.reassemble_body(record.body, record.comments, linear_bind=True)
    operator_content = ps.strip_markers_and_edges(full_body)
    resolved_unit = unit_id_from_labels(record.labels) or parse_body_marker(full_body, MARKER_UNIT_ID) or unit_id
    resolved_type = (
        artifact_type_from_labels(record.labels)
        or parse_body_marker(full_body, MARKER_ARTIFACT_TYPE)
        or getattr(record, "artifact_type", "")
        or ps.infer_artifact_type(body_path)
    )
    canonical = operator_content
    if ps.has_raw_yaml_frontmatter(operator_content):
        canonical = operator_content
    elif ps.is_hybrid_operator_body(operator_content):
        sw_edges = ps.parse_edges_block(full_body)
        canonical = ps.canonical_content_from_operator(
            list(record.labels),
            operator_content,
            unit_id=resolved_unit,
            sw_edges_block=sw_edges,
        )
    return {
        "verdict": "ok",
        "issueId": str(getattr(record, "id", "") or ""),
        "unitId": resolved_unit,
        "artifactType": resolved_type,
        "labels": sorted(set(getattr(record, "labels", []) or [])),
        "state": str(getattr(record, "state", "") or ""),
        "etag": str(getattr(record, "etag", "") or ""),
        "bodyHash": content_hash(canonical),
        "canonicalHash": _canonical_body_hash(record),
        "content": canonical,
        "bodyPath": body_path,
        "projectKey": project_key,
    }


class LinearSemanticCrud:
    """Semantic create/get/update/search over LinearIssuesClient (R33)."""

    def __init__(
        self,
        root: Path,
        cfg: dict[str, Any],
        *,
        client: Any | None = None,
    ) -> None:
        self.root = Path(root)
        self.cfg = cfg
        store = cfg.get("planning", {}).get("store", {}) if isinstance(cfg.get("planning"), dict) else {}
        raw_key = store.get("projectKey") if isinstance(store, dict) else ""
        self.project_key = raw_key.strip() if isinstance(raw_key, str) else ""
        if client is not None:
            self._client = client
        else:
            from planning_linear_client import LinearIssuesClient

            self._client = LinearIssuesClient(self.root, cfg=cfg)

    def create(
        self,
        *,
        unit_id: str,
        body_path: str,
        content: str,
        artifact_type: str | None = None,
    ) -> dict[str, Any]:
        ps = _planning_store()
        resolved_type = (
            artifact_type
            or ps.artifact_type_from_content(content)
            or ps.infer_artifact_type(body_path)
        )
        title = ps.human_readable_title(content, resolved_type, unit_id)
        labels = _semantic_labels(self.project_key, resolved_type, unit_id, content)
        store_content = ps.operator_body_from_canonical(content) if ps.has_raw_yaml_frontmatter(content) else content
        body = compose_issue_body(self.project_key, resolved_type, unit_id, store_content)
        record = self._client.create(
            title=title,
            body=body,
            labels=labels,
            project_key=self.project_key,
            artifact_type=resolved_type,
            unit_id=unit_id,
        )
        payload = _semantic_payload(record, project_key=self.project_key, unit_id=unit_id, body_path=body_path)
        payload["action"] = "linear-semantic-create"
        return payload

    def get(self, issue_id: str, *, unit_id: str, body_path: str) -> dict[str, Any]:
        record = self._client.get(issue_id)
        payload = _semantic_payload(record, project_key=self.project_key, unit_id=unit_id, body_path=body_path)
        payload["action"] = "linear-semantic-get"
        return payload

    def update(
        self,
        issue_id: str,
        *,
        unit_id: str,
        body_path: str,
        content: str | None = None,
        labels: list[str] | None = None,
        if_match: str | None = None,
    ) -> dict[str, Any]:
        ps = _planning_store()
        patch: dict[str, Any] = {}
        if content is not None:
            resolved_type = ps.infer_artifact_type(body_path)
            title = ps.human_readable_title(content, resolved_type, unit_id)
            store_content = ps.operator_body_from_canonical(content) if ps.has_raw_yaml_frontmatter(content) else content
            patch["title"] = title
            patch["body"] = compose_issue_body(self.project_key, resolved_type, unit_id, store_content)
            if labels is None:
                labels = _semantic_labels(self.project_key, resolved_type, unit_id, content)
        if labels is not None:
            patch["labels"] = labels
        current = self._client.get(issue_id)
        if if_match and current.etag == if_match and not patch:
            payload = _semantic_payload(current, project_key=self.project_key, unit_id=unit_id, body_path=body_path)
            payload["action"] = "linear-semantic-update"
            payload["idempotent"] = True
            return payload
        record = self._client.update(issue_id, if_match=if_match or current.etag, **patch)
        payload = _semantic_payload(record, project_key=self.project_key, unit_id=unit_id, body_path=body_path)
        payload["action"] = "linear-semantic-update"
        return payload

    def search(
        self,
        *,
        project_key: str | None = None,
        artifact_type: str | None = None,
        unit_id: str | None = None,
        labels: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        key = project_key or self.project_key
        records = self._client.search(
            project_key=key,
            artifact_type=artifact_type,
            unit_id=unit_id,
            labels=labels,
        )
        out: list[dict[str, Any]] = []
        for record in records:
            resolved_unit = str(getattr(record, "unit_id", "") or unit_id or "")
            body_path = f"docs/planning/{resolved_unit}/body.md"
            payload = _semantic_payload(
                record,
                project_key=key,
                unit_id=resolved_unit,
                body_path=body_path,
            )
            payload["action"] = "linear-semantic-search"
            out.append(payload)
        return out


def wire_linear_semantic_crud(
    root: Path,
    cfg: dict[str, Any],
    *,
    client: Any | None = None,
) -> LinearSemanticCrud:
    """Facade entry — construct semantic CRUD via credential-broker-backed client path."""
    return LinearSemanticCrud(root, cfg, client=client)


def register_linear_semantic_store() -> dict[str, Any]:
    """Registration surface for ``planning_store_facade`` — semantic CRUD metadata."""
    return {
        "backendId": BACKEND_ID,
        "status": "recognized",
        "shipped": False,
        "specPath": SPEC_REL_PATH,
        "programPriorityId": PROGRAM_PRIORITY_ID,
        "verbs": ["create", "get", "update", "search"],
        "transport": {
            "clientModule": "scripts/planning_linear_client.py",
            "credentialBroker": True,
            "pagination": True,
            "retries": True,
            "normalizedErrors": ["auth-denied", "scope-failure", "graphql-error", "RATELIMITED"],
        },
        "preserves": ["unitId", "artifactType", "status", "labels", "canonicalBodyHash"],
    }


class LinearSemanticBackend(PlanningStoreBackend):
    """Planning-store backend delegating put/get to Linear semantic CRUD (R33)."""

    backend_id = BACKEND_ID

    def __init__(self, root: Path, cfg: dict[str, Any], *, client: Any | None = None) -> None:
        super().__init__(root, cfg)
        self._semantic = LinearSemanticCrud(root, cfg, client=client)

    def put(self, unit_id: str, body_path: str, content: str, *, content_class: str | None = None) -> StoreResult:
        del content_class
        ps = _planning_store()
        artifact_type = ps.infer_artifact_type(body_path)
        matches = self._semantic.search(project_key=self._semantic.project_key, unit_id=unit_id)
        if matches:
            issue_id = str(matches[0].get("issueId") or "")
            payload = self._semantic.update(
                issue_id,
                unit_id=unit_id,
                body_path=body_path,
                content=content,
            )
        else:
            payload = self._semantic.create(unit_id=unit_id, body_path=body_path, content=content, artifact_type=artifact_type)
        log_operation("put", unit_id, body_path, content, self.backend_id)
        return StoreResult(
            "ok",
            unit_id,
            body_path,
            self.backend_id,
            content=str(payload.get("content") or content),
            hash=str(payload.get("bodyHash") or content_hash(content)),
        )

    def get(self, unit_id: str, body_path: str) -> StoreResult:
        matches = self._semantic.search(project_key=self._semantic.project_key, unit_id=unit_id)
        if not matches:
            log_operation("get", unit_id, body_path, None, self.backend_id, notice="missing")
            return StoreResult("missing", unit_id, body_path, self.backend_id, reason="not-found")
        payload = matches[0]
        content = str(payload.get("content") or "")
        log_operation("get", unit_id, body_path, content, self.backend_id)
        return StoreResult(
            "ok",
            unit_id,
            body_path,
            self.backend_id,
            content=content,
            hash=str(payload.get("bodyHash") or content_hash(content)),
        )

    def exists(self, unit_id: str, body_path: str) -> StoreResult:
        got = self.get(unit_id, body_path)
        if got.verdict == "ok":
            return StoreResult("ok", unit_id, body_path, self.backend_id, content=got.content, hash=got.hash)
        return StoreResult("missing", unit_id, body_path, self.backend_id, reason="not-found")

    def materialize(self, unit_id: str, body_path: str, dest_path: Path) -> StoreResult:
        got = self.get(unit_id, body_path)
        return finalize_materialize_from_get(got, unit_id, body_path, self.backend_id, dest_path)
