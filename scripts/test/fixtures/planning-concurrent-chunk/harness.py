#!/usr/bin/env python3
"""Concurrent chunked-put integrity fixture (PRD 057 R27).

Proves, fully offline and deterministically (fixture issues store, no
network, manual step-interleaving rather than real threads so the exact race
window is reproducible):

1. **Zero: a single writer's chunked put is unaffected** — the R27
   write-token machinery is invisible to the ordinary single-writer path;
   `put`/`get` round-trip byte-exact as before.
2. **The unsafe read window is real** — with the write-token stripped from a
   mid-race manifest (simulating pre-R27 behavior), reassembling that exact
   same body+comments state DOES splice writer A's overflow content onto
   writer B's head — a hybrid of two writers.
3. **Token-scoped reassembly never produces that hybrid** — reassembling the
   SAME mid-race state with the write-token intact returns writer B's head
   alone (incomplete, since B hasn't posted its own comments yet at that
   instant) — never a hybrid of A's and B's content.
4. **Interleaved concurrent large puts converge to exactly one writer's
   body** — after both writers finish, `reassemble_body` returns writer B's
   (the last writer's) full content byte-exact; writer A's now-orphaned
   overflow comments are never referenced by the final manifest.
5. **`planning-doctor.py` sees no cardinality mismatch on that clean final
   state** — the converged manifest's declared ids all resolve to real
   comments.
6. **`planning-doctor.py` flags a cardinality mismatch when a writer is
   interrupted before its rewrite** — same race, but the "winning" writer's
   final manifest rewrite never happens (crash simulation); the doctor check
   fires.
7. **The full `IssueStoreBackend.put` path rejects a genuinely stale-etag
   racer outright** — a writer that read the issue before another writer's
   completed put gets a clean revision-conflict failure at the very first
   write, before posting a single comment; the winning writer's content is
   completely untouched.

No network, no live issue store required (`SW_ISSUES_FIXTURE=1`).

ZOMBIES: Zero (single writer) · Many (two interleaved writers) · Boundaries
(the exact read window between head-write and manifest rewrite)
· Exceptions (writer interrupted before rewrite; stale-etag racer rejected)
· State (orphaned comments never referenced) · Interfaces (doctor
cardinality check).
"""
from __future__ import annotations

import dataclasses
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from types import ModuleType

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

os.environ.setdefault("SW_ISSUES_FIXTURE", "1")

from planning_canonical import (  # noqa: E402
    BODY_SIZE_LIMIT,
    MARKER_CHUNK_MANIFEST,
    chunk_body_if_needed,
    compose_issue_body,
    reassemble_body,
    rewrite_chunk_manifest_ids,
    strip_markers_and_edges,
)


def _load_module(rel_path: str, name: str) -> ModuleType:
    path = ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prefix_byte_len(project_key: str, artifact_type: str, unit_id: str) -> int:
    composed = compose_issue_body(project_key, artifact_type, unit_id, "X")
    idx = composed.index("X")
    return len(composed[:idx].encode("utf-8"))


def _clean_overflow_content(tag: str, project_key: str, artifact_type: str, unit_id: str) -> str:
    """Content sized so the chunk cut lands on a paragraph break, giving a
    byte-exact reassembly round trip (mirrors planning-chunk-reassembly)."""
    prefix = f"# Title {tag}\n\n"
    target_len = BODY_SIZE_LIMIT - _prefix_byte_len(project_key, artifact_type, unit_id)
    filler_len = target_len - len(prefix) - 2
    head = prefix + ("A" * filler_len) + "\n\n"
    tail = f"Paragraph {tag} tail content here\n\nEND-{tag}"
    return head + tail


def _fixture_root(tmp: str, *, project_key: str) -> tuple[Path, dict]:
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


def _strip_write_token(body: str) -> str:
    """Simulate pre-R27 behavior: same manifest, no writeToken."""
    match = MARKER_CHUNK_MANIFEST.search(body)
    manifest = json.loads(match.group(1))
    manifest.pop("writeToken", None)
    new_marker = f"<!-- sw-chunk-manifest: {json.dumps(manifest, sort_keys=True, ensure_ascii=False)} -->"
    return body[: match.start()] + new_marker + body[match.end() :]


def check_zero_single_writer_unaffected() -> dict:
    import planning_store as ps

    with tempfile.TemporaryDirectory() as tmp:
        root, cfg = _fixture_root(tmp, project_key="concurrent-chunk-zero")
        backend = ps.get_backend(root, cfg)
        content = _clean_overflow_content("SOLO", cfg["planning"]["store"]["projectKey"], "prd", "unit-1")
        put_result = backend.put("unit-1", "docs/prds/x/x.md", content)
        got = backend.get("unit-1", "docs/prds/x/x.md")
    ok = put_result.verdict == "ok" and got.content == content
    return {
        "name": "zero-single-writer-unaffected",
        "ok": ok,
        "detail": f"putOk={put_result.verdict == 'ok'} exactMatch={got.content == content}",
    }


