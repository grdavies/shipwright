#!/usr/bin/env python3
"""PRD 043 — normative canonical serialization + content-hash (R35, R9, R29, R47)."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, unquote

import planning_index_gen as pig

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
# Sentinel returned by ``infer_artifact_type`` for opaque issue-store locators
# (``issue:<n>`` / ``issue-cache:<n>``) that carry no path-shape type signal.
ARTIFACT_TYPE_UNRESOLVED = "__unresolved__"
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

# PRD 057 R27 -- last-writer-wins body+comment consistency. Each generic
# (non-Jira) chunk_body_if_needed call mints one write-token spanning the
# whole comment set it produces, carried in the manifest's writeToken field
# and in each overflow comment's sw-chunk-token:<token> marker. Deliberately
# a comment *marker* (structural metadata), never literal body text: the
# fixture issue store preserves markers verbatim, so token-scoped reassembly
# works end-to-end offline, without perturbing the byte-for-byte overflow
# body content other fixtures (R8) already assert on. Live provider clients
# (GitHub/Jira) only round-trip a small fixed marker set from body text today
# and will not carry this token -- reassembly there simply falls back to the
# pre-existing (unscoped) behavior, never a regression.
CHUNK_TOKEN_MARKER_PREFIX = "sw-chunk-token:"


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


def is_opaque_body_path(body_path: str) -> bool:
    norm = body_path.replace("\\", "/").lower().strip()
    return norm.startswith("issue:") or norm.startswith("issue-cache:")


def is_resolved_artifact_type(artifact_type: str | None) -> bool:
    return bool(artifact_type) and artifact_type in ARTIFACT_TYPES


def artifact_type_from_content(content: str) -> str | None:
    """Read artifact type from body marker or frontmatter ``type:`` (R1/R2)."""
    marker = parse_body_marker(content, MARKER_ARTIFACT_TYPE)
    if marker and marker in ARTIFACT_TYPES:
        return marker
    if content.startswith("---"):
        fm = pig.parse_frontmatter(content)
        if fm and fm.get("type"):
            candidate = str(fm["type"]).strip().lower()
            if candidate in ARTIFACT_TYPES:
                return candidate
    return None


class ArtifactTypeUnresolved(ValueError):
    def __init__(self, body_path: str, *, unit_id: str | None = None) -> None:
        self.body_path = body_path
        self.unit_id = unit_id
        super().__init__(f"artifact type unresolved for body path {body_path!r}")


def infer_artifact_type(body_path: str) -> str:
    if is_opaque_body_path(body_path):
        return ARTIFACT_TYPE_UNRESOLVED
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


# PRD 057 R11 (gap-030, D5) -- provider-native label projections for the
# structural frontmatter keys (type/unit-id/status/topic/depends/absorbs/
# amends/visibility). These are ADDITIVE: the doc's own frontmatter block
# stays embedded in the issue body for the one-release dual-read window
# (frontmatter remains authoritative there per the Wave 4 revert path) --
# labels are the vendor-native read/discover projection, letting search and
# list operations resolve unit metadata without fetching/parsing full issue
# bodies, and letting an old (pre-R11) issue's frontmatter-only metadata
# still resolve correctly via the body-marker/frontmatter fallback already
# used throughout this module and its callers.
UNIT_LABEL_PREFIX = "sw:unit:"
TOPIC_LABEL_PREFIX = "sw:topic:"
VISIBILITY_LABEL_PREFIX = "sw:visibility:"
EDGE_LABEL_PREFIXES: dict[str, str] = {
    "depends": "sw:depends:",
    "absorbs": "sw:absorbs:",
    "amends": "sw:amends:",
}
# GitHub allows up to 100 labels/issue -- comfortably enough headroom for the
# handful of structural labels plus a generous edge-label allowance. Jira has
# no hard per-issue label *count* limit, but (matching the existing
# `gap_schedule_label` / `source_tag_label` percent-encoding convention)
# label *values* cannot contain spaces, so multi-word edge targets are
# percent-encoded here too. This cap keeps the label projection well inside
# both providers' practical limits; a unit with more edges than the cap
# never loses data -- the authoritative `sw-edges` body fence (D5, PRD 056
# D2) always carries every edge regardless of what the label projection can
# fit, so a truncated label set degrades discovery convenience only.
MAX_EDGE_LABELS_PER_RELATION = 20

STRUCTURAL_FRONTMATTER_KEYS = (
    "type",
    "unit-id",
    "status",
    "topic",
    "depends",
    "absorbs",
    "amends",
    "visibility",
)


def unit_id_label(unit_id: str) -> str:
    return f"{UNIT_LABEL_PREFIX}{quote(unit_id, safe='')}"


def unit_id_from_labels(labels: list[str]) -> str:
    for label in labels:
        if label.startswith(UNIT_LABEL_PREFIX):
            return unquote(label[len(UNIT_LABEL_PREFIX) :])
    return ""


def artifact_type_from_labels(labels: list[str]) -> str:
    """Reverse-lookup of `type_label` -- the label side of the R11 dual-read
    projection for `artifact_type` (body-marker fallback lives in callers)."""
    label_set = set(labels)
    for artifact_type, label in TYPE_LABELS.items():
        if label in label_set:
            return artifact_type
    return ""


def require_artifact_type(
    body_path: str,
    *,
    record_type: str | None = None,
    content: str | None = None,
    caller_type: str | None = None,
    labels: list[str] | None = None,
) -> str:
    """Resolve a concrete artifact type (R1/R2).

    Preference: existing record type → content/frontmatter → caller hint →
    type labels → path-shape inference (non-opaque paths only). Fail closed
    when none resolve.
    """
    for candidate in (
        record_type,
        artifact_type_from_content(content) if content else None,
        caller_type,
        artifact_type_from_labels(labels) if labels else None,
    ):
        if is_resolved_artifact_type(candidate):
            return candidate  # type: ignore[return-value]
    inferred = infer_artifact_type(body_path)
    if is_resolved_artifact_type(inferred):
        return inferred
    raise ArtifactTypeUnresolved(body_path)


def topic_label(topic: str) -> str:
    return f"{TOPIC_LABEL_PREFIX}{quote(topic, safe='')}"


def topic_from_labels(labels: list[str]) -> str:
    for label in labels:
        if label.startswith(TOPIC_LABEL_PREFIX):
            return unquote(label[len(TOPIC_LABEL_PREFIX) :])
    return ""


def visibility_label(visibility: str) -> str:
    return f"{VISIBILITY_LABEL_PREFIX}{quote(visibility, safe='')}"


def visibility_from_labels(labels: list[str]) -> str:
    for label in labels:
        if label.startswith(VISIBILITY_LABEL_PREFIX):
            return unquote(label[len(VISIBILITY_LABEL_PREFIX) :])
    return ""


def edge_labels_for(rel: str, targets: list[str]) -> list[str]:
    """Provider-native label projection of a `depends`/`absorbs`/`amends`
    edge list (R11). Silently caps at `MAX_EDGE_LABELS_PER_RELATION` -- see
    that constant's docstring for why truncation here never loses data."""
    prefix = EDGE_LABEL_PREFIXES.get(rel)
    if not prefix:
        return []
    out: list[str] = []
    for target in targets[:MAX_EDGE_LABELS_PER_RELATION]:
        cleaned = str(target).strip()
        if not cleaned:
            continue
        out.append(f"{prefix}{quote(cleaned, safe='')}")
    return out


