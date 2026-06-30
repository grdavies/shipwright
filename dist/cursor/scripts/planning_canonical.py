#!/usr/bin/env python3
"""PRD 043 — normative canonical serialization + content-hash (R35, R9, R29, R47)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

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

EXCLUDED_COMMENT_MARKERS = frozenset({"sw-freeze-record", "sw-chunk-overflow"})
FREEZE_RECORD_MARKER = "sw-freeze-record"
FROZEN_LABEL = "sw:frozen"
FREEZE_INCOMPLETE_LABEL = "sw:freeze-incomplete"
FREEZE_HASH_PATTERN = re.compile(r"sw-freeze-hash:\s*([a-f0-9]{64})")

ARTIFACT_TYPES = frozenset({"prd", "gap", "tasks", "brainstorm"})
TYPE_LABELS = {
    "prd": "sw:prd",
    "gap": "sw:gap",
    "tasks": "sw:tasks",
    "brainstorm": "sw:brainstorm",
}


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


def infer_artifact_type(body_path: str) -> str:
    rel = body_path.replace("\\", "/").lower()
    if "/brainstorms/" in rel or rel.startswith("docs/brainstorms/"):
        return "brainstorm"
    if "/gap/" in rel or "/planning/gap/" in rel or rel.startswith("docs/planning/gap/"):
        return "gap"
    base = rel.rsplit("/", 1)[-1]
    if base.startswith("tasks-"):
        return "tasks"
    if "-prd-" in base or ("/prds/" in rel and base.endswith(".md") and not base.startswith("tasks-")):
        return "prd"
    return "prd"


def project_label(project_key: str) -> str:
    return f"sw:project:{project_key}"


def type_label(artifact_type: str) -> str:
    return TYPE_LABELS.get(artifact_type, f"sw:{artifact_type}")


def title_prefix(project_key: str) -> str:
    return f"[{project_key}]"


def build_markers(project_key: str, artifact_type: str, unit_id: str) -> str:
    return (
        f"<!-- sw-project-key: {project_key} -->\n"
        f"<!-- sw-artifact-type: {artifact_type} -->\n"
        f"<!-- sw-unit-id: {unit_id} -->\n"
        f"<!-- sw-canonical-version: {CANONICAL_VERSION} -->\n"
    )


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
    return normalize_body(text)


def parse_body_marker(body: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.search(body)
    return match.group(1).strip() if match else None


def parse_edges_block(body: str) -> dict[str, Any] | None:
    match = SW_EDGES_FENCE.search(body)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


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


def chunk_body_if_needed(
    body: str,
    comments: list[CommentRecord],
) -> tuple[str, list[CommentRecord]]:
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
        head = head.rstrip() + f"\n<!-- sw-chunk-manifest: {json.dumps(manifest, sort_keys=True, ensure_ascii=False)} -->"
    return head, new_comments


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
    overflow_parts: list[str] = []
    for entry in sorted(chunks, key=lambda x: x.get("index", 0) if isinstance(x, dict) else 0):
        if not isinstance(entry, dict):
            continue
        cid = entry.get("commentId")
        if not isinstance(cid, str):
            continue
        comment = comment_by_id.get(cid)
        if comment is None:
            continue
        chunk_text = comment.body
        chunk_text = re.sub(r"<!--\s*sw-chunk-overflow\s*-->\n?", "", chunk_text)
        overflow_parts.append(chunk_text)
    base = MARKER_CHUNK_MANIFEST.sub("", text)
    return normalize_body(base + "".join(overflow_parts))


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
    for comment in comments:
        if FREEZE_RECORD_MARKER not in comment.markers and not comment.excluded_from_canonical():
            if f"<!-- {FREEZE_RECORD_MARKER} -->" not in comment.body and f"<!--{FREEZE_RECORD_MARKER}-->" not in comment.body:
                continue
        match = FREEZE_HASH_PATTERN.search(comment.body)
        if match:
            return match.group(1)
    return None


def build_freeze_record_body(content_hash: str) -> str:
    return f"<!-- {FREEZE_RECORD_MARKER} -->\nsw-freeze-hash: {content_hash}\n"
