"""PRD 341 phase 2 — colon/HTML marker family + inspect refuses raw prose fences."""

from __future__ import annotations

import json

from planning_doc_review_transport import (
    build_doc_review_comment_body,
    inspect_review_round_block,
    parse_doc_review_comment,
    payload_hash,
    render_review_round_block,
)


def _payload() -> dict:
    return {"reviewer": "coherence", "findings": [{"id": "f1", "summary": "ok"}]}


def test_colon_html_marker_family_parses_as_typed() -> None:
    envelope = {
        "round": "round-colon",
        "persona": "coherence",
        "idempotencyKey": "round-colon:coherence",
        "payloadHash": payload_hash(_payload()),
        "payload": _payload(),
    }
    body = (
        "<!-- sw:doc-review -->\n"
        f"```json\n{json.dumps(envelope, indent=2, sort_keys=True)}\n```\n"
        "<!-- /sw:doc-review -->\n"
    )
    parsed = parse_doc_review_comment(body)
    assert parsed is not None
    assert parsed["round"] == "round-colon"


def test_inspect_accepts_colon_round_block() -> None:
    block = {"roundId": "r1", "pins": []}
    body = (
        "<!-- sw:doc-review-round -->\n"
        f"```json\n{json.dumps(block, indent=2, sort_keys=True)}\n```\n"
        "<!-- /sw:doc-review-round -->\n"
    )
    parsed, err = inspect_review_round_block(body)
    assert err is None
    assert parsed["roundId"] == "r1"


def test_inspect_refuses_raw_prose_fence() -> None:
    body = "prose\n```sw-doc-review\n{}\n```\n"
    _parsed, err = inspect_review_round_block(body)
    assert err == "raw-prose-fence"


def test_inspect_refuses_duplicate_witness() -> None:
    block = {"roundId": "r1", "pins": []}
    one = render_review_round_block(block)
    _parsed, err = inspect_review_round_block(one + "\n" + one)
    assert err == "duplicate-round-block"


def test_hyphen_form_still_parses() -> None:
    body = build_doc_review_comment_body(
        round_id="round-hyphen",
        persona="coherence",
        payload=_payload(),
    )
    parsed = parse_doc_review_comment(body)
    assert parsed is not None
    assert parsed["round"] == "round-hyphen"
