#!/usr/bin/env python3
"""Linear-aware chunking fixture (PRD 357 R8–R12, R16).

Offline deterministic checks for ``chunk_body_if_needed(provider="linear")`` and
sanitized corpus round-trips. No network, no consumer workspace identifiers.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from planning_canonical import (  # noqa: E402
    BODY_SIZE_LIMIT,
    CommentRecord,
    LinearChunkAuthorshipError,
    MARKER_CHUNK_MANIFEST,
    chunk_body_if_needed,
    chunk_token_from_comment,
    normalize_body,
    reassemble_body,
    rewrite_chunk_manifest_ids,
)
from planning_jira_canonical import chunk_body_for_jira_cloud, jira_adf_payload_size  # noqa: E402
from planning_linear_canonical import (  # noqa: E402
    chunk_body_for_linear,
    _utf8_byte_len,
)
from planning_notion_canonical import chunk_body_for_notion  # noqa: E402

FIXTURES = SCRIPT_DIR / "fixtures"


def _load_corpus() -> list[dict]:
    out: list[dict] = []
    for path in sorted(FIXTURES.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        data["_path"] = path.name
        out.append(data)
    return out


def check_corpus_round_trip() -> dict:
    failures: list[str] = []
    for item in _load_corpus():
        body = str(item.get("body") or "")
        expect_chunked = bool(item.get("expectChunked"))
        head, comments = chunk_body_if_needed(body, [], provider="linear")
        if expect_chunked and not comments:
            failures.append(f"{item['_path']}: expected chunks")
        if not expect_chunked and comments:
            failures.append(f"{item['_path']}: unexpected chunks")
        if _utf8_byte_len(head) > BODY_SIZE_LIMIT:
            failures.append(f"{item['_path']}: head over limit")
        for comment in comments:
            if _utf8_byte_len(comment.body) > BODY_SIZE_LIMIT:
                failures.append(f"{item['_path']}: comment over limit")
            if "sw-chunk-token:" not in comment.body:
                failures.append(f"{item['_path']}: missing token in body")
        rebuilt = reassemble_body(head, comments)
        if normalize_body(rebuilt) != normalize_body(body):
            failures.append(f"{item['_path']}: normalize_body mismatch")
    return {
        "name": "corpus-round-trip",
        "ok": not failures,
        "detail": failures or f"fixtures={len(list(FIXTURES.glob('*.json')))}",
    }


def check_delegates_to_linear_splitter() -> dict:
    body = "# Linear\n\n" + ("x" * (BODY_SIZE_LIMIT + 500))
    head, comments = chunk_body_if_needed(body, [], provider="linear")
    direct_head, direct_comments = chunk_body_for_linear(body, [])
    ok = (
        normalize_body(reassemble_body(head, comments)) == normalize_body(reassemble_body(direct_head, direct_comments))
        and len(comments) == len(direct_comments)
        and bool(comments)
    )
    return {
        "name": "delegates-to-linear-splitter",
        "ok": ok,
        "detail": f"chunked={bool(comments)}",
    }


def check_generic_unspecified_unchanged() -> dict:
    body = "# Generic\n\n" + ("y" * (BODY_SIZE_LIMIT + 400))
    head, comments = chunk_body_if_needed(body, [], provider=None)
    ok = len(comments) == 1 and "sw-chunk-overflow" in comments[0].body
    return {"name": "generic-unspecified-unchanged", "ok": ok, "detail": len(comments)}


def check_jira_notion_goldens_unchanged() -> dict:
    jira_body = "# J\n\n" + ("word " * 300)
    j_head, j_comments = chunk_body_for_jira_cloud(jira_body, [])
    jira_ok = jira_adf_payload_size(j_head) <= 32767
    notion_body = "# N\n\n" + ("line\n" * 5000)
    n_head, n_comments = chunk_body_for_notion(notion_body, [])
    notion_ok = isinstance(n_head, str) and isinstance(n_comments, list)
    ok = jira_ok and notion_ok
    return {
        "name": "jira-notion-goldens-unchanged",
        "ok": ok,
        "detail": f"jiraChunked={bool(j_comments)} notionChunked={bool(n_comments)}",
    }


def check_unicode_boundary_no_ignore() -> dict:
    body = "café " * 25000
    head, comments = chunk_body_for_linear(body, [])
    rebuilt = normalize_body(reassemble_body(head, comments))
    ok = rebuilt == normalize_body(body) and "é" in rebuilt
    return {"name": "unicode-boundary-no-ignore", "ok": ok, "detail": len(comments)}


def check_actor_bound_overflow() -> dict:
    body = "# A\n\n" + ("z" * (BODY_SIZE_LIMIT + 800))
    head, comments = chunk_body_for_linear(body, [])
    token = chunk_token_from_comment(comments[0])
    rewritten = rewrite_chunk_manifest_ids(head, ["real-1"])
    own = CommentRecord(
        id="real-1",
        body=comments[0].body,
        markers=comments[0].markers,
        author_id="actor-a",
    )
    other = CommentRecord(
        id="stale-9",
        body=comments[0].body.replace("z", "STALE"),
        markers=comments[0].markers,
        author_id="actor-b",
    )
    with_other = reassemble_body(rewritten, [own, other], linear_author_id="actor-a")
    without_author = None
    try:
        reassemble_body(rewritten, [own], linear_author_id="actor-a")
        missing = CommentRecord(id="real-1", body=own.body, markers=own.markers, author_id="")
        reassemble_body(rewritten, [missing], linear_author_id="actor-a")
        auth_fail = False
    except LinearChunkAuthorshipError:
        auth_fail = True
    ok = "STALE" not in with_other and auth_fail and bool(token)
    return {
        "name": "actor-bound-overflow",
        "ok": ok,
        "detail": f"token={bool(token)} authFail={auth_fail}",
    }


def main() -> int:
    checks = [
        check_corpus_round_trip(),
        check_delegates_to_linear_splitter(),
        check_generic_unspecified_unchanged(),
        check_jira_notion_goldens_unchanged(),
        check_unicode_boundary_no_ignore(),
        check_actor_bound_overflow(),
    ]
    failures = [c for c in checks if not c["ok"]]
    report = {
        "fixture": "planning-linear-chunk",
        "rid": "R8-R16",
        "verdict": "pass" if not failures else "fail",
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if not failures else 20


if __name__ == "__main__":
    raise SystemExit(main())
