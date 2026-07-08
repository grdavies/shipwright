#!/usr/bin/env python3
"""PRD 043 — normative canonical serialization + content-hash (R35, R9, R29, R47)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, unquote

CANONICAL_VERSION = "1"
BODY_SIZE_LIMIT = 60_000
EDGE_DIVERGENCE_TOLERANCE = 0

MARKER_PROJECT_KEY = re.compile(r"<!--\s*sw-project-key:\s*([a-z][a-z0-9-]*)\s*-->")
MARKER_ARTIFACT_TYPE = re.compile(r"<!--\s*sw-artifact-type:\s*(\w+)\s*-->")
MARKER_UNIT_ID = re.compile(r"<!--\s*sw-unit-id:\s*([^\s]+)\s*-->")
MARKER_CANONICAL_VERSION = re.compile(r"<!--\s*sw-canonical-version:\s*(\d+)\s*-->")
MARKER_CHUNK_MANIFEST = re.compile(
    r"<!--\s*sw-chunk-manifest:\s*(\{.*?\})\s*-->",
    re.DOTALL,
)

SW_EDGES_FENCE = re.compile(
    r"```sw-edges\s*\n(.*?)\n```",
    re.DOTALL,
)
GENERIC_CODE_FENCE = re.compile(r"```(?:\w+)?\s*\n(.*?)\n```", re.DOTALL)

EXCLUDED_COMMENT_MARKERS = frozenset({"sw-freeze-record", "sw-chunk-overflow"})
FREEZE_RECORD_MARKER = "sw-freeze-record"
FROZEN_LABEL = "sw:frozen"
FREEZE_INCOMPLETE_LABEL = "sw:freeze-incomplete"
FREEZE_HASH_PATTERN = re.compile(r"sw-freeze-hash:\s*([a-f0-9]{64})")

ARTIFACT_TYPES = frozenset({"prd", "gap", "tasks", "brainstorm", "decision", "amendment"})
TYPE_LABELS = {
    "prd": "sw:prd",
    "gap": "sw:gap",
    "tasks": "sw:tasks",
    "brainstorm": "sw:brainstorm",
    "decision": "sw:decision",
    "amendment": "sw:amendment",
}
STATUS_LABEL_PREFIX = "sw:status:"
GAP_LABEL_OPEN = "sw:gap-open"
GAP_LABEL_SCHEDULED = "sw:gap-scheduled"
GAP_LABEL_RESOLVED = "sw:gap-resolved"
SOURCE_REMOVED_LABEL = "sw:source-removed"
LEGACY_GAP_LABELS = frozenset({"open", "gap-scheduled", "resolved"})

# PRD 057 R12 -- product source tags (`sw:source:<owner>/<repo>`) so a shared
# planning repository can filter discovery/scheduler/gap-capture by the
# product code repo a unit originated from.
SOURCE_TAG_LABEL_PREFIX = "sw:source:"
SOURCE_MISSING_LABEL = "sw:source-missing"

# PRD 057 R17 -- schedule-hint reconciliation. Gap units carry a `schedule:`
# frontmatter hint (file-store) or an equivalent `sw:gap-schedule:` label
# (issue-store); reconcile compares the hint against the unit's actual
# `absorbs` edges and surfaces this label on mismatch.
GAP_SCHEDULE_LABEL_PREFIX = "sw:gap-schedule:"
SCHEDULE_STALE_LABEL = "sw:schedule-stale"


@dataclass
class CommentRecord:
    id: str
    body: str
    created_at: str = ""
    markers: list[str] = field(default_factory=list)

    def excluded_from_canonical(self) -> bool:
        return any(m in EXCLUDED_COMMENT_MARKERS for m in self.markers) or any(
            f"<!-- {m} -->" in self.body or f"<!--{m}-->" in self.body
            for m in EXCLUDED_COMMENT_MARKERS
        )


@dataclass
class IssueSnapshot:
    title: str
    body: str
    state: str
    labels: list[str]
    comments: list[CommentRecord] = field(default_factory=list)
    native_links: list[dict[str, Any]] = field(default_factory=list)
    etag: str = ""
    updated_at: str = ""


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def normalize_body(text: str) -> str:
    lines = normalize_newlines(text).split("\n")
    return "\n".join(line.rstrip() for line in lines).strip("\n")


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def infer_artifact_type(body_path: str) -> str:
    rel = body_path.replace("\\", "/").lower()
    if "/brainstorms/" in rel or rel.startswith("docs/brainstorms/"):
        return "brainstorm"
    if "/planning/brainstorm/" in rel:
        return "brainstorm"
    if "/planning/decision/" in rel:
        return "decision"
    if rel.startswith("docs/decisions/") and rel.endswith(".md") and not rel.endswith("/index.md"):
        return "decision"
    if "/gap/" in rel or "/planning/gap/" in rel or rel.startswith("docs/planning/gap/"):
        return "gap"
    if "/amendments/" in rel:
        return "amendment"
    base = rel.rsplit("/", 1)[-1]
    if base.startswith("tasks-"):
        return "tasks"
    if "-prd-" in base or ("/prds/" in rel and base.endswith(".md") and not base.startswith("tasks-")):
        return "prd"
    return "prd"


def gap_status_label(status: str | None) -> str | None:
    if not status:
        return None
    lowered = status.strip().lower()
    if lowered == "resolved":
        return GAP_LABEL_RESOLVED
    if lowered in {"planned", "scheduled"}:
        return GAP_LABEL_SCHEDULED
    if lowered == "open":
        return GAP_LABEL_OPEN
    return None


def gap_status_from_labels(labels: list[str]) -> str | None:
    label_set = set(labels)
    if GAP_LABEL_RESOLVED in label_set or "resolved" in label_set:
        return "resolved"
    if GAP_LABEL_SCHEDULED in label_set or "gap-scheduled" in label_set:
        return "planned"
    if GAP_LABEL_OPEN in label_set or "open" in label_set:
        return "open"
    return None


def status_from_labels(labels: list[str]) -> str | None:
    for label in labels:
        if label.startswith(STATUS_LABEL_PREFIX):
            return label[len(STATUS_LABEL_PREFIX) :]
    return None


def status_label(consumer_status: str) -> str:
    return f"{STATUS_LABEL_PREFIX}{consumer_status}"


def project_label(project_key: str) -> str:
    return f"sw:project:{project_key}"


def type_label(artifact_type: str) -> str:
    return TYPE_LABELS.get(artifact_type, f"sw:{artifact_type}")


def title_prefix(project_key: str) -> str:
    return f"[{project_key}]"


def source_tag_label(source: str) -> str:
    """R12 -- provider-native label form of a `sw:source:<owner>/<repo>` tag.

    GitHub labels accept `/` verbatim; Jira labels do not (spaces or `/` are
    invalid), so the Jira client percent-encodes the payload the same way it
    already does for `sw:gap-schedule:` (see `gap_schedule_label`).
    """
    return f"{SOURCE_TAG_LABEL_PREFIX}{source}"


def source_tag_from_labels(labels: list[str]) -> str:
    """Decode a `sw:source:<owner>/<repo>` tag from provider-native labels.

    Percent-decoding a raw (GitHub-style) label with no `%` is a no-op, so
    this handles both the GitHub and Jira label encodings.
    """
    for label in labels:
        if label.startswith(SOURCE_TAG_LABEL_PREFIX):
            return unquote(label[len(SOURCE_TAG_LABEL_PREFIX) :])
    return ""


def gap_schedule_label(schedule: str) -> str:
    """Jira labels cannot contain spaces or `/`; percent-encode the payload."""
    return f"{GAP_SCHEDULE_LABEL_PREFIX}{quote(schedule, safe='')}"


def gap_schedule_from_labels(labels: list[str]) -> str:
    for label in labels:
        if label.startswith(GAP_SCHEDULE_LABEL_PREFIX):
            return unquote(label[len(GAP_SCHEDULE_LABEL_PREFIX) :])
    return ""


def build_markers(project_key: str, artifact_type: str, unit_id: str) -> str:
    return (
        f"<!-- sw-project-key: {project_key} -->\n"
        f"<!-- sw-artifact-type: {artifact_type} -->\n"
        f"<!-- sw-unit-id: {unit_id} -->\n"
        f"<!-- sw-canonical-version: {CANONICAL_VERSION} -->\n"
    )


def is_sw_edges_payload(data: Any) -> bool:
    return (
        isinstance(data, dict)
        and isinstance(data.get("version"), int)
        and isinstance(data.get("edges"), list)
        and isinstance(data.get("native"), list)
    )


def parse_edges_fence_inner(inner: str) -> dict[str, Any] | None:
    try:
        data = json.loads(inner.strip())
    except json.JSONDecodeError:
        return None
    return data if is_sw_edges_payload(data) else None


def build_edges_block(edges: list[dict[str, Any]] | None, native: list[dict[str, Any]] | None = None) -> str:
    payload = {
        "version": 1,
        "edges": edges or [],
        "native": native or [],
    }
    return f"```sw-edges\n{json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)}\n```"


def strip_markers_and_edges(body: str) -> str:
    text = normalize_body(body)
    for pattern in (
        MARKER_PROJECT_KEY,
        MARKER_ARTIFACT_TYPE,
        MARKER_UNIT_ID,
        MARKER_CANONICAL_VERSION,
        MARKER_CHUNK_MANIFEST,
    ):
        text = pattern.sub("", text)
    text = SW_EDGES_FENCE.sub("", text)
    for match in list(GENERIC_CODE_FENCE.finditer(text)):
        if parse_edges_fence_inner(match.group(1)):
            text = text[: match.start()] + text[match.end() :]
    return normalize_body(text)


def parse_body_marker(body: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.search(body)
    return match.group(1).strip() if match else None


def parse_edges_block(body: str) -> dict[str, Any] | None:
    match = SW_EDGES_FENCE.search(body)
    if match:
        data = parse_edges_fence_inner(match.group(1))
        return data
    for generic in GENERIC_CODE_FENCE.finditer(body):
        data = parse_edges_fence_inner(generic.group(1))
        if data:
            return data
    return None


def reconcile_edges(
    body_edges: dict[str, Any] | None,
    native_links: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    body_edges = body_edges or {"version": 1, "edges": [], "native": []}
    native_links = native_links or []
    body_native = body_edges.get("native") if isinstance(body_edges.get("native"), list) else []
    body_edge_list = body_edges.get("edges") if isinstance(body_edges.get("edges"), list) else []

    def _norm_edges(edges: list[Any]) -> list[str]:
        out: list[str] = []
        for edge in edges:
            if isinstance(edge, dict):
                out.append(json.dumps(edge, sort_keys=True, ensure_ascii=False))
            else:
                out.append(json.dumps(edge, sort_keys=True, ensure_ascii=False, default=str))
        return sorted(out)

    body_native_set = set(_norm_edges(body_native))
    native_set = set(_norm_edges(native_links))

    symmetric_diff = len(body_native_set.symmetric_difference(native_set))
    if symmetric_diff > EDGE_DIVERGENCE_TOLERANCE and native_set:
        raise ValueError(
            f"edge-divergence: body native projection differs from provider native links "
            f"(diff={symmetric_diff}, tolerance={EDGE_DIVERGENCE_TOLERANCE})"
        )

    return {
        "version": body_edges.get("version", 1),
        "edges": body_edge_list,
        "native": native_links if native_links else body_native,
    }




_EDGE_REL_TO_NATIVE_TYPE: dict[str, str] = {
    "depends": "depends-on",
    "blocks": "blocks",
    "sub-issue-of": "sub-issue-of",
    "extends": "extends",
    "supersedes": "supersedes",
    "absorbs": "absorbs",
    "prd": "prd",
    "amends": "amends",
    "brainstorm": "brainstorm",
}


def native_links_from_edges(
    edge_list: list[dict[str, Any]],
    index: dict[str, str],
    *,
    project_key: str,
) -> list[dict[str, Any]]:
    """Resolve sw-edges unit targets to provider issue ids via the issue unit index."""
    out: list[dict[str, Any]] = []
    for edge in edge_list or []:
        if not isinstance(edge, dict):
            continue
        rel = str(edge.get("rel") or edge.get("type") or "").strip()
        target_raw = edge.get("target")
        if not rel or target_raw is None:
            continue
        targets = target_raw if isinstance(target_raw, list) else [target_raw]
        link_type = _EDGE_REL_TO_NATIVE_TYPE.get(rel, rel)
        for target_unit in targets:
            unit_id = str(target_unit).strip()
            if not unit_id:
                continue
            idx_key = f"{project_key}:{unit_id}"
            issue_id = index.get(idx_key)
            if not issue_id:
                continue
            entry = {"type": link_type, "target": issue_id}
            if entry not in out:
                out.append(entry)
    return out

def compose_issue_body(
    project_key: str,
    artifact_type: str,
    unit_id: str,
    content: str,
    *,
    edges: list[dict[str, Any]] | None = None,
    native_links: list[dict[str, Any]] | None = None,
    chunk_manifest: dict[str, Any] | None = None,
) -> str:
    parts = [build_markers(project_key, artifact_type, unit_id)]
    if chunk_manifest:
        parts.append(f"<!-- sw-chunk-manifest: {json.dumps(chunk_manifest, sort_keys=True, ensure_ascii=False)} -->")
    parts.append(normalize_body(content))
    if edges is not None or native_links:
        parts.append(build_edges_block(edges, native_links))
    return "\n\n".join(p for p in parts if p)


def append_chunk_manifest_marker(head: str, marker: str) -> str:
    """Append manifest HTML comment without stripping trailing paragraph breaks."""
    if MARKER_CHUNK_MANIFEST.search(head):
        return MARKER_CHUNK_MANIFEST.sub(marker, head)
    trimmed = head.rstrip(" \t\r")
    if not trimmed.endswith("\n"):
        trimmed += "\n"
    return trimmed + marker


def chunk_body_if_needed(
    body: str,
    comments: list[CommentRecord],
    *,
    provider: str | None = None,
) -> tuple[str, list[CommentRecord]]:
    if provider == "jira":
        # R9: Jira Cloud's ADF description/comment payload limits (~32KB) are
        # far tighter than the generic BODY_SIZE_LIMIT below, so a body that
        # fits under the generic limit can still overflow Jira's own
        # client-side check and be rejected at issue_create/issue_update time.
        # Delegate to the Jira-aware splitter so oversized-for-Jira bodies
        # chunk here, before the client ever sees them.
        #
        # Lazy import: `planning_jira_canonical` imports the generic markers
        # and helpers from this module at top level, so importing it back
        # here at module scope would create a circular import. Deferring the
        # import until this branch actually runs is safe -- both modules are
        # already fully loaded by the time `chunk_body_if_needed` executes.
        from planning_jira_canonical import chunk_body_for_jira_cloud

        return chunk_body_for_jira_cloud(body, comments)
    if len(body.encode("utf-8")) <= BODY_SIZE_LIMIT:
        return body, comments
    encoded = body.encode("utf-8")
    head = encoded[:BODY_SIZE_LIMIT].decode("utf-8", errors="ignore")
    overflow = encoded[BODY_SIZE_LIMIT:].decode("utf-8", errors="ignore")
    chunk_id = f"chunk-{len(comments)}"
    chunk_comment = CommentRecord(
        id=chunk_id,
        body=f"<!-- sw-chunk-overflow -->\n{overflow}",
        markers=["sw-chunk-overflow"],
    )
    new_comments = list(comments) + [chunk_comment]
    manifest = {"version": 1, "chunks": [{"index": 0, "commentId": chunk_id}]}
    if MARKER_CHUNK_MANIFEST.search(head):
        head = MARKER_CHUNK_MANIFEST.sub(
            f"<!-- sw-chunk-manifest: {json.dumps(manifest, sort_keys=True, ensure_ascii=False)} -->",
            head,
        )
    else:
        marker = f"<!-- sw-chunk-manifest: {json.dumps(manifest, sort_keys=True, ensure_ascii=False)} -->"
        head = append_chunk_manifest_marker(head, marker)
    return head, new_comments


def rewrite_chunk_manifest_ids(body: str, comment_ids: list[str]) -> str:
    """R8 -- replace synthetic placeholder chunk ids with real provider ids.

    ``chunk_body_if_needed`` assigns synthetic placeholder ids (``chunk-N``)
    before the provider has created the overflow comments and issued real
    ids. Call this once those comments are actually posted (in the same order
    they were generated, so ``comment_ids[i]`` is the real id for chunk index
    ``i``) so the manifest baked into the persisted body carries the real ids
    that ``reassemble_body`` can match directly -- instead of falling back to
    positional matching against every ``sw-chunk-overflow`` comment on the
    issue, which can select a stale comment left over from an earlier put.
    """
    if not comment_ids:
        return body
    manifest = {
        "version": 1,
        "chunks": [{"index": index, "commentId": cid} for index, cid in enumerate(comment_ids)],
    }
    marker = f"<!-- sw-chunk-manifest: {json.dumps(manifest, sort_keys=True, ensure_ascii=False)} -->"
    return append_chunk_manifest_marker(body, marker)


def _overflow_chunk_comments(comments: list[CommentRecord]) -> list[CommentRecord]:
    ordered = sorted(
        [
            c
            for c in comments
            if "sw-chunk-overflow" in c.markers
            or "<!-- sw-chunk-overflow -->" in c.body
            or "<!--sw-chunk-overflow-->" in c.body
        ],
        key=lambda c: (c.created_at, c.id),
    )
    unique: list[CommentRecord] = []
    seen: set[str] = set()
    for comment in ordered:
        body = re.sub(r"<!--\s*sw-chunk-overflow\s*-->\n?", "", comment.body)
        digest = hashlib.sha256(normalize_body(body).encode("utf-8")).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        unique.append(comment)
    return unique




def _last_line(text: str) -> str:
    lines = text.rstrip("\n").split("\n")
    return lines[-1] if lines else ""


def _needs_extra_paragraph_break(merged: str, stripped_part: str) -> bool:
    if not merged.endswith("\n") or merged.endswith("\n\n"):
        return False
    last = _last_line(merged).strip()
    if not last or not stripped_part:
        return False
    first = stripped_part.split("\n", 1)[0].strip()
    if first.startswith("#") and not last.startswith("#"):
        return True
    if first.startswith("- ") and last.startswith("#"):
        return True
    if first.startswith("```") and last and not last.startswith("```"):
        return True
    return False


def _append_reassembled_part(merged: str, part: str) -> str:
    if not part:
        return merged
    if merged and not merged.endswith("\n"):
        merged += "\n"
    stripped = part.lstrip("\n")
    if _needs_extra_paragraph_break(merged, stripped):
        merged += "\n"
    merged += stripped
    return merged

def reassemble_body(body: str, comments: list[CommentRecord]) -> str:
    text = normalize_body(body)
    manifest_match = MARKER_CHUNK_MANIFEST.search(text)
    if not manifest_match:
        return text
    try:
        manifest = json.loads(manifest_match.group(1))
    except json.JSONDecodeError:
        return text
    chunks = manifest.get("chunks") if isinstance(manifest, dict) else None
    if not isinstance(chunks, list):
        return text
    comment_by_id = {c.id: c for c in comments}
    overflow_comments = _overflow_chunk_comments(comments)
    overflow_parts: list[str] = []
    for entry in sorted(chunks, key=lambda x: x.get("index", 0) if isinstance(x, dict) else 0):
        if not isinstance(entry, dict):
            continue
        cid = entry.get("commentId")
        comment = comment_by_id.get(cid) if isinstance(cid, str) else None
        if comment is None:
            index = entry.get("index")
            if isinstance(index, int) and 0 <= index < len(overflow_comments):
                comment = overflow_comments[index]
        if comment is None:
            continue
        chunk_text = comment.body
        chunk_text = re.sub(r"<!--\s*sw-chunk-overflow\s*-->\n?", "", chunk_text)
        overflow_parts.append(chunk_text)
    base = MARKER_CHUNK_MANIFEST.sub("", text)
    merged = base
    for part in overflow_parts:
        merged = _append_reassembled_part(merged, part)
    return normalize_body(merged)


def canonical_comments(comments: list[CommentRecord]) -> list[dict[str, str]]:
    included = [c for c in comments if not c.excluded_from_canonical()]
    included.sort(key=lambda c: (c.created_at, c.id))
    return [{"id": c.id, "body": normalize_body(c.body)} for c in included]


def canonical_form(snapshot: IssueSnapshot) -> str:
    full_body = reassemble_body(snapshot.body, snapshot.comments)
    payload = {
        "sw-canonical-version": CANONICAL_VERSION,
        "title": normalize_body(snapshot.title),
        "body": normalize_body(full_body),
        "state": snapshot.state,
        "labels": sorted(snapshot.labels),
        "comments": canonical_comments(snapshot.comments),
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def canonical_hash(snapshot: IssueSnapshot) -> str:
    return hashlib.sha256(canonical_form(snapshot).encode("utf-8")).hexdigest()


def compute_etag(updated_at: str, body: str, title: str, labels: list[str]) -> str:
    material = json.dumps(
        {"updated_at": updated_at, "body": body, "title": title, "labels": sorted(labels)},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def verify_project_scope(body: str, project_key: str) -> bool:
    marker = parse_body_marker(body, MARKER_PROJECT_KEY)
    return marker == project_key


def verify_unit_id(body: str, unit_id: str) -> bool:
    marker = parse_body_marker(body, MARKER_UNIT_ID)
    return marker == unit_id


def parse_freeze_record_hash(comments: list[CommentRecord]) -> str | None:
    """Return the hash from the most recent `sw-freeze-record` comment (gap-052)."""
    latest_hash: str | None = None
    for comment in sorted(comments, key=lambda c: (c.created_at, c.id)):
        if FREEZE_RECORD_MARKER not in comment.markers and not comment.excluded_from_canonical():
            if f"<!-- {FREEZE_RECORD_MARKER} -->" not in comment.body and f"<!--{FREEZE_RECORD_MARKER}-->" not in comment.body:
                continue
        match = FREEZE_HASH_PATTERN.search(comment.body)
        if match:
            latest_hash = match.group(1)
    return latest_hash


def build_freeze_record_body(content_hash: str) -> str:
    return f"<!-- {FREEZE_RECORD_MARKER} -->\nsw-freeze-hash: {content_hash}\n"
