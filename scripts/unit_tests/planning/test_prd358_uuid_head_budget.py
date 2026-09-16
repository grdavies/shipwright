"""PRD 358 R2 / D4 — Linear UUID head budget after manifest rewrite."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from planning_canonical import BODY_SIZE_LIMIT, rewrite_chunk_manifest_ids
from planning_linear_canonical import (
    LINEAR_OVERFLOW_COMMENT_ID_UTF8_LEN,
    LinearChunkHeadBudgetError,
    _utf8_byte_len,
    _worst_case_linear_overflow_comment_ids,
    chunk_body_for_linear,
)

FIXTURES = scripts / "test/fixtures/planning-linear-uuid-head-budget"


def _body_from_fixture(name: str) -> tuple[dict, str]:
    path = FIXTURES / f"{name}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    prefix = str(data.get("prefix") or "")
    char = str(data.get("paddingChar") or "x")
    length = int(data["paddingLength"])
    return data, prefix + (char * length)


class TestPrd358UuidHeadBudget:
    def test_near_limit_fixture_head_within_limit_after_uuid_rewrite(self) -> None:
        _meta, body = _body_from_fixture("near-limit-after-rewrite")
        assert _utf8_byte_len(body) > BODY_SIZE_LIMIT
        head, comments = chunk_body_for_linear(body, [])
        posted = _worst_case_linear_overflow_comment_ids(len(comments))
        assert len(posted) == len(comments)
        assert all(len(cid.encode("utf-8")) == LINEAR_OVERFLOW_COMMENT_ID_UTF8_LEN for cid in posted)
        rewritten = rewrite_chunk_manifest_ids(head, posted)
        assert _utf8_byte_len(rewritten) <= BODY_SIZE_LIMIT

    def test_over_budget_first_split_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        data, body = _body_from_fixture("over-budget-first-split")
        limit = int(data["linearChunkLimitBytes"])
        import planning_linear_canonical as llc

        monkeypatch.setattr(llc, "_LINEAR_CHUNK_LIMIT", limit)
        with pytest.raises(LinearChunkHeadBudgetError, match="UUID manifest rewrite"):
            chunk_body_for_linear(body, [])