def edges_from_labels(labels: list[str], rel: str) -> list[str]:
    prefix = EDGE_LABEL_PREFIXES.get(rel)
    if not prefix:
        return []
    out: list[str] = []
    for label in labels:
        if label.startswith(prefix):
            value = unquote(label[len(prefix) :])
            if value and value not in out:
                out.append(value)
    return out


def structural_labels_from_content(content: str) -> list[str]:
    """R11 write-side -- promote a doc's structural frontmatter keys (type/
    unit-id/status/topic/depends/absorbs/amends/visibility) to provider-
    native labels. Purely additive: `content`'s own frontmatter block is
    untouched by this function and keeps being embedded in the issue body
    (dual-read window, D5) -- this only computes the label projection of it.
    """
    if not content.startswith("---"):
        return []
    fm = pig.parse_frontmatter(content)
    if not fm:
        return []
    labels: list[str] = []
    if fm.get("type"):
        labels.append(type_label(str(fm["type"])))
    if fm.get("unit-id"):
        labels.append(unit_id_label(str(fm["unit-id"])))
    if fm.get("status"):
        labels.append(status_label(str(fm["status"])))
    if fm.get("topic"):
        labels.append(topic_label(str(fm["topic"])))
    if fm.get("visibility"):
        labels.append(visibility_label(str(fm["visibility"])))
    for rel in ("depends", "absorbs", "amends"):
        value = fm.get(rel)
        targets = value if isinstance(value, list) else ([value] if value else [])
        labels.extend(edge_labels_for(rel, [str(t) for t in targets]))
    return labels


