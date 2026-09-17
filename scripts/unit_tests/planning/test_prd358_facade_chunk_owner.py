"""PRD 358 R1 — facade owns Linear chunking; adapter skip-on-manifest."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_linear_client as plc
from planning_canonical import BODY_SIZE_LIMIT, load_chunk_manifest, rewrite_chunk_manifest_ids
from planning_linear_canonical import _utf8_byte_len, chunk_body_for_linear

FACADE_DOUBLE_CHUNK_REPRO = "facade-double-chunk-repro-2.19.0"
_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "prd358_facade_double_chunk_repro.json"


def _load_facade_double_chunk_repro() -> dict[str, Any]:
    data = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert data["name"] == FACADE_DOUBLE_CHUNK_REPRO
    return data


def _caller_body_from_fixture(data: dict[str, Any]) -> str:
    return (
        str(data["markers"])
        + str(data["title"])
        + str(data["repeatLine"]) * int(data["repeatCount"])
    )


def test_facade_double_chunk_repro_skip_after_uuid_rewrite() -> None:
    """Live 2.19.0 double-chunk repro: adapter must not split a manifested head again."""
    fixture = _load_facade_double_chunk_repro()
    body = _caller_body_from_fixture(fixture)
    head, extras = chunk_body_for_linear(body, [])
    assert len(extras) == int(fixture["overflowChunkCount"])
    posted = [str(cid) for cid in fixture["postedCommentIds"]]
    rewritten = rewrite_chunk_manifest_ids(head, posted)
    assert load_chunk_manifest(rewritten) is not None
    assert _utf8_byte_len(rewritten) == int(fixture["headBytesAfterRewrite"])
    assert _utf8_byte_len(rewritten) <= int(fixture["linearLimitBytes"])

    head_after, extras_after = plc.prepare_body_with_overflow(rewritten, [])
    assert extras_after == []
    assert head_after == rewritten


def test_manifested_over_limit_head_fails_second_split_without_skip() -> None:
    """When UUID rewrite pushes the head over the Linear pin, re-chunking is invalid."""
    manifest = {
        "version": 1,
        "chunks": [{"index": i, "commentId": str(uuid.uuid4())} for i in range(3)],
        "writeToken": uuid.uuid4().hex[:12],
    }
    marker = f"<!-- sw-chunk-manifest: {json.dumps(manifest, sort_keys=True)} -->"
    overshoot = BODY_SIZE_LIMIT + 128
    head = ("x" * overshoot) + "\n" + marker
    assert load_chunk_manifest(head) is not None
    assert _utf8_byte_len(head) > BODY_SIZE_LIMIT

    skipped_head, skipped_extras = plc.prepare_body_with_overflow(head, [])
    assert skipped_extras == []
    assert skipped_head == head

    _second_head, second_extras = chunk_body_for_linear(head, [])
    assert second_extras, "linear chunker would attempt a second split on manifested text"


def test_prepare_body_still_chunks_unmanifested_oversized_body() -> None:
    """Skip-on-manifest is a hard skip only when a manifest is already present."""
    body = "y" * (BODY_SIZE_LIMIT + 4096)
    assert load_chunk_manifest(body) is None
    head, extras = plc.prepare_body_with_overflow(body, [])
    assert extras
    assert "sw-chunk-manifest" in head
