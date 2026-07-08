#!/usr/bin/env python3
"""Chunk-manifest id rewrite + reassembly fixture (PRD 057 R8).

Proves, fully offline and deterministically (fixture issues store, no
network):

1. **Synthetic placeholder ids** — `chunk_body_if_needed` bakes a synthetic
   `chunk-N` placeholder id into the `sw-chunk-manifest` marker before any
   provider comment exists.
2. **Real-id rewrite** — `rewrite_chunk_manifest_ids` replaces those
   placeholders with the real provider comment ids, in posting order.
3. **`reassemble_body` prefers the real id** — given a manifest that names a
   real comment id directly, reassembly picks that comment even when a
   same-shaped *decoy* `sw-chunk-overflow` comment (a different id, different
   content) is also present on the issue — it never falls back to positional
   guessing when a direct id match exists.
4. **`IssueStoreBackend.put` rewrites the manifest with the real id** —
   end-to-end: a chunked `put` persists a body whose manifest `commentId`
   equals the id the fixture issues store actually assigned the overflow
   comment (never the `chunk-N` synthetic placeholder).
5. **Many: repeated large updates never reassemble a stale comment** — three
   successive chunked `put`s of the same unit (each producing a new overflow
   comment; the two earlier ones are left orphaned on the issue) each `get`
   back byte-exact, with zero cross-contamination from an earlier update's
   overflow content.
6. **Zero: a body under the chunk threshold is untouched** — `put` for a
   small body never allocates a chunk manifest or posts an overflow comment.

No network, no live issue store required (`SW_ISSUES_FIXTURE=1`).

ZOMBIES: Zero (small body, no chunking) · One (single chunk) · Many (repeated
large updates) · Boundaries (`BODY_SIZE_LIMIT` overflow threshold) ·
Interfaces (manifest rewrite) · State (real ids replace synthetic; no stale
comment ever selected).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

os.environ.setdefault("SW_ISSUES_FIXTURE", "1")

from planning_canonical import (  # noqa: E402
    BODY_SIZE_LIMIT,
    CommentRecord,
    MARKER_CHUNK_MANIFEST,
    chunk_body_if_needed,
    compose_issue_body,
    reassemble_body,
    rewrite_chunk_manifest_ids,
)

_SENTINEL = "XCONTENTSTART"


def _prefix_byte_len(project_key: str, artifact_type: str, unit_id: str) -> int:
    """Byte length of everything `compose_issue_body` prepends before content."""
    composed = compose_issue_body(project_key, artifact_type, unit_id, _SENTINEL)
    idx = composed.index(_SENTINEL)
    return len(composed[:idx].encode("utf-8"))


def _make_clean_overflow_content(
    tag: str, project_key: str, artifact_type: str, unit_id: str, *, filler: str = "A"
) -> str:
    """Content sized so `chunk_body_if_needed`'s byte-offset cut lands exactly
    on a paragraph break, giving a byte-exact (not just id-correct)
    reassembly round trip for the "Many: repeated updates" check below."""
    prefix = f"# Title {tag}\n\n"
    target_content_len = BODY_SIZE_LIMIT - _prefix_byte_len(project_key, artifact_type, unit_id)
    filler_len = target_content_len - len(prefix) - 2
    head = prefix + (filler * filler_len) + "\n\n"
    tail = f"Paragraph {tag} tail content here\n\nEND-{tag}"
    return head + tail


def check_chunk_body_if_needed_uses_synthetic_placeholder() -> dict:
    body = compose_issue_body("proj", "prd", "unit-x", "A" * (BODY_SIZE_LIMIT + 500))
    head, comments = chunk_body_if_needed(body, [])
    match = MARKER_CHUNK_MANIFEST.search(head)
    manifest = json.loads(match.group(1)) if match else None
    ok = (
        len(comments) == 1
        and comments[0].id == "chunk-0"
        and manifest is not None
        and manifest["chunks"][0]["commentId"] == "chunk-0"
    )
    return {
        "name": "chunk-body-if-needed-synthetic-placeholder",
        "ok": ok,
        "detail": f"commentIds={[c.id for c in comments]} manifest={manifest}",
    }


def check_rewrite_chunk_manifest_ids_replaces_synthetic() -> dict:
    body = compose_issue_body("proj", "prd", "unit-x", "A" * (BODY_SIZE_LIMIT + 500))
    head, comments = chunk_body_if_needed(body, [])
    rewritten = rewrite_chunk_manifest_ids(head, ["real-comment-42"])
    match = MARKER_CHUNK_MANIFEST.search(rewritten)
    manifest = json.loads(match.group(1)) if match else None
    ok = manifest is not None and manifest["chunks"] == [{"index": 0, "commentId": "real-comment-42"}]
    return {"name": "rewrite-chunk-manifest-ids-replaces-synthetic", "ok": ok, "detail": manifest}


def check_reassemble_prefers_real_id_over_decoy() -> dict:
    """A manifest naming a real id must win over a same-shaped decoy comment
    with different content and a different id -- direct id match, never
    positional guessing, when a real id is present."""
    body = compose_issue_body("proj", "prd", "unit-x", "HEAD-" + ("A" * (BODY_SIZE_LIMIT + 200)))
    head, comments = chunk_body_if_needed(body, [])
    rewritten = rewrite_chunk_manifest_ids(head, ["real-comment-7"])
    decoy = CommentRecord(
        id="stale-comment-1",
        body="<!-- sw-chunk-overflow -->\nSTALE-DECOY-CONTENT",
        created_at="2020-01-01T00:00:00Z",
        markers=["sw-chunk-overflow"],
    )
    real = CommentRecord(
        id="real-comment-7",
        body=comments[0].body,
        created_at="2030-01-01T00:00:00Z",
        markers=["sw-chunk-overflow"],
    )
    reassembled = reassemble_body(rewritten, [decoy, real])
    ok = "STALE-DECOY-CONTENT" not in reassembled and reassembled.rstrip("\n").endswith(
        comments[0].body.replace("<!-- sw-chunk-overflow -->\n", "").rstrip("\n")
    )
    return {
        "name": "reassemble-prefers-real-id-over-decoy",
        "ok": ok,
        "detail": f"decoy-leaked={'STALE-DECOY-CONTENT' in reassembled}",
    }


def _fixture_root(tmp: str, *, project_key: str = "chunk-fixture") -> tuple[Path, dict]:
    root = Path(tmp)
    cfg = {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": project_key,
                "storeLocation": {"mode": "separate-project", "owner": "acme", "repo": "planning"},
            }
        },
        "host": {"provider": "github"},
    }
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return root, cfg


def check_put_rewrites_manifest_with_real_comment_id() -> dict:
    import planning_store as ps
    from issues_lib import FixtureIssuesStore

    with tempfile.TemporaryDirectory() as tmp:
        root, cfg = _fixture_root(tmp)
        backend = ps.get_backend(root, cfg)
        content = "A" * (BODY_SIZE_LIMIT + 5_000)
        backend.put("unit-1", "docs/prds/x/x.md", content)
        store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
        record = next(iter(store._issues.values()))
        match = MARKER_CHUNK_MANIFEST.search(record.body)
        manifest = json.loads(match.group(1)) if match else None
        real_ids = {c.id for c in record.comments}
        manifest_ids = {chunk.get("commentId") for chunk in (manifest or {}).get("chunks", [])}
    ok = bool(manifest_ids) and manifest_ids <= real_ids and not any(
        cid.startswith("chunk-") for cid in manifest_ids
    )
    return {
        "name": "put-rewrites-manifest-with-real-comment-id",
        "ok": ok,
        "detail": f"manifestIds={manifest_ids} realCommentIds={real_ids}",
    }


def check_zero_small_body_no_chunking() -> dict:
    import planning_store as ps
    from issues_lib import FixtureIssuesStore

    with tempfile.TemporaryDirectory() as tmp:
        root, cfg = _fixture_root(tmp, project_key="chunk-zero")
        backend = ps.get_backend(root, cfg)
        backend.put("unit-1", "docs/prds/x/x.md", "# small body\n\ncontent")
        store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
        record = next(iter(store._issues.values()))
    ok = len(record.comments) == 0 and MARKER_CHUNK_MANIFEST.search(record.body) is None
    return {
        "name": "zero-small-body-no-chunking",
        "ok": ok,
        "detail": f"comments={len(record.comments)} hasManifest={MARKER_CHUNK_MANIFEST.search(record.body) is not None}",
    }


def check_repeated_large_updates_never_stale() -> dict:
    """Many: three successive chunked puts of the same unit each reassemble
    byte-exact, with no cross-contamination from an earlier update's now
    orphaned overflow comment (the real-id rewrite makes each manifest name
    only its own current comment)."""
    import planning_store as ps
    from issues_lib import FixtureIssuesStore

    tags = ("ONE", "TWO", "THREE")
    results: dict[str, dict] = {}
    with tempfile.TemporaryDirectory() as tmp:
        root, cfg = _fixture_root(tmp, project_key="chunk-repeat")
        backend = ps.get_backend(root, cfg)
        for tag in tags:
            content = _make_clean_overflow_content(tag, cfg["planning"]["store"]["projectKey"], "prd", "unit-1")
            put_result = backend.put("unit-1", "docs/prds/x/x.md", content)
            got = backend.get("unit-1", "docs/prds/x/x.md")
            other_tags = [t for t in tags if t != tag]
            results[tag] = {
                "putOk": put_result.verdict == "ok",
                "exactMatch": got.content == content,
                "staleLeak": any(t in (got.content or "") for t in other_tags),
            }
        store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
        record = next(iter(store._issues.values()))
        orphaned_comments = len(record.comments)
    ok = (
        all(r["putOk"] and r["exactMatch"] and not r["staleLeak"] for r in results.values())
        and orphaned_comments == len(tags)
    )
    return {
        "name": "repeated-large-updates-never-stale",
        "ok": ok,
        "detail": f"results={results} orphanedComments={orphaned_comments}",
    }


def main() -> int:
    checks = [
        check_chunk_body_if_needed_uses_synthetic_placeholder(),
        check_rewrite_chunk_manifest_ids_replaces_synthetic(),
        check_reassemble_prefers_real_id_over_decoy(),
        check_put_rewrites_manifest_with_real_comment_id(),
        check_zero_small_body_no_chunking(),
        check_repeated_large_updates_never_stale(),
    ]
    failures = [c for c in checks if not c["ok"]]
    verdict = "pass" if not failures else "fail"
    report = {
        "fixture": "planning-chunk-reassembly",
        "rid": "R8",
        "verdict": verdict,
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if verdict == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