def human_readable_title(content: str, artifact_type: str, unit_id: str) -> str:
    """R11 -- issue title without the legacy `[project] type:unit-id`
    prefix (see `title_prefix`, still used by the one-time migration writer
    for its own separate cutover path). The provider-assigned id is a
    storage pointer only, so nothing about unit identity depends on this
    title being unique, stable, or parseable -- it exists purely so a human
    operator browsing the tracker sees the document's own name instead of a
    synthetic `type:unit-id` string.

    Prefers an explicit frontmatter `title:` key, then the document's first
    H1 heading, then falls back to a plain (still bracket-free) `type:
    unit-id` string for a stub write that has neither yet.
    """
    body = content
    fm = pig.parse_frontmatter(content) if content.startswith("---") else None
    if fm and fm.get("title"):
        return str(fm["title"]).strip()[:250]
    if fm:
        parts = content.split("---", 2)
        body = parts[2] if len(parts) >= 3 else content
    for line in normalize_body(body).split("\n"):
        stripped = line.strip()
        if stripped.startswith("# "):
            heading = stripped[2:].strip()
            if heading:
                return heading[:250]
    return f"{artifact_type}: {unit_id}"[:250]


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


def _manifest_write_token(body: str) -> str | None:
    """Extract the writeToken (if any) from the sw-chunk-manifest already
    embedded in ``body``, so a manifest rewrite (real ids replacing synthetic
    placeholders) preserves the write-session token instead of dropping it
    (R27)."""
    match = MARKER_CHUNK_MANIFEST.search(body)
    if not match:
        return None
    try:
        existing = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    token = existing.get("writeToken") if isinstance(existing, dict) else None
    return token if isinstance(token, str) and token else None


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
    # R27: one write-token per chunking call, spanning this whole comment set
    # (see CHUNK_TOKEN_MARKER_PREFIX docstring above) -- a concurrent writer's
    # own (differently-tokened) overflow comments are never picked up by this
    # session's positional-fallback reassembly.
    write_token = uuid.uuid4().hex[:12]
    chunk_comment = CommentRecord(
        id=chunk_id,
        body=f"<!-- sw-chunk-overflow -->\n{overflow}",
        markers=["sw-chunk-overflow", f"{CHUNK_TOKEN_MARKER_PREFIX}{write_token}"],
    )
    new_comments = list(comments) + [chunk_comment]
    manifest = {
        "version": 1,
        "chunks": [{"index": 0, "commentId": chunk_id}],
        "writeToken": write_token,
    }
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

    R27: preserves the write-token (if any) already embedded in ``body``'s
    manifest, so a rewritten manifest still scopes positional-fallback
    reassembly to this write session's own overflow comments.
    """
    if not comment_ids:
        return body
    manifest: dict[str, Any] = {
        "version": 1,
        "chunks": [{"index": index, "commentId": cid} for index, cid in enumerate(comment_ids)],
    }
    token = _manifest_write_token(body)
    if token:
        manifest["writeToken"] = token
    marker = f"<!-- sw-chunk-manifest: {json.dumps(manifest, sort_keys=True, ensure_ascii=False)} -->"
    return append_chunk_manifest_marker(body, marker)


def overflow_chunk_comments(
    comments: list[CommentRecord],
    *,
    token: str | None = None,
) -> list[CommentRecord]:
    """Overflow comments eligible for positional-fallback reassembly.

    R27: when ``token`` is given (the current manifest's ``writeToken``),
    scope the result to comments carrying a matching ``sw-chunk-token:``
    marker -- excluding another writer's (or a superseded write attempt's)
    overflow comments left on the same issue, so reassembly never builds a
    hybrid body out of two different write sessions. ``token=None`` (no
    token on the manifest -- Jira-built or pre-R27 manifests) keeps the
    original unscoped behavior.
    """
    candidates = [
        c
        for c in comments
        if "sw-chunk-overflow" in c.markers
        or "<!-- sw-chunk-overflow -->" in c.body
        or "<!--sw-chunk-overflow-->" in c.body
    ]
    if token:
        token_marker = f"{CHUNK_TOKEN_MARKER_PREFIX}{token}"
        candidates = [c for c in candidates if token_marker in c.markers]
    ordered = sorted(candidates, key=lambda c: (c.created_at, c.id))
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
    write_token = manifest.get("writeToken") if isinstance(manifest, dict) else None
    comment_by_id = {c.id: c for c in comments}
    # R27: direct commentId matches below are unambiguous regardless of
    # write-token (real provider ids are globally unique); the positional
    # fallback is the only path a stray concurrent/superseded write session's
    # overflow comment could leak into, so scope that list to this
    # manifest's own write-token.
    overflow_comments = overflow_chunk_comments(comments, token=write_token)
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
