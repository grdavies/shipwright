#!/usr/bin/env python3
"""Issue-store doc-review comment transport bootstrap (PRD 341 slice)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from issues_broker import IssueCommentAuthorshipMismatch
from issues_lib import IssueRevisionConflict, IssuesClient
from planning_canonical import (
    DOC_REVIEW_MARKER,
    MARKER_UNIT_ID,
    CommentRecord,
    parse_body_marker,
    verify_unit_id,
)

DOC_REVIEW_TRANSPORT_UNAVAILABLE = "doc-review-transport-unavailable"
DOC_REVIEW_COMMENT_DRIFT = "doc-review-comment-drift"
DOC_REVIEW_PIN_CONFLICT = "doc-review-pin-conflict"
DOC_REVIEW_ROUND_MALFORMED = "doc-review-round-malformed"
BODY_SHA256_V1_PREFIX = "body-sha256/v1:"
DOC_REVIEW_AUTHORSHIP_REJECTED = "doc-review-authorship-rejected"
DOC_REVIEW_PAYLOAD_TOO_LARGE = "doc-review-payload-too-large"
DOC_REVIEW_FINDINGS_SCHEMA_INVALID = "doc-review-findings-schema-invalid"
DOC_REVIEW_IDEMPOTENCY_AMBIGUOUS = "doc-review-idempotency-ambiguous"
DOC_REVIEW_PAGINATION_INCOMPLETE = "doc-review-pagination-incomplete"

# GitHub issue comment body hard cap (characters). Provider-neutral facade uses this as the
# default size bound for findings comments (PRD 341 R39).
DOC_REVIEW_COMMENT_SIZE_CAP = 65536

_FINDINGS_SCHEMA_REL = Path("core/skills/doc-review/references/findings-schema.json")
_FINDINGS_SEVERITIES = frozenset({"P0", "P1", "P2", "P3"})
_FINDINGS_AUTOFIX = frozenset({"safe_auto", "gated_auto", "manual"})
_FINDINGS_TYPES = frozenset({"error", "omission"})
_FINDINGS_CONFIDENCE = frozenset({0, 25, 50, 75, 100})

# Colon (`sw:doc-review`) and hyphen/HTML (`sw-doc-review`) are one marker family (PRD 341 R4).
_DOC_REVIEW_NAME = r"sw[:-]doc-review"
_DOC_REVIEW_ROUND_NAME = r"sw[:-]doc-review-round"

DOC_REVIEW_OPEN_MARKER = re.compile(
    rf"<!--\s*{_DOC_REVIEW_NAME}\s*-->",
    re.IGNORECASE,
)
DOC_REVIEW_CLOSE_MARKER = re.compile(
    rf"<!--\s*/{_DOC_REVIEW_NAME}\s*-->",
    re.IGNORECASE,
)
DOC_REVIEW_JSON_FENCE = re.compile(
    rf"<!--\s*{_DOC_REVIEW_NAME}\s*-->\s*```(?:json|sw-doc-review)?\s*\n(.*?)\n```\s*<!--\s*/{_DOC_REVIEW_NAME}\s*-->",
    re.DOTALL | re.IGNORECASE,
)
DOC_REVIEW_ROUND_OPEN_MARKER = re.compile(
    rf"<!--\s*{_DOC_REVIEW_ROUND_NAME}\s*-->",
    re.IGNORECASE,
)
DOC_REVIEW_ROUND_CLOSE_MARKER = re.compile(
    rf"<!--\s*/{_DOC_REVIEW_ROUND_NAME}\s*-->",
    re.IGNORECASE,
)
DOC_REVIEW_ROUND_JSON_FENCE = re.compile(
    rf"<!--\s*{_DOC_REVIEW_ROUND_NAME}\s*-->\s*```(?:json|sw-doc-review)?\s*\n(.*?)\n```\s*<!--\s*/{_DOC_REVIEW_ROUND_NAME}\s*-->",
    re.DOTALL | re.IGNORECASE,
)
LEGACY_INLINE_ROUND_MARKER = re.compile(
    rf"<!--\s*{_DOC_REVIEW_ROUND_NAME}:\s*\{{",
    re.IGNORECASE,
)
# Bare prose fences without HTML wrappers are never typed doc-review (R4/R42).
RAW_DOC_REVIEW_PROSE_FENCE = re.compile(
    r"```(?:sw-doc-review|sw:doc-review)\b",
    re.IGNORECASE,
)

TXN_VERBS = frozenset(
    {
        "doc-review-round-open",
        "doc-review-round-post",
        "doc-review-round-read",
        "doc-review-round-verify",
        "doc-review-round-close",
    }
)


@dataclass(frozen=True)
class DocReviewPin:
    comment_id: str
    revision: str
    author_id: str
    persona: str
    idempotency_key: str
    payload_hash: str
    body_digest: str
    body_snapshot: str = ""

    def as_dict(self, *, include_snapshot: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {
            "commentId": self.comment_id,
            "revision": self.revision,
            "authorId": self.author_id,
            "persona": self.persona,
            "idempotencyKey": self.idempotency_key,
            "payloadHash": self.payload_hash,
            "bodyDigest": self.body_digest,
        }
        if include_snapshot and self.body_snapshot:
            out["bodySnapshot"] = self.body_snapshot
        return out


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def idempotency_key(round_id: str, persona: str) -> str:
    return f"{round_id}:{persona}"


def payload_hash(payload: dict[str, Any]) -> str:
    material = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def normalize_comment_body_for_digest(body: str) -> str:
    """Normalize comment body bytes for revision digests (PRD 341 R17/R18).

    UTF-8 text with CRLF and bare CR converted to LF. No Unicode NFC and no trim.
    """
    return (body or "").replace("\r\n", "\n").replace("\r", "\n")


def body_digest(body: str) -> str:
    material = normalize_comment_body_for_digest(body).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def body_sha256_v1(body: str) -> str:
    """GitHub v1 revision token — never ``updated_at`` (PRD 341 R17/R18, D5)."""
    return f"{BODY_SHA256_V1_PREFIX}{body_digest(body)}"


def comment_revision_token(comment: CommentRecord) -> str:
    """Authoritative revision for doc-review pins."""
    return body_sha256_v1(comment.body or "")


def build_doc_review_comment_body(*, round_id: str, persona: str, payload: dict[str, Any]) -> str:
    envelope = {
        "round": round_id,
        "persona": persona,
        "idempotencyKey": idempotency_key(round_id, persona),
        "payloadHash": payload_hash(payload),
        "payload": payload,
    }
    raw = json.dumps(envelope, indent=2, sort_keys=True, ensure_ascii=False)
    return (
        f"<!-- {DOC_REVIEW_MARKER} -->\n"
        f"```json\n{raw}\n```\n"
        f"<!-- /{DOC_REVIEW_MARKER} -->\n"
    )


def parse_doc_review_comment(body: str) -> dict[str, Any] | None:
    match = DOC_REVIEW_JSON_FENCE.search(body or "")
    if not match:
        return None
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def validate_doc_review_envelope(envelope: dict[str, Any]) -> str | None:
    """Return a stable malformed detail when envelope fields disagree."""
    round_id = str(envelope.get("round") or "").strip()
    persona = str(envelope.get("persona") or "").strip()
    key = str(envelope.get("idempotencyKey") or "").strip()
    digest = str(envelope.get("payloadHash") or "").strip()
    payload = envelope.get("payload")
    if not round_id:
        return "missing-round"
    if not persona:
        return "missing-persona"
    if not key:
        return "missing-idempotency-key"
    if not digest:
        return "missing-payload-hash"
    if not isinstance(payload, dict):
        return "missing-payload"
    expected_key = idempotency_key(round_id, persona)
    if key != expected_key:
        return "idempotency-key-mismatch"
    expected_digest = payload_hash(payload)
    if digest != expected_digest:
        return "payload-hash-mismatch"
    return None


def envelope_error_for_comment(comment: CommentRecord) -> str | None:
    parsed = parse_doc_review_comment(comment.body)
    if parsed is None:
        return "envelope-unparseable"
    return validate_doc_review_envelope(parsed)


def is_marked_doc_review_comment(comment: CommentRecord) -> bool:
    markers = {str(m).strip().lower() for m in (comment.markers or [])}
    if DOC_REVIEW_MARKER.lower() in markers or "sw:doc-review" in markers:
        return True
    body = comment.body or ""
    return bool(DOC_REVIEW_OPEN_MARKER.search(body) and DOC_REVIEW_CLOSE_MARKER.search(body))


def comment_round_id(comment: CommentRecord) -> str | None:
    parsed = parse_doc_review_comment(comment.body)
    if not parsed:
        return None
    if validate_doc_review_envelope(parsed) is not None:
        return None
    round_id = str(parsed.get("round") or "").strip()
    return round_id or None


def collect_round_doc_review_comments(comments: list[CommentRecord], round_id: str) -> list[CommentRecord]:
    scoped: list[CommentRecord] = []
    for comment in comments:
        if not is_marked_doc_review_comment(comment):
            continue
        if envelope_error_for_comment(comment) is not None:
            continue
        if comment_round_id(comment) != round_id:
            continue
        scoped.append(comment)
    scoped.sort(key=lambda comment: (comment.created_at, comment.id))
    return scoped


def collect_malformed_doc_review_comments(comments: list[CommentRecord]) -> list[CommentRecord]:
    malformed: list[CommentRecord] = []
    for comment in comments:
        if not is_marked_doc_review_comment(comment):
            continue
        if envelope_error_for_comment(comment) is not None:
            malformed.append(comment)
    return malformed


def find_comments_by_idempotency_key(
    comments: list[CommentRecord],
    *,
    round_id: str,
    key: str,
) -> list[CommentRecord]:
    """Return every valid round comment carrying ``key`` (PRD 341 R8)."""
    matches: list[CommentRecord] = []
    for comment in collect_round_doc_review_comments(comments, round_id):
        parsed = parse_doc_review_comment(comment.body)
        if not parsed:
            continue
        if validate_doc_review_envelope(parsed) is not None:
            continue
        if str(parsed.get("idempotencyKey") or "") == key:
            matches.append(comment)
    return matches


def find_comment_by_idempotency_key(
    comments: list[CommentRecord],
    *,
    round_id: str,
    key: str,
) -> CommentRecord | None:
    """Return the sole matching comment, or None when zero matches.

    Callers that must fail closed on duplicates should use
    :func:`find_comments_by_idempotency_key` (PRD 341 R8).
    """
    matches = find_comments_by_idempotency_key(comments, round_id=round_id, key=key)
    if len(matches) != 1:
        return None
    return matches[0]


def comments_pagination_complete(record: Any) -> bool:
    """Fail closed when the provider cannot prove terminal pagination (R8/R13)."""
    flag = getattr(record, "comments_complete", None)
    if flag is None:
        # Fixture / fully-materialized IssueRecord comments are terminal.
        return True
    return bool(flag)


def validate_findings_payload(payload: dict[str, Any], *, persona: str) -> str | None:
    """Validate persona findings against findings-schema.json (PRD 341 R5/R6).

    Lightweight structural checks mirror the JSON Schema without requiring jsonschema.
    """
    if not isinstance(payload, dict):
        return "payload-not-object"
    required = ("reviewer", "findings", "residual_risks", "deferred_questions")
    for field in required:
        if field not in payload:
            return f"missing-{field}"
    reviewer = payload.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        return "invalid-reviewer"
    if reviewer.strip() != persona:
        return "reviewer-persona-mismatch"
    findings = payload.get("findings")
    if not isinstance(findings, list):
        return "findings-not-array"
    residual = payload.get("residual_risks")
    deferred = payload.get("deferred_questions")
    if not isinstance(residual, list) or not isinstance(deferred, list):
        return "risks-or-questions-not-array"
    for item in residual:
        if not isinstance(item, str):
            return "residual-risk-not-string"
    for item in deferred:
        if not isinstance(item, str):
            return "deferred-question-not-string"
    required_finding = (
        "title",
        "severity",
        "section",
        "why_it_matters",
        "finding_type",
        "autofix_class",
        "confidence",
        "evidence",
    )
    for idx, finding in enumerate(findings):
        if not isinstance(finding, dict):
            return f"finding-{idx}-not-object"
        for field in required_finding:
            if field not in finding:
                return f"finding-{idx}-missing-{field}"
        title = finding.get("title")
        if not isinstance(title, str) or not title or len(title) > 100:
            return f"finding-{idx}-invalid-title"
        if finding.get("severity") not in _FINDINGS_SEVERITIES:
            return f"finding-{idx}-invalid-severity"
        if not isinstance(finding.get("section"), str):
            return f"finding-{idx}-invalid-section"
        if not isinstance(finding.get("why_it_matters"), str):
            return f"finding-{idx}-invalid-why"
        if finding.get("finding_type") not in _FINDINGS_TYPES:
            return f"finding-{idx}-invalid-type"
        if finding.get("autofix_class") not in _FINDINGS_AUTOFIX:
            return f"finding-{idx}-invalid-autofix"
        suggested = finding.get("suggested_fix", None)
        if suggested is not None and not isinstance(suggested, str):
            return f"finding-{idx}-invalid-suggested-fix"
        if finding.get("confidence") not in _FINDINGS_CONFIDENCE:
            return f"finding-{idx}-invalid-confidence"
        evidence = finding.get("evidence")
        if not isinstance(evidence, list) or not evidence or not all(isinstance(e, str) for e in evidence):
            return f"finding-{idx}-invalid-evidence"
    # Keep schema path discoverable for docs-currency / future jsonschema wiring.
    _ = _FINDINGS_SCHEMA_REL
    return None


def envelope_immutable_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Semantic equality for idempotent replay (PRD 341 R38).

    JSON key order and presentation whitespace do not create a conflict; payload
    comparison uses sorted-key hashing already applied by :func:`payload_hash`.
    """
    for field in ("round", "persona", "idempotencyKey", "payloadHash"):
        if str(left.get(field) or "") != str(right.get(field) or ""):
            return False
    left_payload = left.get("payload")
    right_payload = right.get("payload")
    if not isinstance(left_payload, dict) or not isinstance(right_payload, dict):
        return False
    return payload_hash(left_payload) == payload_hash(right_payload)


