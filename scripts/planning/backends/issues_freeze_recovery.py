"""Private freeze-recovery helpers for the issue-store backend."""
from __future__ import annotations

import os
import json
import re
from copy import deepcopy
from typing import Any

from ._common import log_operation
from .memory_cache import ReplicatedPlanningCacheBackend


def _ps():
    import planning_store as ps

    return ps


class IssueFreezeRecoveryMixin:
    """Brainstorm distillation and guarded incomplete-freeze recovery."""

    def _find_linked_brainstorm(self, prd_unit_id: str, *, require_unique: bool = False) -> Any | None:
        matches = self._client.issue_search(project_key=self.project_key, artifact_type="brainstorm")
        linked = []
        for record in matches:
            full_body = _ps().reassemble_body(record.body, record.comments)
            edges = _ps().parse_edges_block(full_body)
            if not edges:
                continue
            for edge in edges.get("edges") or []:
                if isinstance(edge, dict) and edge.get("target") == prd_unit_id:
                    if not require_unique:
                        return record
                    linked.append(record)
                    break
        if require_unique:
            # Recovery cannot infer that interrupted work was unnecessary from
            # absent search evidence, nor choose arbitrarily among candidates.
            if len(linked) != 1:
                raise RuntimeError("freeze-recovery-brainstorm-missing-or-ambiguous")
            return linked[0]
        return None

    def _distill_brainstorm_rationale(self, brainstorm: Any, prd_unit_id: str) -> dict[str, Any]:
        if os.environ.get("SW_FREEZE_DISTILL_FAIL", "").strip() in {"1", "true", "yes"}:
            raise RuntimeError("distillation-forced-fail")
        # Search results are projections; use a full read for identity and OCC.
        expected = brainstorm
        brainstorm = deepcopy(self._client.issue_get(expected.id))
        self._check_brainstorm_identity(brainstorm, expected, prd_unit_id, from_search_projection=True)
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
        if mem_result.verdict != "ok" or mem_result.content != redacted:
            raise RuntimeError("distillation-cache-result-invalid")
        # The cache preserves its ordinary fallback policy; configured remote
        # authority reports a dirty projection and must not satisfy required work.
        if mem._has_configured_remote_planning_authority() and "projection dirty" in (mem_result.notice or ""):
            raise RuntimeError("distillation-authority-incomplete")
        self._guard_write_secrets(pointer, path_hint="freeze-memory-pointer")
        pointers = [c for c in brainstorm.comments if "sw-memory-pointer" in c.markers or "<!-- sw-memory-pointer -->" in c.body]
        if pointers and (len(pointers) != 1 or pointers[0].body != pointer):
            raise RuntimeError("brainstorm-pointer-mismatch")
        if brainstorm.state == "closed" and not pointers:
            raise RuntimeError("closed-brainstorm-pointer-missing")
        if not pointers:
            self._adapter_issue_comment(brainstorm.id, pointer, markers=["sw-memory-pointer"])
        fresh = self._client.issue_get(brainstorm.id)
        self._check_brainstorm_identity(fresh, brainstorm, prd_unit_id)
        fresh_pointers = [c for c in fresh.comments if "sw-memory-pointer" in c.markers or "<!-- sw-memory-pointer -->" in c.body]
        if len(fresh_pointers) != 1 or fresh_pointers[0].body != pointer:
            raise RuntimeError("brainstorm-pointer-mismatch")
        old_comments = [c for c in brainstorm.comments if c not in pointers]
        if [c for c in fresh.comments if c not in fresh_pointers] != old_comments:
            raise RuntimeError("brainstorm-comment-drift")
        closed = fresh if fresh.state == "closed" else self._client.issue_update(
            fresh.id, state="closed", if_match=fresh.etag
        )
        return {"memoryUnitId": mem_result.unit_id, "brainstormUnitId": brainstorm.unit_id,
                "etag": closed.etag, "notice": mem_result.notice}

    def _check_brainstorm_identity(
        self, fresh: Any, expected: Any, prd_unit_id: str, *, from_search_projection: bool = False
    ) -> None:
        for field in ("id", "unit_id", "project_key", "artifact_type", "title", "body", "labels", "state"):
            if getattr(fresh, field) != getattr(expected, field):
                raise RuntimeError(f"brainstorm-{field}-drift")
        # GitHub search omits native links. Establish them on the first full
        # read; require exact equality on every subsequent full-to-full check.
        if not from_search_projection and fresh.native_links != expected.native_links:
            raise RuntimeError("brainstorm-native_links-drift")
        if fresh.project_key != self.project_key or fresh.artifact_type != "brainstorm":
            raise RuntimeError("brainstorm-identity-mismatch")
        self._extract_content(fresh)
        edges = _ps().parse_edges_block(_ps().reassemble_body(fresh.body, fresh.comments)) or {}
        if not any(e.get("target") == prd_unit_id for e in edges.get("edges", []) if isinstance(e, dict)):
            raise RuntimeError("brainstorm-linkage-mismatch")

    def _check_recovery_review(self, record: Any, unit_id: str, body_path: str) -> None:
        from planning_doc_review_transport import (
            inspect_review_round_block, verify_manifest_binding, verify_round_integrity,
            find_completion_receipts, parse_completion_receipt, body_manifest_id, default_completion_idempotency_key,
            comments_pagination_complete, is_marked_doc_review_comment, is_marked_completion_receipt,
        )
        if not comments_pagination_complete(record):
            raise RuntimeError("review-pagination-incomplete")
        body = _ps().reassemble_body(record.body, record.comments)
        manifest, error = inspect_review_round_block(body)
        if error:
            raise RuntimeError("review-witness-malformed")
        if not manifest:
            if any(is_marked_doc_review_comment(c) or is_marked_completion_receipt(c) for c in record.comments):
                raise RuntimeError("review-witness-missing")
            if body_path != _ps()._default_body_path(unit_id, "prd"):
                raise RuntimeError("freeze-recovery-body-path-unbound")
            return
        artifact = manifest.get("artifact", {})
        # V1 permits unit-only evidence. An absent optional path is not a
        # historical default filename; canonical resolution already checked it.
        if artifact.get("bodyPath", body_path) != body_path or artifact.get("unitId", unit_id) != unit_id:
            raise RuntimeError("review-artifact-binding-invalid")
        if manifest.get("status") != "closed" or verify_manifest_binding(manifest, unit_id=unit_id, issue_id=record.id):
            raise RuntimeError("review-witness-binding-invalid")
        # Applied closed rounds retain the reviewed input hash. Do not reverify
        # that historical input against the subsequently applied artifact body.
        if verify_round_integrity(manifest=manifest, comments=list(record.comments), expected_author_id=""):
            raise RuntimeError("review-pins-drift")
        round_id = manifest["roundId"]
        manifest_id = body_manifest_id(issue_id=record.id, round_id=round_id)
        receipts = find_completion_receipts(list(record.comments), round_id=round_id,
            idempotency_key_value=default_completion_idempotency_key(round_id=round_id, manifest_id=manifest_id))
        candidates = [c for c in record.comments if is_marked_completion_receipt(c)
                      and (not parse_completion_receipt(c.body)
                           or parse_completion_receipt(c.body).get("roundId") == round_id)]
        if len(receipts) != 1 or len(candidates) != 1:
            raise RuntimeError("review-completion-missing-or-ambiguous")
        receipt = receipts[0][1]
        artifact = receipt.get("artifact", {})
        if (artifact.get("unitId") != unit_id or artifact.get("bodyPath", body_path) != body_path
                or receipt.get("manifestId") != manifest_id or receipt.get("verification") != "verified"
                or receipt.get("manifestRevisionToken") != manifest.get("artifactRevision")):
            raise RuntimeError("review-completion-binding-invalid")

    def _check_recovery_record(self, record: Any, entry: Any, unit_id: str, body_path: str,
                               *, complete: bool = False, require_native: bool = True) -> str:
        if (record.id != entry.id or record.unit_id != unit_id or record.project_key != self.project_key
                or record.artifact_type != "prd" or record.native_links != entry.native_links):
            raise RuntimeError("freeze-recovery-identity-drift")
        if require_native and getattr(record, "native_locked", None) is not True:
            raise RuntimeError("freeze-recovery-native-lock-unproven")
        if record.body != entry.body or record.comments != entry.comments:
            raise RuntimeError("freeze-recovery-body-or-witness-drift")
        resolved = self._resolve_canonical_body_for_op(unit_id, body_path, record)
        self._guard_write_visibility(unit_id, body_path, str(resolved["body"]))
        self._extract_content(record)
        if self._resolve_artifact_type(body_path, record=record, unit_id=unit_id) != "prd":
            raise RuntimeError("freeze-recovery-not-prd")
        body_edges = _ps().parse_edges_block(_ps().reassemble_body(record.body, record.comments)) or {}
        projected_links = body_edges.get("native") or []
        normalize_links = lambda links: sorted(json.dumps(link, sort_keys=True) for link in links)
        if normalize_links(projected_links) != normalize_links(record.native_links):
            raise RuntimeError("freeze-recovery-links-drift")
        self._check_recovery_review(record, unit_id, body_path)
        receipts = [c for c in record.comments if "sw-freeze-record" in c.markers or "sw-freeze-record" in c.body]
        if len(receipts) != 1:
            raise RuntimeError("freeze-recovery-receipt-missing-or-ambiguous")
        if len(re.findall(r"sw-freeze-hash:\s*([a-f0-9]{64})", receipts[0].body)) != 1:
            raise RuntimeError("freeze-recovery-receipt-missing-or-ambiguous")
        digest = _ps().parse_freeze_record_hash(receipts)
        snapshot = self._record_to_snapshot(record)
        if _ps().FROZEN_LABEL not in snapshot.labels:
            raise RuntimeError("freeze-recovery-frozen-label-lost")
        if (_ps().FREEZE_INCOMPLETE_LABEL in snapshot.labels) == complete:
            raise RuntimeError("freeze-recovery-incomplete-state-drift")
        snapshot.labels = [label for label in snapshot.labels if label != _ps().FREEZE_INCOMPLETE_LABEL]
        if not digest or _ps().canonical_hash(snapshot) != digest:
            raise RuntimeError("freeze-recovery-original-hash-drift")
        return digest

    def _resume_incomplete_freeze(self, unit_id: str, body_path: str, record: Any, *, distill: bool) -> dict[str, Any]:
        # Recovery never locks, edits the body, or creates/replaces a receipt.
        entry = deepcopy(self._client.issue_get(record.id))
        removed = False
        try:
            digest = self._check_recovery_record(entry, entry, unit_id, body_path)
            if not distill:
                raise RuntimeError("freeze-recovery-distillation-required")
            brainstorm = self._find_linked_brainstorm(unit_id, require_unique=True)
            distillation = self._distill_brainstorm_rationale(brainstorm, unit_id)
            absorb = self._ensure_absorb_linkage_at_freeze(unit_id, self._extract_content(entry))
            if absorb.get("verdict") == "fail":
                raise RuntimeError("absorb-linkage-failed")
            fresh = self._client.issue_get(entry.id)
            self._check_recovery_record(fresh, entry, unit_id, body_path)
            # Treat a transport failure during the write as possibly applied.
            removed = True
            self._client.issue_label(fresh.id, [l for l in fresh.labels if l != _ps().FREEZE_INCOMPLETE_LABEL], if_match=fresh.etag)
            final = self._client.issue_get(entry.id)
            self._check_recovery_record(final, entry, unit_id, body_path, complete=True)
        except (Exception, SystemExit) as exc:
            if removed:
                try:
                    fresh = self._client.issue_get(entry.id)
                    if _ps().FREEZE_INCOMPLETE_LABEL not in fresh.labels:
                        self._check_recovery_record(fresh, entry, unit_id, body_path, complete=True, require_native=False)
                        self._client.issue_label(fresh.id, sorted(set(fresh.labels) | {_ps().FREEZE_INCOMPLETE_LABEL}), if_match=fresh.etag)
                        restored = self._client.issue_get(entry.id)
                        self._check_recovery_record(restored, entry, unit_id, body_path, require_native=False)
                except (Exception, SystemExit) as restore_exc:
                    _ps().fail("freeze-recovery-partial-apply", code="freeze-recovery-partial-apply", partialApply=True,
                               reason=str(exc), restorationError=str(restore_exc), unitId=unit_id)
            _ps().fail("freeze-incomplete", code="freeze-incomplete", reason=str(exc), unitId=unit_id)
        resolved = self._resolve_canonical_body_for_op(unit_id, body_path, final)
        log_operation("freeze", unit_id, body_path, None, self.backend_id)
        return {"verdict": "ok", "unitId": unit_id, "bodyPath": body_path, "hash": digest,
                "locked": True, "labels": list(final.labels), "distillation": distillation,
                "absorbLinkage": absorb, "bodySource": resolved.get("bodySource"),
                "freezeAuthority": resolved.get("freezeAuthority"), "recovered": True}