def _race_setup(root: Path, project_key: str, unit_id: str = "unit-1"):
    """Manually drive two writers' low-level calls into the exact interleaving
    R27 protects against: writer A's overflow comments are posted, then
    writer B's head write lands BEFORE writer A's manifest rewrite would have
    happened (this fixture makes A never rewrite -- B "wins" the head race)."""
    from issues_lib import IssuesClient

    client = IssuesClient(root, "github-issues")
    base = client.issue_create(
        title="[proj] prd:unit-1",
        body=compose_issue_body(project_key, "prd", unit_id, "seed"),
        labels=[],
        project_key=project_key,
        artifact_type="prd",
        unit_id=unit_id,
    )

    content_a = _clean_overflow_content("WRITERA", project_key, "prd", unit_id)
    content_b = _clean_overflow_content("WRITERB", project_key, "prd", unit_id)
    body_a, comments_a = chunk_body_if_needed(
        compose_issue_body(project_key, "prd", unit_id, content_a), [], provider=None
    )
    body_b, comments_b = chunk_body_if_needed(
        compose_issue_body(project_key, "prd", unit_id, content_b), [], provider=None
    )

    # Writer A: head write, then posts its overflow comment(s).
    rec_a = client.issue_update(base.id, body=body_a, if_match=base.etag)
    posted_a = [client.issue_comment(base.id, c.body, markers=c.markers).id for c in comments_a]
    rec_a2 = client.issue_get(base.id)

    # Interleave: writer B's head write lands now, using the freshest etag --
    # BEFORE writer A ever gets to rewrite its manifest with real ids.
    client.issue_update(base.id, body=body_b, if_match=rec_a2.etag)
    mid_record = client.issue_get(base.id)

    return {
        "client": client,
        "issue_id": base.id,
        "content_a": content_a,
        "content_b": content_b,
        "body_b": body_b,
        "comments_b": comments_b,
        "posted_a": posted_a,
        "mid_record": mid_record,
    }


def check_unsafe_window_would_hybridize_without_token() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root, cfg = _fixture_root(tmp, project_key="concurrent-chunk-unsafe")
        state = _race_setup(root, cfg["planning"]["store"]["projectKey"])
        legacy_body = _strip_write_token(state["mid_record"].body)
        legacy_reassembled = reassemble_body(legacy_body, state["mid_record"].comments)
    hybrid_leaked = "WRITERA" in legacy_reassembled or "END-WRITERA" in legacy_reassembled
    ok = hybrid_leaked
    return {
        "name": "unsafe-window-would-hybridize-without-token",
        "ok": ok,
        "detail": f"legacyReassemblyLeakedWriterA={hybrid_leaked}",
    }


def check_token_scoped_reassembly_never_hybridizes() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root, cfg = _fixture_root(tmp, project_key="concurrent-chunk-safe")
        state = _race_setup(root, cfg["planning"]["store"]["projectKey"])
        mid_reassembled = reassemble_body(state["mid_record"].body, state["mid_record"].comments)
    no_writer_a_leak = "WRITERA" not in mid_reassembled and "END-WRITERA" not in mid_reassembled
    no_writer_b_tail = "END-WRITERB" not in mid_reassembled  # B hasn't posted its own chunk yet
    ok = no_writer_a_leak and no_writer_b_tail
    return {
        "name": "token-scoped-reassembly-never-hybridizes",
        "ok": ok,
        "detail": f"noWriterALeak={no_writer_a_leak} noPrematureWriterBTail={no_writer_b_tail}",
    }


def check_interleaved_puts_converge_to_last_writer_exact() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root, cfg = _fixture_root(tmp, project_key="concurrent-chunk-converge")
        state = _race_setup(root, cfg["planning"]["store"]["projectKey"])
        client = state["client"]
        issue_id = state["issue_id"]

        # Writer B finishes: posts its own comments, rewrites the manifest
        # with real ids (last writer to complete wins the head).
        posted_b = [
            client.issue_comment(issue_id, c.body, markers=c.markers).id for c in state["comments_b"]
        ]
        rec_b2 = client.issue_get(issue_id)
        rewritten_b = rewrite_chunk_manifest_ids(state["body_b"], posted_b)
        client.issue_update(issue_id, body=rewritten_b, if_match=rec_b2.etag)

        final_record = client.issue_get(issue_id)
        final_reassembled = strip_markers_and_edges(reassemble_body(final_record.body, final_record.comments))
        manifest = json.loads(MARKER_CHUNK_MANIFEST.search(final_record.body).group(1))
        declared_ids = {c.get("commentId") for c in manifest.get("chunks", [])}
    exact_match = final_reassembled == state["content_b"]
    no_hybrid = "WRITERA" not in final_reassembled
    orphans_not_referenced = declared_ids.isdisjoint(set(state["posted_a"])) and declared_ids == set(posted_b)
    ok = exact_match and no_hybrid and orphans_not_referenced
    return {
        "name": "interleaved-puts-converge-to-last-writer-exact",
        "ok": ok,
        "detail": (
            f"exactMatch={exact_match} noHybrid={no_hybrid} "
            f"orphansNotReferenced={orphans_not_referenced} declaredIds={declared_ids} "
            f"orphanedWriterAIds={state['posted_a']}"
        ),
    }