def render_review_round_block(block: dict[str, Any]) -> str:
    payload = json.dumps(block, sort_keys=True, indent=2, ensure_ascii=False)
    return (
        "<!-- sw-doc-review-round -->\n"
        f"```json\n{payload}\n```\n"
        "<!-- /sw-doc-review-round -->\n"
    )


def inspect_review_round_block(body: str) -> tuple[dict[str, Any], str | None]:
    text = body or ""
    if LEGACY_INLINE_ROUND_MARKER.search(text):
        return {}, "legacy-inline-round-block"
    matches = list(DOC_REVIEW_ROUND_JSON_FENCE.finditer(text))
    # Strip typed HTML-wrapped fences before scanning for raw prose fences.
    remainder = DOC_REVIEW_ROUND_JSON_FENCE.sub("", text)
    remainder = DOC_REVIEW_JSON_FENCE.sub("", remainder)
    if RAW_DOC_REVIEW_PROSE_FENCE.search(remainder):
        return {}, "raw-prose-fence"
    open_count = len(DOC_REVIEW_ROUND_OPEN_MARKER.findall(text))
    close_count = len(DOC_REVIEW_ROUND_CLOSE_MARKER.findall(text))
    if len(matches) > 1 or open_count > 1 or close_count > 1:
        return {}, "duplicate-round-block"
    if open_count != close_count:
        return {}, "unbalanced-round-block"
    if not matches:
        return {}, None
    try:
        parsed = json.loads(matches[0].group(1))
    except json.JSONDecodeError:
        return {}, "malformed-round-block"
    if not isinstance(parsed, dict):
        return {}, "malformed-round-block"
    return parsed, None


