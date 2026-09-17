"""Bundle-asset helpers for the issues planning backend (PRD 342 R35)."""
from __future__ import annotations

from typing import Any

from planning_canonical import MARKER_UNIT_ID
import planning_paths as _pp

from ._common import log_operation
from .issues_helpers import (
    self_heal_issue_unit_index,
    record_unit_id,
    record_artifact_type,
)
from ..model import StoreResult


def _ps():
    import planning_store as ps

    return ps


class IssueStoreBundleAssetsMixin:
    """Co-located bundle assets stored as marked issue comments."""

    def self_heal_unit_index(self) -> dict[str, Any]:
        def _resolve(issue_id: str) -> Any | None:
            try:
                return self._client.issue_get(issue_id)
            except Exception:
                return None

        return self_heal_issue_unit_index(
            self.root,
            project_key=self.project_key,
            resolve_record=_resolve,
            record_unit_id=lambda rec: record_unit_id(rec, ps_mod=_ps(), unit_marker=MARKER_UNIT_ID),
            record_artifact_type=lambda rec: record_artifact_type(rec, ps_mod=_ps()),
        )


    def _bundle_asset_role(self, body_path: str) -> str | None:
        return _pp.bundle_role_for_body_path(body_path)

    def _bundle_asset_comment_body(self, role: str, content: str) -> str:
        marker = _pp.bundle_asset_marker(role)
        return f"<!-- {marker} -->\n{content}"

    def _find_bundle_asset_comment(self, record: Any, role: str) -> Any | None:
        marker = _pp.bundle_asset_marker(role)
        comments = list(getattr(record, "comments", None) or [])
        matches = [c for c in comments if marker in list(getattr(c, "markers", None) or [])]
        return matches[-1] if matches else None

    def _extract_bundle_asset_content(self, comment: Any, role: str) -> str:
        body = str(getattr(comment, "body", "") or "")
        marker = _pp.bundle_asset_marker(role)
        open_tag = f"<!-- {marker} -->"
        if body.startswith(open_tag):
            return body[len(open_tag):].lstrip("\n")
        # Tolerate marker-only payloads when body is raw content.
        return body

    def _put_bundle_asset(
        self, unit_id: str, body_path: str, content: str, role: str
    ) -> StoreResult:
        """Persist a co-located bundle asset as a marked comment (PRD 342 R35)."""
        try:
            record = self._lookup_record(unit_id, body_path)
        except _ps().IssueNotFound:
            _ps().fail(
                "bundle-asset-requires-canonical-body",
                code="bundle-asset-requires-canonical-body",
                unitId=unit_id,
                bodyPath=body_path,
                role=role,
            )
        self._guard_write_secrets(content, path_hint=body_path)
        marker = _pp.bundle_asset_marker(role)
        comment_body = self._bundle_asset_comment_body(role, content)
        self._adapter_issue_comment(record.id, comment_body, markers=[marker])
        digest = _ps().content_hash(content) if hasattr(_ps(), "content_hash") else _ps().canonical_hash({"body": content})
        log_operation("put", unit_id, body_path, content, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=content, hash=digest)

    def _get_bundle_asset(self, unit_id: str, body_path: str, role: str) -> StoreResult:
        try:
            record = self._lookup_record(unit_id, body_path)
        except _ps().IssueNotFound:
            return StoreResult("missing", unit_id, body_path, self.backend_id, reason="not-found")
        except _ps().IssueCapabilityError as exc:
            _ps().fail(str(exc), code="issues-capability")
        except (_ps().IssueTombstone, _ps().IssueTransferred, _ps().IssueBudgetExhausted) as exc:
            _ps().handle_issue_client_error(exc)
        # Refresh after freeze so asset comments remain visible.
        try:
            record = self._client.issue_get(record.id)
        except Exception:
            pass
        comment = self._find_bundle_asset_comment(record, role)
        if comment is None:
            return StoreResult("missing", unit_id, body_path, self.backend_id, reason="bundle-asset-missing")
        content = self._extract_bundle_asset_content(comment, role)
        digest = _ps().content_hash(content) if hasattr(_ps(), "content_hash") else _ps().canonical_hash({"body": content})
        log_operation("get", unit_id, body_path, content, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=content, hash=digest)