def check_doctor_no_mismatch_on_clean_converged_state() -> dict:
    doctor = _load_module("scripts/planning-doctor.py", "_concurrent_chunk_doctor_1")
    with tempfile.TemporaryDirectory() as tmp:
        root, cfg = _fixture_root(tmp, project_key="concurrent-chunk-doctor-clean")
        state = _race_setup(root, cfg["planning"]["store"]["projectKey"])
        client = state["client"]
        issue_id = state["issue_id"]
        posted_b = [
            client.issue_comment(issue_id, c.body, markers=c.markers).id for c in state["comments_b"]
        ]
        rec_b2 = client.issue_get(issue_id)
        rewritten_b = rewrite_chunk_manifest_ids(state["body_b"], posted_b)
        client.issue_update(issue_id, body=rewritten_b, if_match=rec_b2.etag)
        finding = doctor.chunk_cardinality_finding(root)
    ok = finding is None
    return {"name": "doctor-no-mismatch-on-clean-converged-state", "ok": ok, "detail": finding}


def check_doctor_flags_mismatch_when_winner_never_rewrites() -> dict:
    doctor = _load_module("scripts/planning-doctor.py", "_concurrent_chunk_doctor_2")
    with tempfile.TemporaryDirectory() as tmp:
        root, cfg = _fixture_root(tmp, project_key="concurrent-chunk-doctor-mismatch")
        project_key = cfg["planning"]["store"]["projectKey"]
        state = _race_setup(root, project_key)
        # Writer B posts its comments but is interrupted before rewriting the
        # manifest -- the head still names B's synthetic placeholder chunk
        # id, which can never resolve to a real comment.
        client = state["client"]
        for comment in state["comments_b"]:
            client.issue_comment(state["issue_id"], comment.body, markers=comment.markers)
        finding = doctor.chunk_cardinality_finding(root)
    ok = (
        finding is not None
        and finding.get("check") == "chunk-cardinality-mismatch"
        and any(u.get("unitId") == "unit-1" for u in finding.get("units") or [])
    )
    return {"name": "doctor-flags-mismatch-when-winner-never-rewrites", "ok": ok, "detail": finding}


def check_stale_etag_racer_rejected_full_put_path() -> dict:
    import planning_store as ps
    from issues_lib import FixtureIssuesStore

    with tempfile.TemporaryDirectory() as tmp:
        root, cfg = _fixture_root(tmp, project_key="concurrent-chunk-fullpath")
        project_key = cfg["planning"]["store"]["projectKey"]
        backend_a = ps.get_backend(root, cfg)
        backend_a.put("unit-1", "docs/prds/x/x.md", "# seed\n\ninitial content")

        store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
        issue_id = next(iter(store._issues.keys()))
        stale_etag = store._issues[issue_id].etag

        content_a = _clean_overflow_content("FULLPATHA", project_key, "prd", "unit-1")
        result_a = backend_a.put("unit-1", "docs/prds/x/x.md", content_a)

        backend_b = ps.get_backend(root, cfg)
        real_lookup = backend_b._lookup_record

        def stale_lookup(unit_id: str, body_path: str):
            record = real_lookup(unit_id, body_path)
            return dataclasses.replace(record, etag=stale_etag)

        backend_b._lookup_record = stale_lookup
        content_b = _clean_overflow_content("FULLPATHB", project_key, "prd", "unit-1")
        rejected = False
        try:
            backend_b.put("unit-1", "docs/prds/x/x.md", content_b)
        except SystemExit:
            rejected = True

        got = backend_a.get("unit-1", "docs/prds/x/x.md")
        store_final = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
        record_final = store_final._issues[issue_id]
    ok = (
        result_a.verdict == "ok"
        and rejected
        and got.content == content_a
        and "FULLPATHB" not in record_final.body
        and not any("FULLPATHB" in c.body for c in record_final.comments)
    )
    return {
        "name": "stale-etag-racer-rejected-full-put-path",
        "ok": ok,
        "detail": (
            f"aOk={result_a.verdict == 'ok'} bRejected={rejected} aUntouched={got.content == content_a} "
            f"noWriterBLeak={'FULLPATHB' not in record_final.body}"
        ),
    }


def main() -> int:
    checks = [
        check_zero_single_writer_unaffected(),
        check_unsafe_window_would_hybridize_without_token(),
        check_token_scoped_reassembly_never_hybridizes(),
        check_interleaved_puts_converge_to_last_writer_exact(),
        check_doctor_no_mismatch_on_clean_converged_state(),
        check_doctor_flags_mismatch_when_winner_never_rewrites(),
        check_stale_etag_racer_rejected_full_put_path(),
    ]
    failures = [c for c in checks if not c["ok"]]
    verdict = "pass" if not failures else "fail"
    report = {
        "fixture": "planning-concurrent-chunk",
        "rid": "R27",
        "verdict": verdict,
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if verdict == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
