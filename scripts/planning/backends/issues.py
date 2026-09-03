"""Issue-store backend adapter (PRD 082 phase 12 / R27)."""
from __future__ import annotations

import os
import re
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Iterator

from planning_canonical import DOC_REVIEW_MARKER, MARKER_UNIT_ID

from ._common import content_hash, finalize_materialize_from_get, log_operation
from .issues_helpers import (
    issue_index_key,
    mutate_issue_unit_index,
    mutate_put_journal,
    read_issue_unit_index_locked,
    read_put_journal_locked,
    self_heal_issue_unit_index,
)
from .memory_cache import ReplicatedPlanningCacheBackend
from ..model import StoreResult
from ..repository import PlanningStoreBackend
from issues_lib import IssueRevisionConflict


def _ps():
    import planning_store as ps

    return ps


def fail(error: str, exit_code: int = 2, **extra):
    _ps().fail(error, exit_code, **extra)


DOC_REVIEW_COMMENT_MARKER = DOC_REVIEW_MARKER
_DOC_REVIEW_OPEN_MARKER = re.compile(r"<!--\s*sw-doc-review\s*-->", re.IGNORECASE)
_DOC_REVIEW_FACADE_AUTHORIZED: ContextVar[bool] = ContextVar(
    "doc_review_facade_authorized",
    default=False,
)


class DocReviewCommentFacadeRequired(Exception):
    """Doc-review marked issue-comment refused outside facade-validated path (PRD 341 R1/R2)."""

    def __init__(self, message: str = "doc-review-comment-facade-required") -> None:
        self.code = "doc-review-comment-facade-required"
        super().__init__(message)


def is_doc_review_comment_write(body: str, markers: list[str] | None) -> bool:
    marker_list = list(markers or [])
    if DOC_REVIEW_COMMENT_MARKER in marker_list:
        return True
    text = body or ""
    return bool(_DOC_REVIEW_OPEN_MARKER.search(text))


def assert_adapter_issue_comment_allowed(body: str, markers: list[str] | None) -> None:
    """Refuse sw-doc-review comment writes unless the facade authorized the post (PRD 341 R2)."""
    if not is_doc_review_comment_write(body, markers):
        return
    if not _DOC_REVIEW_FACADE_AUTHORIZED.get():
        raise DocReviewCommentFacadeRequired()


@contextmanager
def doc_review_facade_issue_comment_scope() -> Iterator[None]:
    token = _DOC_REVIEW_FACADE_AUTHORIZED.set(True)
    try:
        yield
    finally:
        _DOC_REVIEW_FACADE_AUTHORIZED.reset(token)


def resolve_doc_review_author_principal(client: Any) -> dict[str, Any]:
    """Resolve whoami principal for doc-review authorship (PRD 341 R14/R15, D4).

    GitHub v1 expects numeric ``user.id``. Application identity is not stable on PAT
    paths, so ``stableApplicationId`` is false.
    """
    getter = getattr(client, "authenticated_principal_id", None)
    if getter is None:
        return {
            "verdict": "fail",
            "error": "doc-review-author-unresolved",
            "detail": "whoami-unavailable",
        }
    try:
        principal = str(getter() or "").strip()
    except Exception as exc:  # noqa: BLE001
        return {
            "verdict": "fail",
            "error": "doc-review-author-unresolved",
            "detail": str(exc),
        }
    if not principal:
        return {
            "verdict": "fail",
            "error": "doc-review-author-unresolved",
            "detail": "whoami-empty",
        }
    # Numeric GitHub ids are digits; non-empty fixture ids also accepted.
    return {
        "verdict": "ok",
        "authorPrincipal": principal,
        "stableApplicationId": False,
    }


def assert_doc_review_authorship(
    *,
    expected_principal: str,
    comment_author_id: str,
    payload_claimed_author: str | None = None,
) -> dict[str, Any] | None:
    """Fail closed when authorship is not whoami-backed (PRD 341 R14/R16).

    Payload-claimed authors and broker account strings never satisfy authorship.
    """
    expected = str(expected_principal or "").strip()
    actual = str(comment_author_id or "").strip()
    claimed = str(payload_claimed_author or "").strip()
    if claimed and claimed != expected:
        return {
            "verdict": "fail",
            "error": "doc-review-authorship-rejected",
            "detail": "payload-claimed-author",
            "expectedPrincipal": expected,
            "payloadClaimedAuthor": claimed,
        }
    if claimed and not actual:
        return {
            "verdict": "fail",
            "error": "doc-review-authorship-rejected",
            "detail": "payload-claim-without-provider-author",
            "expectedPrincipal": expected,
        }
    if not expected:
        return {
            "verdict": "fail",
            "error": "doc-review-authorship-rejected",
            "detail": "expected-principal-missing",
        }
    if actual != expected:
        return {
            "verdict": "fail",
            "error": "doc-review-authorship-rejected",
            "detail": "whoami-mismatch",
            "expectedPrincipal": expected,
            "actualAuthorId": actual,
        }
    return None



