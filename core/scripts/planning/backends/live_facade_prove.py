"""Live facade issue-store prove helper (PRD 363 R10).

Extracted from ``issues.py`` to keep the authored package module under the
module-size lint cap.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _ps():
    import planning_store as ps

    return ps


def run_live_facade_issue_store_prove(
    backend: Any,
    *,
    unit_id: str,
    body_path: str,
    operator_content: str,
    updated_operator_content: str,
    materialize_dest: Path,
) -> dict[str, Any]:
    """Live pilot put/get/materialize/update(+retry) via IssueStoreBackend.

    Exercises reconstruct-before-ok on chunked puts without mutating unrelated
    stuck issues (e.g. TIE-8 put-incomplete) elsewhere in Linear.
    """
    ops: list[str] = []
    first = backend.put(unit_id, body_path, operator_content)
    if first.verdict != "ok":
        _ps().fail(
            "live-prove-put",
            code="live-prove-put",
            reason=first.reason or first.verdict,
            unitId=unit_id,
        )
    ops.append("put")
    record = backend._lookup_record(unit_id, body_path)
    if _ps().PUT_INCOMPLETE_LABEL in record.labels:
        _ps().fail(
            "live-prove-put-incomplete",
            code="reconstruct-before-ok",
            unitId=unit_id,
            issueId=record.id,
        )
    got = backend.get(unit_id, body_path)
    if got.verdict != "ok" or got.content is None:
        _ps().fail("live-prove-get", code="live-prove-get", unitId=unit_id)
    ops.append("get")
    mat = backend.materialize(unit_id, body_path, materialize_dest)
    if mat.verdict != "ok":
        _ps().fail("live-prove-materialize", code="live-prove-materialize", unitId=unit_id)
    ops.append("materialize")
    retry = backend.put(unit_id, body_path, operator_content)
    if retry.verdict != "ok":
        _ps().fail("live-prove-retry", code="live-prove-retry", unitId=unit_id)
    ops.append("retry-put")
    updated = backend.put(unit_id, body_path, updated_operator_content)
    if updated.verdict != "ok":
        _ps().fail("live-prove-update", code="live-prove-update", unitId=unit_id)
    ops.append("update")
    final = backend.get(unit_id, body_path)
    if final.verdict != "ok" or final.content is None:
        _ps().fail("live-prove-get-final", code="live-prove-get", unitId=unit_id)
    ops.append("get")
    final_record = backend._lookup_record(unit_id, body_path)
    chunk_count = len(
        [c for c in (final_record.comments or []) if "sw-chunk-overflow" in str(c.body or "")]
    )
    return {
        "ops": ops,
        "issueId": final_record.id,
        "chunkCount": chunk_count,
        "descriptionBytes": len(str(final_record.body or "").encode("utf-8")),
        "commentBytesMax": max(
            (len(str(c.body or "").encode("utf-8")) for c in (final_record.comments or [])),
            default=0,
        ),
    }