def parse_review_round_block(body: str) -> dict[str, Any]:
    manifest, _err = inspect_review_round_block(body)
    return manifest


def strip_review_round_blocks(body: str) -> str:
    text = DOC_REVIEW_ROUND_JSON_FENCE.sub("", body or "")
    text = re.sub(
        rf"<!--\s*{_DOC_REVIEW_ROUND_NAME}:.*?-->",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    text = DOC_REVIEW_ROUND_OPEN_MARKER.sub("", text)
    text = DOC_REVIEW_ROUND_CLOSE_MARKER.sub("", text)
    return text.strip()


def upsert_review_round_block(body: str, block: dict[str, Any]) -> str:
    stripped = strip_review_round_blocks(body)
    marker = render_review_round_block(block)
    return f"{stripped}\n\n{marker}" if stripped else marker


def pin_from_comment(comment: CommentRecord) -> DocReviewPin | None:
    parsed = parse_doc_review_comment(comment.body)
    if not parsed:
        return None
    if validate_doc_review_envelope(parsed) is not None:
        return None
    round_id = str(parsed.get("round") or "")
    persona = str(parsed.get("persona") or "")
    payload = parsed.get("payload")
    if not isinstance(payload, dict):
        return None
    return DocReviewPin(
        comment_id=str(comment.id),
        revision=comment_revision_token(comment),
        author_id=str(comment.author_id or ""),
        persona=persona,
        idempotency_key=str(parsed.get("idempotencyKey") or idempotency_key(round_id, persona)),
        payload_hash=str(parsed.get("payloadHash") or payload_hash(payload)),
        body_digest=body_digest(comment.body),
        body_snapshot=comment.body,
    )


def pin_index(pins: list[Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_comment: dict[str, dict[str, Any]] = {}
    by_key: dict[str, dict[str, Any]] = {}
    for row in pins:
        if not isinstance(row, dict):
            continue
        comment_id = str(row.get("commentId") or "")
        key = str(row.get("idempotencyKey") or "")
        if comment_id:
            by_comment[comment_id] = row
        if key:
            by_key[key] = row
    return by_comment, by_key


def merge_pin_into_manifest(
    pins: list[Any],
    pin: DocReviewPin,
) -> tuple[list[dict[str, Any]], bool, dict[str, Any] | None]:
    """Add *pin* to manifest rows; reconcile when comment exists but pin row is absent."""
    normalized: list[dict[str, Any]] = [row for row in pins if isinstance(row, dict)]
    by_comment, by_key = pin_index(normalized)

    existing_for_key = by_key.get(pin.idempotency_key)
    if existing_for_key is not None:
        if str(existing_for_key.get("commentId") or "") != pin.comment_id:
            return normalized, False, {
                "verdict": "fail",
                "error": DOC_REVIEW_PIN_CONFLICT,
                "detail": "idempotency-key-comment-mismatch",
                "idempotencyKey": pin.idempotency_key,
            }
        return normalized, False, None

    existing_for_comment = by_comment.get(pin.comment_id)
    if existing_for_comment is not None:
        if str(existing_for_comment.get("idempotencyKey") or "") != pin.idempotency_key:
            return normalized, False, {
                "verdict": "fail",
                "error": DOC_REVIEW_PIN_CONFLICT,
                "detail": "comment-id-key-mismatch",
                "commentId": pin.comment_id,
            }
        return normalized, False, None

    updated = [*normalized, pin.as_dict()]
    return updated, True, None


def transport_unavailable(*, reason: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {
        "verdict": "fail",
        "error": DOC_REVIEW_TRANSPORT_UNAVAILABLE,
        "capability": "github-issue-store",
    }
    if reason:
        out["reason"] = reason
    return out


def drift_failure(*, kind: str, detail: str = "", **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "verdict": "fail",
        "error": DOC_REVIEW_COMMENT_DRIFT,
        "driftKind": kind,
    }
    if detail:
        out["detail"] = detail
    out.update(extra)
    return out


def require_github_issue_store(*, effective: dict[str, Any], provider: str) -> dict[str, Any] | None:
    if effective.get("configured") != "issue-store":
        return transport_unavailable(reason="issue-store-required")
    if provider != "github-issues":
        return transport_unavailable(reason=f"unsupported-issues-provider:{provider}")
    return None


def verify_issue_unit(body: str, *, unit_id: str, issue_id: str) -> dict[str, Any] | None:
    marker_unit = parse_body_marker(body, MARKER_UNIT_ID)
    if marker_unit and marker_unit != unit_id:
        return drift_failure(
            kind="issue-unit-mismatch",
            issueId=issue_id,
            expectedUnitId=unit_id,
            actualUnitId=marker_unit,
        )
    if marker_unit:
        return None
    if not verify_unit_id(body, unit_id):
        return drift_failure(
            kind="issue-unit-mismatch",
            issueId=issue_id,
            expectedUnitId=unit_id,
        )
    return None


def verify_manifest_binding(
    manifest: dict[str, Any],
    *,
    unit_id: str,
    issue_id: str,
) -> dict[str, Any] | None:
    if not manifest:
        return None
    manifest_unit = str(manifest.get("unitId") or "")
    manifest_issue = str(manifest.get("issueId") or "")
    if manifest_unit and manifest_unit != unit_id:
        return drift_failure(
            kind="issue-unit-mismatch",
            detail="manifest-unit-mismatch",
            expectedUnitId=unit_id,
            actualUnitId=manifest_unit,
            issueId=issue_id,
        )
    if manifest_issue and manifest_issue != str(issue_id):
        return drift_failure(
            kind="issue-id-mismatch",
            detail="manifest-issue-mismatch",
            expectedIssueId=str(issue_id),
            actualIssueId=manifest_issue,
        )
    return None


def verify_round_integrity(
    *,
    manifest: dict[str, Any],
    comments: list[CommentRecord],
    expected_author_id: str,
) -> dict[str, Any] | None:
    pins_raw = manifest.get("pins")
    if not isinstance(pins_raw, list):
        return drift_failure(kind="malformed", detail="manifest-missing-pins")

    round_id = str(manifest.get("roundId") or "")
    if not round_id:
        return drift_failure(kind="malformed", detail="manifest-missing-round-id")

    for comment in collect_malformed_doc_review_comments(comments):
        parsed = parse_doc_review_comment(comment.body)
        comment_round = str(parsed.get("round") or "").strip() if parsed else ""
        if not comment_round or comment_round == round_id:
            return drift_failure(
                kind="malformed",
                commentId=comment.id,
                detail=envelope_error_for_comment(comment) or "envelope-unparseable",
            )

    by_id = {str(comment.id): comment for comment in comments}
    marked = collect_round_doc_review_comments(comments, round_id)
    marked_ids = {comment.id for comment in marked}
    pinned_ids = {str(row.get("commentId") or "") for row in pins_raw if isinstance(row, dict)}

    seen_keys: set[str] = set()
    seen_comments: set[str] = set()
    for row in pins_raw:
        if not isinstance(row, dict):
            return drift_failure(kind="malformed", detail="invalid-pin-row")
        comment_id = str(row.get("commentId") or "")
        key = str(row.get("idempotencyKey") or "")
        if key:
            if key in seen_keys:
                return drift_failure(kind="malformed", detail="duplicate-idempotency-key", idempotencyKey=key)
            seen_keys.add(key)
        if comment_id:
            if comment_id in seen_comments:
                return drift_failure(kind="malformed", detail="duplicate-comment-id", commentId=comment_id)
            seen_comments.add(comment_id)

        comment = by_id.get(comment_id)
        if comment is None:
            return drift_failure(kind="delete", commentId=comment_id)
        if not is_marked_doc_review_comment(comment):
            return drift_failure(kind="malformed", commentId=comment_id)
        if comment_round_id(comment) != round_id:
            return drift_failure(kind="malformed", commentId=comment_id, detail="round-mismatch")
        parsed = parse_doc_review_comment(comment.body)
        if parsed is None:
            return drift_failure(kind="malformed", commentId=comment_id)
        envelope_err = validate_doc_review_envelope(parsed)
        if envelope_err is not None:
            return drift_failure(kind="malformed", commentId=comment_id, detail=envelope_err)
        expected_revision = str(row.get("revision") or "")
        actual_revision = comment_revision_token(comment)
        if expected_revision and actual_revision != expected_revision:
            # updated_at / provider revision metadata is never authoritative for new pins.
            return drift_failure(kind="edit", commentId=comment_id, detail="revision-token-mismatch")
        expected_digest = str(row.get("bodyDigest") or "")
        if expected_digest and body_digest(comment.body) != expected_digest:
            return drift_failure(kind="edit", commentId=comment_id)
        snapshot = str(row.get("bodySnapshot") or "")
        if snapshot and comment.body != snapshot:
            return drift_failure(kind="edit", commentId=comment_id)
        expected_author = str(row.get("authorId") or expected_author_id)
        actual_author = str(comment.author_id or "")
        if expected_author and actual_author != expected_author:
            return drift_failure(kind="author-mismatch", commentId=comment_id)
        if expected_author_id and actual_author != expected_author_id:
            return drift_failure(kind="author-mismatch", commentId=comment_id)

    extra_ids = marked_ids - pinned_ids
    if extra_ids:
        return drift_failure(kind="added", commentIds=sorted(extra_ids))

    missing_ids = pinned_ids - marked_ids
    if missing_ids:
        return drift_failure(kind="delete", commentIds=sorted(missing_ids))

    return None


def manifest_response(manifest: dict[str, Any], *, comments: list[CommentRecord] | None = None) -> dict[str, Any]:
    pins = manifest.get("pins")
    if not isinstance(pins, list):
        pins = []
    by_id = {str(comment.id): comment for comment in comments or []}
    enriched: list[dict[str, Any]] = []
    for row in pins:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        comment_id = str(item.get("commentId") or "")
        comment = by_id.get(comment_id)
        if comment is not None:
            item["bodySnapshot"] = comment.body
        enriched.append(item)
    return {
        "roundId": manifest.get("roundId"),
        "status": manifest.get("status"),
        "unitId": manifest.get("unitId"),
        "issueId": manifest.get("issueId"),
        "openedAt": manifest.get("openedAt"),
        "closedAt": manifest.get("closedAt"),
        "pins": enriched or pins,
    }


def revision_conflict_result(*, action: str, issue_id: str, exc: IssueRevisionConflict) -> dict[str, Any]:
    return {
        "verdict": "fail",
        "action": action,
        "issueId": issue_id,
        "error": "revision-conflict",
        "detail": {"expected": exc.expected, "actual": exc.actual},
    }


def manifest_malformed_result(*, action: str, issue_id: str, detail: str) -> dict[str, Any]:
    return {
        "verdict": "fail",
        "action": action,
        "issueId": issue_id,
        "error": DOC_REVIEW_ROUND_MALFORMED,
        "detail": detail,
    }


def apply_manifest_update(
    client: IssuesClient,
    *,
    issue_id: str,
    verb: str,
    record_body: str,
    etag: str,
    manifest_block: dict[str, Any],
) -> dict[str, Any] | None:
    body = upsert_review_round_block(record_body, manifest_block)
    try:
        client.issue_update(str(issue_id), body=body, if_match=etag)
        return None
    except IssueRevisionConflict as exc:
        return revision_conflict_result(action=verb, issue_id=str(issue_id), exc=exc)


def execute_doc_review_txn(
    client: IssuesClient,
    *,
    verb: str,
    issue_id: str,
    unit_id: str,
    round_id: str,
    persona: str | None = None,
    payload: dict[str, Any] | None = None,
    dry_run: bool = False,
    author_id: str,
) -> dict[str, Any]:
    """Issue-store doc-review transport verbs (GitHub bootstrap). Fail-closed on drift and revision conflict."""
    try:
        record = client.issue_get(str(issue_id))
    except Exception as exc:  # noqa: BLE001
        return {"verdict": "fail", "action": verb, "error": str(exc), "issueId": issue_id}

    unit_err = verify_issue_unit(record.body, unit_id=unit_id, issue_id=str(issue_id))
    if unit_err is not None:
        unit_err["action"] = verb
        return unit_err

    manifest, manifest_err = inspect_review_round_block(record.body)
    if manifest_err:
        return manifest_malformed_result(action=verb, issue_id=str(issue_id), detail=manifest_err)

    def _binding_failure(active_manifest: dict[str, Any]) -> dict[str, Any] | None:
        bind_err = verify_manifest_binding(
            active_manifest,
            unit_id=unit_id,
            issue_id=str(issue_id),
        )
        if bind_err is None:
            return None
        bind_err["action"] = verb
        return bind_err

    def _binding_for_round(active_manifest: dict[str, Any]) -> dict[str, Any] | None:
        if active_manifest.get("roundId") != round_id:
            return None
        return _binding_failure(active_manifest)

    if manifest.get("roundId") == round_id:
        bind_err = _binding_failure(manifest)
        if bind_err is not None:
            return bind_err

    if verb == "doc-review-round-open":
        if manifest.get("status") == "open" and manifest.get("roundId") == round_id:
            out = manifest_response(manifest, comments=list(record.comments))
            out.update({"verdict": "ok", "action": verb, "issueId": issue_id})
            return out
        if manifest.get("status") == "open" and manifest.get("roundId") != round_id:
            return {
                "verdict": "fail",
                "action": verb,
                "error": "doc-review-round-already-open",
                "openRoundId": manifest.get("roundId"),
            }
        opened = {
            "roundId": round_id,
            "status": "open",
            "unitId": unit_id,
            "issueId": str(issue_id),
            "openedAt": utc_now(),
            "pins": [],
        }
        if dry_run:
            return {"verdict": "ok", "action": verb, "dryRun": True, **manifest_response(opened)}
        conflict = apply_manifest_update(
            client,
            issue_id=str(issue_id),
            verb=verb,
            record_body=record.body,
            etag=record.etag,
            manifest_block=opened,
        )
        if conflict is not None:
            return conflict
        out = manifest_response(opened)
        out.update({"verdict": "ok", "action": verb, "issueId": issue_id, "status": "open"})
        return out

    if verb == "doc-review-round-close":
        refreshed = client.issue_get(str(issue_id))
        manifest, manifest_err = inspect_review_round_block(refreshed.body)
        if manifest_err:
            return manifest_malformed_result(action=verb, issue_id=str(issue_id), detail=manifest_err)
        bind_err = _binding_for_round(manifest)
        if bind_err is not None:
            return bind_err
        if manifest.get("roundId") == round_id and manifest.get("status") == "closed":
            drift = verify_round_integrity(
                manifest=manifest,
                comments=list(refreshed.comments),
                expected_author_id=author_id,
            )
            if drift is not None:
                drift["action"] = verb
                drift["issueId"] = issue_id
                return drift
            return {
                "verdict": "ok",
                "action": verb,
                "issueId": issue_id,
                "roundId": round_id,
                "status": "closed",
                "idempotent": True,
            }
        if manifest.get("roundId") != round_id or manifest.get("status") != "open":
            return {
                "verdict": "fail",
                "action": verb,
                "error": "doc-review-round-not-open",
                "roundId": round_id,
            }
        drift = verify_round_integrity(
            manifest=manifest,
            comments=list(refreshed.comments),
            expected_author_id=author_id,
        )
        if drift is not None:
            drift["action"] = verb
            drift["issueId"] = issue_id
            return drift
        if dry_run:
            return {"verdict": "ok", "action": verb, "dryRun": True, "status": "closed", "roundId": round_id}
        closed = dict(manifest)
        closed["status"] = "closed"
        closed["closedAt"] = utc_now()
        conflict = apply_manifest_update(
            client,
            issue_id=str(issue_id),
            verb=verb,
            record_body=refreshed.body,
            etag=refreshed.etag,
            manifest_block=closed,
        )
        if conflict is not None:
            return conflict
        return {"verdict": "ok", "action": verb, "issueId": issue_id, "roundId": round_id, "status": "closed"}

    if manifest.get("roundId") != round_id or manifest.get("status") != "open":
        return {
            "verdict": "fail",
            "action": verb,
            "error": "doc-review-round-not-open",
            "roundId": round_id,
        }

    if verb == "doc-review-round-read":
        refreshed = client.issue_get(str(issue_id))
        manifest, manifest_err = inspect_review_round_block(refreshed.body)
        if manifest_err:
            return manifest_malformed_result(action=verb, issue_id=str(issue_id), detail=manifest_err)
        bind_err = _binding_for_round(manifest)
        if bind_err is not None:
            return bind_err
        out = manifest_response(manifest, comments=list(refreshed.comments))
        out.update({"verdict": "ok", "action": verb, "issueId": issue_id})
        return out

    if verb == "doc-review-round-verify":
        refreshed = client.issue_get(str(issue_id))
        manifest, manifest_err = inspect_review_round_block(refreshed.body)
        if manifest_err:
            return manifest_malformed_result(action=verb, issue_id=str(issue_id), detail=manifest_err)
        bind_err = _binding_for_round(manifest)
        if bind_err is not None:
            return bind_err
        drift = verify_round_integrity(
            manifest=manifest,
            comments=list(refreshed.comments),
            expected_author_id=author_id,
        )
        if drift is not None:
            drift["action"] = verb
            drift["issueId"] = issue_id
            return drift
        return {"verdict": "ok", "action": verb, "issueId": issue_id, "roundId": round_id}

    if verb != "doc-review-round-post":
        return {"verdict": "fail", "action": verb, "error": "unknown-doc-review-verb", "verb": verb}

    if not persona:
        return {"verdict": "fail", "action": verb, "error": "persona-required"}
    if not isinstance(payload, dict):
        return {"verdict": "fail", "action": verb, "error": "payload-required"}

    schema_err = validate_findings_payload(payload, persona=persona)
    if schema_err is not None:
        return {
            "verdict": "fail",
            "action": verb,
            "error": DOC_REVIEW_FINDINGS_SCHEMA_INVALID,
            "detail": schema_err,
            "persona": persona,
            "roundId": round_id,
        }

    # Fresh issue_get materializes the complete comment set before reconcile/retry (R8).
    record = client.issue_get(str(issue_id))
    if not comments_pagination_complete(record):
        return {
            "verdict": "fail",
            "action": verb,
            "error": DOC_REVIEW_PAGINATION_INCOMPLETE,
            "issueId": issue_id,
            "roundId": round_id,
        }
    manifest, manifest_err = inspect_review_round_block(record.body)
    if manifest_err:
        return manifest_malformed_result(action=verb, issue_id=str(issue_id), detail=manifest_err)

    key = idempotency_key(round_id, persona)
    digest = payload_hash(payload)
    matches = find_comments_by_idempotency_key(list(record.comments), round_id=round_id, key=key)
    if len(matches) > 1:
        return {
            "verdict": "fail",
            "action": verb,
            "error": DOC_REVIEW_IDEMPOTENCY_AMBIGUOUS,
            "persona": persona,
            "roundId": round_id,
            "matchCount": len(matches),
            "commentIds": [str(c.id) for c in matches],
        }
    existing = matches[0] if matches else None
    if existing is not None:
        existing_parsed = parse_doc_review_comment(existing.body)
        if existing_parsed is None or validate_doc_review_envelope(existing_parsed) is not None:
            return {"verdict": "fail", "action": verb, "error": "doc-review-comment-malformed"}
        proposed = {
            "round": round_id,
            "persona": persona,
            "idempotencyKey": key,
            "payloadHash": digest,
            "payload": payload,
        }
        if not envelope_immutable_equal(existing_parsed, proposed):
            return {
                "verdict": "fail",
                "action": verb,
                "error": "doc-review-idempotency-conflict",
                "persona": persona,
                "roundId": round_id,
            }
        pin = pin_from_comment(existing)
        if pin is None:
            return {"verdict": "fail", "action": verb, "error": "doc-review-comment-malformed"}
        if existing.author_id and existing.author_id != author_id:
            return {
                "verdict": "fail",
                "action": verb,
                "error": DOC_REVIEW_COMMENT_DRIFT,
                "driftKind": "author-mismatch",
                "commentId": existing.id,
            }
        bind_err = _binding_for_round(manifest)
        if bind_err is not None:
            return bind_err
        if manifest.get("roundId") != round_id or manifest.get("status") != "open":
            return {
                "verdict": "fail",
                "action": verb,
                "error": "doc-review-round-manifest-missing",
                "issueId": issue_id,
                "roundId": round_id,
            }
        pins, reconciled, conflict = merge_pin_into_manifest(list(manifest.get("pins") or []), pin)
        if conflict is not None:
            conflict["action"] = verb
            conflict["issueId"] = issue_id
            return conflict
        if reconciled:
            manifest["pins"] = pins
            pin_conflict = apply_manifest_update(
                client,
                issue_id=str(issue_id),
                verb=verb,
                record_body=record.body,
                etag=record.etag,
                manifest_block=manifest,
            )
            if pin_conflict is not None:
                return pin_conflict
        return {
            "verdict": "ok",
            "action": verb,
            "issueId": issue_id,
            "roundId": round_id,
            "persona": persona,
            "commentId": existing.id,
            "revision": existing.revision or existing.created_at,
            "authorId": existing.author_id or author_id,
            "idempotent": True,
            "reconciled": reconciled,
            "pin": pin.as_dict(include_snapshot=True),
        }

    body = build_doc_review_comment_body(round_id=round_id, persona=persona, payload=payload)
    if len(body) > DOC_REVIEW_COMMENT_SIZE_CAP:
        return {
            "verdict": "fail",
            "action": verb,
            "error": DOC_REVIEW_PAYLOAD_TOO_LARGE,
            "persona": persona,
            "roundId": round_id,
            "size": len(body),
            "limit": DOC_REVIEW_COMMENT_SIZE_CAP,
        }
    if dry_run:
        return {
            "verdict": "ok",
            "action": verb,
            "dryRun": True,
            "issueId": issue_id,
            "roundId": round_id,
            "persona": persona,
            "authorId": author_id,
        }

    try:
        from planning.backends.issues import doc_review_facade_issue_comment_scope

        with doc_review_facade_issue_comment_scope():
            posted = client.issue_comment(
                str(issue_id),
                body,
                markers=["sw-doc-review"],
                author_id=author_id,
            )
    except IssueCommentAuthorshipMismatch as exc:
        return {
            "verdict": "fail",
            "action": verb,
            "error": DOC_REVIEW_COMMENT_DRIFT,
            "driftKind": "author-mismatch",
            "commentId": exc.comment_id,
            "expectedAuthorId": exc.expected,
            "actualAuthorId": exc.actual,
        }

    if posted.author_id and posted.author_id != author_id:
        return {
            "verdict": "fail",
            "action": verb,
            "error": DOC_REVIEW_COMMENT_DRIFT,
            "driftKind": "author-mismatch",
            "commentId": posted.id,
        }

    pin = pin_from_comment(posted)
    if pin is None:
        return {"verdict": "fail", "action": verb, "error": "doc-review-comment-malformed"}

    refreshed = client.issue_get(str(issue_id))
    manifest, manifest_err = inspect_review_round_block(refreshed.body)
    if manifest_err:
        return manifest_malformed_result(action=verb, issue_id=str(issue_id), detail=manifest_err)
    bind_err = _binding_for_round(manifest)
    if bind_err is not None:
        return bind_err
    if manifest.get("roundId") != round_id or manifest.get("status") != "open":
        return {
            "verdict": "fail",
            "action": verb,
            "error": "doc-review-round-manifest-missing",
            "issueId": issue_id,
            "roundId": round_id,
        }
    pins, reconciled, conflict = merge_pin_into_manifest(list(manifest.get("pins") or []), pin)
    if conflict is not None:
        conflict["action"] = verb
        conflict["issueId"] = issue_id
        return conflict
    manifest["pins"] = pins
    pin_conflict = apply_manifest_update(
        client,
        issue_id=str(issue_id),
        verb=verb,
        record_body=refreshed.body,
        etag=refreshed.etag,
        manifest_block=manifest,
    )
    if pin_conflict is not None:
        return pin_conflict

    return {
        "verdict": "ok",
        "action": verb,
        "issueId": issue_id,
        "roundId": round_id,
        "persona": persona,
        "commentId": posted.id,
        "revision": posted.revision or posted.created_at,
        "authorId": posted.author_id or author_id,
        "idempotent": False,
        "reconciled": reconciled,
        "pin": pin.as_dict(include_snapshot=True),
    }