class IssueStoreBackend(PlanningStoreBackend):
    backend_id = "issue-store"

    def __init__(self, root: Path, cfg: dict[str, Any]) -> None:
        super().__init__(root, cfg)
        key_result = _ps().validate_project_key(root, cfg)
        if key_result.get("verdict") != "ok":
            fail(key_result.get("message") or key_result.get("error", "invalid-project-key"))
        self.project_key = str(key_result["projectKey"])
        issues = _ps().resolve_issues_provider(cfg)
        self.issues_provider = str(issues.get("provider", "none"))
        self._client = _ps().IssuesClient(root, self.issues_provider)

    def _read_index(self) -> dict[str, str]:
        return read_issue_unit_index_locked(self.root)

    def _read_journal(self) -> dict[str, Any]:
        return read_put_journal_locked(self.root)

    def _mutate_index(self, mutator: Callable[[dict[str, str]], None]) -> None:
        mutate_issue_unit_index(self.root, mutator)

    def _mutate_journal(self, mutator: Callable[[dict[str, Any]], None]) -> None:
        mutate_put_journal(self.root, mutator)

    def _adapter_issue_comment(
        self,
        issue_id: str,
        body: str,
        *,
        markers: list[str] | None = None,
        **kwargs: Any,
    ):
        assert_adapter_issue_comment_allowed(body, markers)
        return self._client.issue_comment(issue_id, body, markers=markers, **kwargs)

    def _guard_duplicate_open_tasks_mint(self, unit_id: str) -> None:
        """Refuse minting a second open tasks issue for the same PRD slug (PRD 068 R8)."""
        if not unit_id.startswith("tasks"):
            return
        my_tail = _ps()._tasks_tail_from_unit_id(unit_id)
        search = getattr(self._client, "issue_search", None)
        if not callable(search):
            return
        for record in search(project_key=self.project_key, artifact_type="tasks"):
            other_id = str(getattr(record, "unit_id", "") or "").strip()
            if not other_id or other_id == unit_id:
                continue
            if not _ps()._tasks_slug_family_compatible(my_tail, _ps()._tasks_tail_from_unit_id(other_id)):
                continue
            labels = list(getattr(record, "labels", []) or [])
            if (
                str(getattr(record, "state", "")) == "open"
                and _ps().FROZEN_LABEL not in labels
                and _ps().status_from_labels(labels) != "complete"
            ):
                _ps().fail(
                    "duplicate-open-tasks-refused",
                    code="duplicate-open-tasks",
                    unitId=unit_id,
                    existingUnitId=other_id,
                )

    def derive_unit_status(self, unit_id: str, body_path: str) -> str:
        import planning_discover as pd
        try:
            record = self._lookup_record(unit_id, body_path)
        except _ps().IssueNotFound:
            return "unknown"
        if record is None:
            return "unknown"
        content = _ps().strip_markers_and_edges(_ps().reassemble_body(record.body, record.comments))
        native = pd._status_from_record(record, content)
        artifact_type = self._resolve_artifact_type(
            body_path, record=record, content=content, unit_id=unit_id
        )
        from _planning_pkg_loader import load_submodule

        return load_submodule("repository")._unified_status_from_native(native, artifact_type)

    def _resolve_artifact_type(
        self,
        body_path: str,
        *,
        record: Any | None = None,
        content: str | None = None,
        caller_type: str | None = None,
        unit_id: str | None = None,
    ) -> str:
        record_type = record.artifact_type if record is not None and record.artifact_type else None
        record_labels = list(record.labels) if record is not None and record.labels else None
        record_content = content
        if record is not None and not _ps().artifact_type_from_content(content or ""):
            record_content = _ps().strip_markers_and_edges(_ps().reassemble_body(record.body, record.comments))
        try:
            return _ps().require_artifact_type(
                body_path,
                record_type=record_type,
                content=record_content,
                caller_type=caller_type,
                labels=record_labels,
            )
        except _ps().ArtifactTypeUnresolved:
            _ps().fail(
                "artifact-type-unresolved",
                code="artifact-type-unresolved",
                bodyPath=body_path,
                unitId=unit_id,
            )

    def _issue_title(self, artifact_type: str, unit_id: str, content: str) -> str:
        # R11: human-readable title (doc H1 / frontmatter `title:`) instead of
        # the legacy `[project] type:unit-id` prefix -- see
        # `planning_canonical.human_readable_title` for the fallback chain.
        return _ps().human_readable_title(content, artifact_type, unit_id)

    def _labels_for(self, artifact_type: str, unit_id: str, content: str) -> list[str]:
        # R11: `unit_id_label` plus the doc's structural frontmatter keys
        # (status/topic/depends/absorbs/amends/visibility) are additive
        # provider-native label projections -- never a substitute for the
        # frontmatter itself, which stays embedded in `content` (dual-read
        # window, D5). Recomputed on every put() so an old (pre-R11) issue's
        # labels are backfilled the next time it is written through this
        # path, in addition to the read-time backfill in `_lookup_record`.
        labels = {_ps().project_label(self.project_key), _ps().type_label(artifact_type), _ps().unit_id_label(unit_id)}
        labels.update(_ps().structural_labels_from_content(content))
        return sorted(labels)

    def _record_to_snapshot(self, record: Any) -> Any:
        return _ps().IssueSnapshot(
            title=record.title,
            body=record.body,
            state=record.state,
            labels=list(record.labels),
            comments=list(record.comments),
            native_links=list(record.native_links),
            etag=record.etag,
            updated_at=record.updated_at,
        )

    def _canonical_content_from_record(self, record: Any, unit_id: str) -> str:
        full_body = _ps().reassemble_body(record.body, record.comments)
        # PRD 094 R2 — parse sw-edges before strip; edges authoritative over labels on read.
        sw_edges_block = _ps().parse_edges_block(full_body)
        operator_content = self._extract_content(record)
        if _ps().has_raw_yaml_frontmatter(operator_content):
            return operator_content
        if _ps().is_hybrid_operator_body(operator_content):
            return _ps().canonical_content_from_operator(
                list(record.labels),
                operator_content,
                unit_id=unit_id,
                sw_edges_block=sw_edges_block,
            )
        return operator_content

    def _resolve_canonical_body_for_op(
        self,
        unit_id: str,
        body_path: str,
        record: Any,
        *,
        projection_mirrors: list[dict[str, Any]] | None = None,
        prefer: str | None = None,
    ) -> dict[str, Any]:
        """R26 — get/freeze resolve LCD Issue or Document-backed body; never projection SoT."""
        content = self._canonical_content_from_record(record, unit_id)
        labels = list(getattr(record, "labels", []) or [])
        resolved = _ps().resolve_canonical_freeze_body(
            unit_id=unit_id,
            body_path=body_path,
            body=content,
            labels=labels,
            projection_mirrors=projection_mirrors,
            prefer=prefer,
        )
        if resolved.get("verdict") != "pass":
            _ps().fail(
                str(resolved.get("error") or "canonical-body-unresolved"),
                code=str(resolved.get("error") or "canonical-body-unresolved"),
                unitId=unit_id,
                bodyPath=body_path,
                bodySource=resolved.get("bodySource"),
                typedDrift=resolved.get("typedDrift"),
            )
        return resolved

    def _extract_content(self, record: Any) -> str:
        full_body = _ps().reassemble_body(record.body, record.comments)
        if not _ps().verify_project_scope(full_body, self.project_key):
            _ps().fail(
                "project-scope-violation",
                code="project-scope-violation",
                unitId=record.unit_id,
                projectKey=self.project_key,
            )
        if not _ps().verify_unit_id(full_body, record.unit_id):
            _ps().fail("unit-id-mismatch", code="unit-id-mismatch", unitId=record.unit_id)
        body_edges = _ps().parse_edges_block(full_body)
        try:
            _ps().reconcile_edges(body_edges, record.native_links)
        except ValueError as exc:
            _ps().fail(str(exc), code="edge-divergence")
        return _ps().strip_markers_and_edges(full_body)


    def _verify_frozen_integrity(self, record: Any) -> None:
        if _ps().FREEZE_INCOMPLETE_LABEL in record.labels:
            _ps().fail("freeze-incomplete", code="freeze-incomplete", unitId=record.unit_id)
        if _ps().FROZEN_LABEL not in record.labels:
            return
        recorded = _ps().parse_freeze_record_hash(record.comments)
        if not recorded:
            _ps().fail("missing-freeze-record", code="lifecycle-tombstone", unitId=record.unit_id)
        current = _ps().canonical_hash(self._record_to_snapshot(record))
        if current != recorded:
            _ps().fail(
                "tamper-detected",
                code="tamper-detected",
                unitId=record.unit_id,
                recordedHash=recorded,
                currentHash=current,
            )

    def _guard_write_visibility(self, unit_id: str, body_path: str, content: str) -> None:
        _ps().issue_store_visibility_gate(self.root, self.cfg, unit_id, body_path, content)

    def _guard_write_secrets(self, *texts: str, path_hint: str | None = None) -> None:
        for chunk in texts:
            if chunk:
                _ps().secret_scan_text(chunk, path_hint=path_hint)

    def _find_linked_brainstorm(self, prd_unit_id: str) -> Any | None:
        matches = self._client.issue_search(project_key=self.project_key, artifact_type="brainstorm")
        for record in matches:
            full_body = _ps().reassemble_body(record.body, record.comments)
            edges = _ps().parse_edges_block(full_body)
            if not edges:
                continue
            for edge in edges.get("edges") or []:
                if isinstance(edge, dict) and edge.get("target") == prd_unit_id:
                    return record
        return None

    def _distill_brainstorm_rationale(self, brainstorm: Any, prd_unit_id: str) -> dict[str, Any]:
        if os.environ.get("SW_FREEZE_DISTILL_FAIL", "").strip() in {"1", "true", "yes"}:
            raise RuntimeError("distillation-forced-fail")
        content = self._extract_content(brainstorm)
        if _ps().contains_raw_transcript(content):
            raise RuntimeError("raw-transcript-in-brainstorm")
        excerpt = content[:4000]
        redacted = _ps().redact_content(excerpt)
        mem = ReplicatedPlanningCacheBackend(self.root, self.cfg)
        mem_result = mem.put(
            f"brainstorm-{brainstorm.unit_id}",
            f"docs/brainstorms/{brainstorm.unit_id}.md",
            redacted,
            content_class="research",
        )
        pointer = (
            f"<!-- sw-memory-pointer -->\n"
            f"memoryUnit: {mem_result.unit_id}\n"
            f"prdUnit: {prd_unit_id}\n"
            f"brainstormUnit: {brainstorm.unit_id}\n"
        )
        self._guard_write_secrets(pointer, path_hint="freeze-memory-pointer")
        self._adapter_issue_comment(brainstorm.id, pointer, markers=["sw-memory-pointer"])
        closed = self._client.issue_update(brainstorm.id, state="closed", if_match=brainstorm.etag)
        return {"memoryUnitId": mem_result.unit_id, "brainstormUnitId": brainstorm.unit_id, "etag": closed.etag}

    def _maybe_backfill_labels(self, record: Any, unit_id: str) -> Any:
        """R11 dual-read backfill: an issue resolved via the pre-R11 body-
        marker/frontmatter fallback (no `sw:unit:*` / `sw:<type>` label yet)
        gets those structural labels written back immediately, so the next
        read/discover pass no longer needs the body fallback for it. Best
        effort only -- a frozen/put-incomplete issue, a stale etag, or a
        provider error here must never block the read or put already in
        progress; the label projection simply catches up on the next write.
        """
        if _ps().FROZEN_LABEL in record.labels or _ps().PUT_INCOMPLETE_LABEL in record.labels:
            return record
        content = _ps().strip_markers_and_edges(_ps().reassemble_body(record.body, record.comments))
        artifact_type = (
            record.artifact_type
            or _ps().artifact_type_from_labels(record.labels)
            or _ps().artifact_type_from_content(content)
        )
        if not _ps().is_resolved_artifact_type(artifact_type):
            return record
        missing: set[str] = set()
        if not _ps().unit_id_from_labels(record.labels):
            missing.add(_ps().unit_id_label(unit_id))
        if artifact_type and not _ps().artifact_type_from_labels(record.labels):
            missing.add(_ps().type_label(artifact_type))
        if not missing:
            return record
        try:
            updated = self._client.issue_label(
                record.id,
                sorted(set(record.labels) | missing),
                if_match=record.etag,
            )
        except (
            _ps().IssueRevisionConflict,
            _ps().IssueCapabilityError,
            _ps().IssueBudgetExhausted,
            _ps().IssueTombstone,
            _ps().IssueTransferred,
        ):
            return record
        except RuntimeError:
            # Provider-level HTTP error (e.g. GitHub 422 invalid-label-name on an
            # oversized `sw:unit:<id>` -- gap-085): the label projection is a
            # purely additive optimization over the frontmatter/body-marker dual
            # -read source of truth, never the read/put's source of truth itself,
            # so degrade to a no-op exactly as this method's own docstring
            # promises rather than propagating an uncaught traceback.
            return record
        return updated

    def _lookup_record(self, unit_id: str, body_path: str, *, content: str | None = None) -> Any:
        for candidate in _ps().unit_id_lookup_candidates(self.root, unit_id):
            record = self._lookup_record_candidate(candidate, body_path, content=content)
            if record is not None:
                return record
        raise _ps().IssueNotFound(f"no issue for unit {unit_id}")

    def _lookup_record_candidate(self, unit_id: str, body_path: str, *, content: str | None = None) -> Any | None:
        idx_key = issue_index_key(self.project_key, unit_id)
        issue_id = self._read_index().get(idx_key)
        if issue_id:
            try:
                record = self._client.issue_get(issue_id)
            except _ps().IssueNotFound:
                record = None
            except (_ps().IssueTombstone, _ps().IssueTransferred, _ps().IssueBudgetExhausted) as exc:
                _ps().handle_issue_client_error(exc)
            else:
                if _ps().verify_project_scope(record.body, self.project_key):
                    return self._maybe_backfill_labels(record, unit_id)
        search_kwargs: dict[str, Any] = {
            "project_key": self.project_key,
            "unit_id": unit_id,
        }
        path_inferred = _ps().infer_artifact_type(body_path)
        if path_inferred != _ps().ARTIFACT_TYPE_UNRESOLVED:
            search_kwargs["artifact_type"] = path_inferred
        elif content:
            content_type = _ps().artifact_type_from_content(content)
            if content_type:
                search_kwargs["artifact_type"] = content_type
        matches = self._client.issue_search(**search_kwargs)
        if not matches:
            return None
        record = matches[0]
        self._mutate_index(lambda index: index.__setitem__(idx_key, record.id))
        self._register_native_unit_alias(unit_id, record)
        return self._maybe_backfill_labels(record, unit_id)


    def _register_native_unit_alias(self, caller_unit_id: str, record: Any) -> None:
        """R19 — index namespaced native ids and legacy compatibility aliases."""
        native_id = _ps().format_native_unit_id(self.issues_provider, int(record.number))
        if _ps().is_namespaced_native_unit_id(caller_unit_id):
            canonical = caller_unit_id
        else:
            canonical = native_id
            _ps().register_legacy_unit_mapping(self.root, caller_unit_id, native_id)

        def _update(index: dict[str, str]) -> None:
            index[issue_index_key(self.project_key, canonical)] = record.id
            if caller_unit_id != canonical:
                index[issue_index_key(self.project_key, caller_unit_id)] = record.id

        self._mutate_index(_update)

    def _resolve_put_edge_projection(
        self,
        existing: Any | None,
        store_content: str,
        *,
        canonical_content: str | None = None,
    ) -> tuple[str, list[dict[str, Any]] | None, list[dict[str, Any]] | None]:
        """Merge absorbs into sw-edges on put; preserve native links (PRD 094 R1/R13)."""
        return _ps().resolve_put_edge_projection(
            store_content=store_content,
            canonical_content=canonical_content,
            existing_body=existing.body if existing is not None else None,
            existing_native_links=list(existing.native_links or []) if existing is not None else None,
        )

    def _record_artifact_type(self, record: Any) -> str:
        content = _ps().strip_markers_and_edges(_ps().reassemble_body(record.body, record.comments))
        return (
            str(getattr(record, "artifact_type", "") or "").strip()
            or _ps().artifact_type_from_labels(list(getattr(record, "labels", []) or []))
            or _ps().artifact_type_from_content(content)
            or ""
        )

    def _record_unit_id(self, record: Any) -> str:
        labels = list(getattr(record, "labels", []) or [])
        from_labels = _ps().unit_id_from_labels(labels)
        if from_labels:
            return from_labels
        raw = str(getattr(record, "unit_id", "") or "").strip()
        if raw:
            return raw
        body = getattr(record, "body", "") or ""
        m = MARKER_UNIT_ID.search(body)
        return m.group(1).strip() if m else ""

    def _guard_unit_id_marker_reuse(
        self,
        unit_id: str,
        artifact_type: str,
        existing: Any | None,
    ) -> None:
        """PRD 339 R39 — refuse sw-unit-id marker reuse across artifact types."""
        def _refuse(match: Any, match_type: str) -> None:
            fail(
                "unit-id-marker-reuse",
                code="unit-id-marker-reuse",
                unitId=unit_id,
                existingArtifactType=match_type,
                requestedArtifactType=artifact_type,
                issueId=str(getattr(match, "id", "") or ""),
            )

        if existing is not None:
            existing_type = self._record_artifact_type(existing)
            if existing_type and existing_type != artifact_type:
                _refuse(existing, existing_type)

        search = getattr(self._client, "issue_search", None)
        if not callable(search):
            return
        matches = self._client.issue_search(project_key=self.project_key, unit_id=unit_id)
        for match in matches or []:
            if existing is not None and str(getattr(match, "id", "")) == str(getattr(existing, "id", "")):
                continue
            match_type = self._record_artifact_type(match)
            if match_type and match_type != artifact_type:
                _refuse(match, match_type)

    def self_heal_unit_index(self) -> dict[str, Any]:
        """Expose R39 index self-heal for doctor/closeout callers."""

        def _resolve(issue_id: str) -> Any | None:
            try:
                return self._client.issue_get(issue_id)
            except Exception:
                return None

        return self_heal_issue_unit_index(
            self.root,
            project_key=self.project_key,
            resolve_record=_resolve,
            record_unit_id=self._record_unit_id,
            record_artifact_type=self._record_artifact_type,
        )

    def put(self, unit_id: str, body_path: str, content: str, *, content_class: str | None = None) -> StoreResult:
        _ps().reject_bare_integer_unit_id(unit_id)
        self._guard_write_visibility(unit_id, body_path, content)
        self._guard_write_secrets(content, path_hint=body_path)
        # R39 — heal polluted index entries before lookup/create.
        self.self_heal_unit_index()
        existing: Any | None
        try:
            existing = self._lookup_record(unit_id, body_path, content=content)
        except _ps().IssueNotFound:
            existing = None
        # R39 — requested type from content/path, not existing record preference.
        requested_type = _ps().artifact_type_from_content(content) or ""
        if not _ps().is_resolved_artifact_type(requested_type):
            inferred = _ps().infer_artifact_type(body_path)
            requested_type = inferred if _ps().is_resolved_artifact_type(inferred) else ""
        if requested_type:
            self._guard_unit_id_marker_reuse(unit_id, requested_type, existing)
        artifact_type = self._resolve_artifact_type(
            body_path, record=existing, content=content, unit_id=unit_id
        )
        if not requested_type:
            self._guard_unit_id_marker_reuse(unit_id, artifact_type, existing)
        if existing is None and artifact_type == "tasks":
            self._guard_duplicate_open_tasks_mint(unit_id)
        title = self._issue_title(artifact_type, unit_id, content)
        labels = self._labels_for(artifact_type, unit_id, content)
        store_content = _ps().operator_body_from_canonical(content) if _ps().has_raw_yaml_frontmatter(content) else content
        store_content, put_edges, put_native_links = self._resolve_put_edge_projection(
            existing, store_content, canonical_content=content
        )
        body = _ps().compose_issue_body(
            self.project_key,
            artifact_type,
            unit_id,
            store_content,
            edges=put_edges,
            native_links=put_native_links,
        )
        body, extra_comments = _ps().chunk_body_if_needed(body, [], provider=self.issues_provider)
        idx_key = issue_index_key(self.project_key, unit_id)
        chunked = bool(extra_comments)
        # R26: a chunked put cannot commit its head body, its overflow
        # comments, and its real-id manifest rewrite in one atomic provider
        # call. Mark the issue `sw:put-incomplete` for the duration of that
        # multi-step write so a crash mid-flight leaves a durable, doctor-
        # visible signal instead of a manifest silently pointing at synthetic
        # ids that were never a real comment. Cleared only once the manifest
        # rewrite below actually succeeds.
        head_labels = sorted(set(labels) | {_ps().PUT_INCOMPLETE_LABEL}) if chunked else labels
        create_kwargs: dict[str, Any] = {}
        update_kwargs: dict[str, Any] = {}
        if put_native_links is not None:
            create_kwargs["native_links"] = put_native_links
            update_kwargs["native_links"] = put_native_links
        if existing is None:
            record = self._client.issue_create(
                title=title,
                body=body,
                labels=head_labels,
                project_key=self.project_key,
                artifact_type=artifact_type,
                unit_id=unit_id,
                **create_kwargs,
            )
        else:
            record = existing
            try:
                record = self._client.issue_update(
                    record.id,
                    title=title,
                    body=body,
                    labels=head_labels,
                    if_match=record.etag,
                    **update_kwargs,
                )
            except _ps().IssueRevisionConflict as exc:
                _ps().fail(
                    "revision-conflict",
                    code="revision-conflict",
                    expected=exc.expected,
                    actual=exc.actual,
                )
        # R26: persist the unit->issue index (and, for a chunked body, a
        # journal entry) immediately after the head write succeeds -- before
        # posting a single overflow comment -- so a crash anywhere past this
        # point still resolves a retry of this same unit id back to THIS
        # issue instead of minting a duplicate (idempotent resume).
        self._mutate_index(lambda index: index.__setitem__(idx_key, record.id))
        self._register_native_unit_alias(unit_id, record)
        if chunked:
            self._mutate_journal(
                lambda journal: journal.__setitem__(
                    idx_key,
                    {
                        "unitId": unit_id,
                        "issueId": record.id,
                        "step": "body-written",
                        "expectedChunks": len(extra_comments),
                        "postedCommentIds": [],
                    },
                )
            )
        chunk_comment_ids: list[str] = []
        for comment in extra_comments:
            self._guard_write_secrets(comment.body, path_hint=body_path)
            posted = self._adapter_issue_comment(record.id, comment.body, markers=comment.markers)
            chunk_comment_ids.append(posted.id)
            record = self._client.issue_get(record.id)

            def _journal_pending(journal: dict[str, Any]) -> None:
                entry = journal[idx_key]
                entry["step"] = "comments-pending"
                entry["postedCommentIds"] = list(chunk_comment_ids)

            self._mutate_journal(_journal_pending)
        if chunk_comment_ids:
            # R8: `body` still carries the synthetic placeholder chunk ids
            # assigned before the provider issued real comment ids above;
            # rewrite the manifest with the real ids before persisting so
            # `reassemble_body` matches comments directly instead of falling
            # back to positional matching, which can select a stale overflow
            # comment left over from an earlier put.
            rewritten_body = _ps().rewrite_chunk_manifest_ids(body, chunk_comment_ids)
            final_labels = sorted(set(record.labels) - {_ps().PUT_INCOMPLETE_LABEL})
            if rewritten_body != record.body or final_labels != sorted(record.labels):
                try:
                    record = self._client.issue_update(
                        record.id,
                        body=rewritten_body,
                        labels=final_labels,
                        if_match=record.etag,
                    )
                except _ps().IssueRevisionConflict as exc:
                    # R26: fail closed -- the issue is left at its prior
                    # (pre-this-update) etag, still carrying
                    # _ps().PUT_INCOMPLETE_LABEL and its journal entry, both
                    # visible to `planning-doctor.py` (`put-partial`,
                    # `chunk-cardinality-mismatch`) until a retry converges.
                    _ps().fail(
                        "revision-conflict",
                        code="revision-conflict",
                        expected=exc.expected,
                        actual=exc.actual,
                    )
                record = self._client.issue_get(record.id)
        if chunked:
            self._mutate_journal(lambda journal: journal.pop(idx_key, None))
        digest = _ps().canonical_hash(self._record_to_snapshot(record))
        log_operation("put", unit_id, body_path, content, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=content, hash=digest)

    def get(self, unit_id: str, body_path: str) -> StoreResult:
        try:
            record = self._lookup_record(unit_id, body_path)
        except _ps().IssueNotFound:
            return StoreResult("missing", unit_id, body_path, self.backend_id, reason="not-found")
        except _ps().IssueCapabilityError as exc:
            _ps().fail(str(exc), code="issues-capability")
        except (_ps().IssueTombstone, _ps().IssueTransferred, _ps().IssueBudgetExhausted) as exc:
            _ps().handle_issue_client_error(exc)
        self._verify_frozen_integrity(record)
        # R26 — facade get resolves canonical LCD/Document-backed body; never prefers projection.
        resolved = self._resolve_canonical_body_for_op(unit_id, body_path, record)
        content = str(resolved["body"])
        digest = _ps().canonical_hash(self._record_to_snapshot(record))
        log_operation("get", unit_id, body_path, content, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=content, hash=digest)

    def exists(self, unit_id: str, body_path: str) -> StoreResult:
        try:
            self._lookup_record(unit_id, body_path)
        except _ps().IssueNotFound:
            log_operation("exists", unit_id, body_path, None, self.backend_id)
            return StoreResult("missing", unit_id, body_path, self.backend_id, reason="not-found")
        except _ps().IssueCapabilityError as exc:
            _ps().fail(str(exc), code="issues-capability")
        log_operation("exists", unit_id, body_path, None, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id)

    def materialize(self, unit_id: str, body_path: str, dest_path: Path) -> StoreResult:
        got = self.get(unit_id, body_path)
        return finalize_materialize_from_get(got, unit_id, body_path, self.backend_id, dest_path)

    def freeze(self, unit_id: str, body_path: str, *, distill: bool = True) -> dict[str, Any]:
        try:
            record = self._lookup_record(unit_id, body_path)
        except _ps().IssueNotFound:
            _ps().fail("issue-not-found", code="not-found", unitId=unit_id)
        except (_ps().IssueTombstone, _ps().IssueTransferred, _ps().IssueBudgetExhausted) as exc:
            _ps().handle_issue_client_error(exc)
        # R26 — freeze/hash SoT is LCD Issue or Document-backed body via facade resolution.
        resolved = self._resolve_canonical_body_for_op(unit_id, body_path, record)
        self._guard_write_visibility(unit_id, body_path, str(resolved["body"]))
        if _ps().FROZEN_LABEL in record.labels:
            _ps().fail("already-frozen", code="already-frozen", unitId=unit_id)
        try:
            record = self._client.issue_lock(record.id, if_match=record.etag)
            labels = sorted(set(record.labels) | {_ps().FROZEN_LABEL})
            record = self._client.issue_label(record.id, labels, if_match=record.etag)
            digest = _ps().canonical_hash(self._record_to_snapshot(record))
            freeze_body = _ps().build_freeze_record_body(digest)
            self._guard_write_secrets(freeze_body, path_hint="sw-freeze-record")
            self._adapter_issue_comment(record.id, freeze_body, markers=["sw-freeze-record"])
            record = self._client.issue_get(record.id)
        except _ps().IssueRevisionConflict as exc:
            _ps().fail("revision-conflict", code="revision-conflict", expected=exc.expected, actual=exc.actual)
        except (_ps().IssueBudgetExhausted, _ps().IssueTombstone, _ps().IssueTransferred) as exc:
            _ps().handle_issue_client_error(exc)

        distillation: dict[str, Any] | None = None
        freeze_content = self._extract_content(record)
        artifact_type = self._resolve_artifact_type(
            body_path, record=record, content=freeze_content, unit_id=unit_id
        )
        if distill and artifact_type == "prd":
            brainstorm = self._find_linked_brainstorm(unit_id)
            if brainstorm is not None:
                try:
                    distillation = self._distill_brainstorm_rationale(brainstorm, unit_id)
                except Exception as exc:  # noqa: BLE001 — fail-closed R48
                    labels = sorted(set(record.labels) | {_ps().FREEZE_INCOMPLETE_LABEL})
                    try:
                        record = self._client.issue_label(record.id, labels, if_match=record.etag)
                    except Exception:
                        pass
                    _ps().fail("freeze-incomplete", code="freeze-incomplete", reason=str(exc))

        absorb_linkage: dict[str, Any] | None = None
        if artifact_type == "prd":
            absorb_linkage = self._ensure_absorb_linkage_at_freeze(unit_id, freeze_content)
            if absorb_linkage.get("verdict") == "fail":
                labels = sorted(set(record.labels) | {_ps().FREEZE_INCOMPLETE_LABEL})
                try:
                    record = self._client.issue_label(record.id, labels, if_match=record.etag)
                except Exception:
                    pass
                _ps().fail(
                    "freeze-incomplete",
                    code="freeze-incomplete",
                    unitId=unit_id,
                    reason="absorb-linkage-failed",
                    absorbLinkage=absorb_linkage,
                )

        log_operation("freeze", unit_id, body_path, None, self.backend_id)
        return {
            "verdict": "ok",
            "unitId": unit_id,
            "bodyPath": body_path,
            "hash": digest,
            "locked": True,
            "labels": list(record.labels),
            "distillation": distillation,
            "bodySource": resolved.get("bodySource"),
            "freezeAuthority": resolved.get("freezeAuthority"),
            "absorbLinkage": absorb_linkage,
        }

    def _ensure_absorb_linkage_at_freeze(self, unit_id: str, content: str) -> dict[str, Any]:
        from planning_gap_capture import record_absorb_linkage

        fm = _ps()._migrate_issue_store().parse_frontmatter_fields(content)
        prd_num = _ps()._prd_number_from_unit_id(unit_id)
        absorbs = _ps()._parse_absorbs_targets(fm.get("absorbs", ""))
        gap_targets = [g for g in absorbs if "gap" in g or g.startswith("gap-")]
        planning_issues = _ps().parse_planning_issues_refs(fm.get("planningIssues", ""))
        if not gap_targets and not planning_issues:
            return {"verdict": "skipped", "reason": "no-absorb-targets"}
        return record_absorb_linkage(
            self.root,
            prd_unit_id=unit_id,
            prd_number=prd_num,
            gap_unit_ids=gap_targets or None,
            planning_issues=planning_issues or None,
            dry_run=False,
        )

    def repin_freeze_after_close(self, record: Any) -> dict[str, Any]:
        """Append newest sw-freeze-record for post-close state+labels (PRD 275 R1/R13/R14).

        Idempotent: when the latest freeze hash already matches the current
        canonical snapshot, returns noop. Failures are typed so closeout can
        surface not-ready / partial-apply without silent tamper on next get.
        """
        if _ps().FROZEN_LABEL not in list(record.labels) and not bool(getattr(record, "locked", False)):
            return {
                "verdict": "ok",
                "action": "skip",
                "reason": "not-frozen",
                "unitId": getattr(record, "unit_id", None),
            }
        if _ps().FREEZE_INCOMPLETE_LABEL in list(record.labels):
            return {
                "verdict": "fail",
                "error": "freeze-incomplete",
                "unitId": getattr(record, "unit_id", None),
            }
        try:
            fresh = self._client.issue_get(record.id)
        except (_ps().IssueTombstone, _ps().IssueTransferred, _ps().IssueBudgetExhausted) as exc:
            _ps().handle_issue_client_error(exc)
        except Exception as exc:  # noqa: BLE001
            return {
                "verdict": "fail",
                "error": "repin-fetch-failed",
                "detail": str(exc),
                "unitId": getattr(record, "unit_id", None),
                "partialApply": True,
            }
        digest = _ps().canonical_hash(self._record_to_snapshot(fresh))
        recorded = _ps().parse_freeze_record_hash(fresh.comments)
        if recorded == digest:
            return {
                "verdict": "ok",
                "action": "noop",
                "hash": digest,
                "alreadyPinned": True,
                "unitId": getattr(fresh, "unit_id", None),
            }
        freeze_body = _ps().build_freeze_record_body(digest)
        try:
            self._guard_write_secrets(freeze_body, path_hint="sw-freeze-record")
            self._adapter_issue_comment(fresh.id, freeze_body, markers=["sw-freeze-record"])
            after = self._client.issue_get(fresh.id)
        except IssueRevisionConflict as exc:
            return {
                "verdict": "fail",
                "error": "repin-revision-conflict",
                "detail": {"expected": exc.expected, "actual": exc.actual},
                "unitId": getattr(fresh, "unit_id", None),
                "partialApply": True,
                "closedOk": True,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "verdict": "fail",
                "error": "repin-append-failed",
                "detail": str(exc),
                "unitId": getattr(fresh, "unit_id", None),
                "partialApply": True,
                "closedOk": True,
            }
        after_hash = _ps().parse_freeze_record_hash(after.comments)
        current = _ps().canonical_hash(self._record_to_snapshot(after))
        if after_hash != current or current != digest:
            return {
                "verdict": "fail",
                "error": "repin-hash-mismatch",
                "recordedHash": after_hash,
                "currentHash": current,
                "expectedHash": digest,
                "unitId": getattr(after, "unit_id", None),
                "partialApply": True,
                "closedOk": True,
            }
        return {
            "verdict": "ok",
            "action": "repin",
            "hash": digest,
            "priorHash": recorded,
            "unitId": getattr(after, "unit_id", None),
        }

    def verify_frozen_hash(self, unit_id: str, body_path: str) -> dict[str, Any]:
        try:
            record = self._lookup_record(unit_id, body_path)
        except _ps().IssueNotFound:
            _ps().fail("issue-not-found", code="not-found", unitId=unit_id)
        except (_ps().IssueTombstone, _ps().IssueTransferred, _ps().IssueBudgetExhausted) as exc:
            _ps().handle_issue_client_error(exc)
        if _ps().FREEZE_INCOMPLETE_LABEL in record.labels:
            _ps().fail("freeze-incomplete", code="freeze-incomplete", unitId=unit_id)
        if _ps().FROZEN_LABEL not in record.labels:
            _ps().fail("not-frozen", code="not-frozen", unitId=unit_id)
        recorded = _ps().parse_freeze_record_hash(record.comments)
        if not recorded:
            _ps().fail("missing-freeze-record", code="lifecycle-tombstone", unitId=unit_id)
        current = _ps().canonical_hash(self._record_to_snapshot(record))
        if current != recorded:
            _ps().fail(
                "tamper-detected",
                code="tamper-detected",
                unitId=unit_id,
                recordedHash=recorded,
                currentHash=current,
            )
        return {
            "verdict": "ok",
            "unitId": unit_id,
            "bodyPath": body_path,
            "hash": current,
            "recordedHash": recorded,
        }

    def link_brainstorm_to_prd(self, brainstorm_unit_id: str, prd_unit_id: str) -> dict[str, Any]:
        try:
            brainstorm = self._lookup_record(brainstorm_unit_id, f"docs/brainstorms/{brainstorm_unit_id}.md")
        except _ps().IssueNotFound:
            _ps().fail("brainstorm-issue-missing", code="brainstorm-missing")
        edges = [{"rel": "spawned", "target": prd_unit_id, "targetType": "prd"}]
        raw_content = self._canonical_content_from_record(brainstorm, brainstorm_unit_id)
        self._guard_write_visibility(brainstorm_unit_id, f"docs/brainstorms/{brainstorm_unit_id}.md", raw_content)
        self._guard_write_secrets(raw_content, path_hint=f"docs/brainstorms/{brainstorm_unit_id}.md")
        body = _ps().compose_issue_body(
            self.project_key,
            "brainstorm",
            brainstorm_unit_id,
            raw_content,
            edges=edges,
        )
        self._guard_write_secrets(body, path_hint=f"docs/brainstorms/{brainstorm_unit_id}.md")
        try:
            updated = self._client.issue_update(brainstorm.id, body=body, if_match=brainstorm.etag)
        except _ps().IssueRevisionConflict as exc:
            _ps().fail("revision-conflict", code="revision-conflict", expected=exc.expected, actual=exc.actual)
        return {
            "verdict": "ok",
            "brainstormUnitId": brainstorm_unit_id,
            "prdUnitId": prd_unit_id,
            "etag": updated.etag,
        }
