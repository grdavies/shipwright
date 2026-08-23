"""PRD 327 R3 — Notion block-children canonicalization fixtures and round-trip."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from planning_canonical import canonical_form, canonical_hash
from planning_notion_canonical import (
    NotionCanonicalDegradeError,
    blocks_to_markdown,
    markdown_to_blocks,
    notion_markdown_canonical,
    normalize_fixture,
    snapshot_from_fixture,
)

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests/fixtures/canonical/notion"


@pytest.mark.parametrize(
    "fixture_name",
    [
        "headers",
        "checkboxes",
        "gfm-table",
        "fenced-code",
        "collapsible",
        "mention-url-roundtrip",
        "nested-lists",
    ],
)
def test_fixture_round_trip_byte_idempotent(fixture_name: str) -> None:
    path = FIXTURE_DIR / f"{fixture_name}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    markdown = data["markdown"]
    once = blocks_to_markdown(markdown_to_blocks(markdown))
    twice = blocks_to_markdown(markdown_to_blocks(once))
    assert once == twice
    assert once == notion_markdown_canonical(markdown)


@pytest.mark.parametrize(
    "fixture_name",
    [
        "headers",
        "checkboxes",
        "gfm-table",
        "fenced-code",
        "collapsible",
        "mention-url-roundtrip",
        "nested-lists",
    ],
)
def test_fixture_hash_stable(fixture_name: str) -> None:
    path = FIXTURE_DIR / f"{fixture_name}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    snap = snapshot_from_fixture(data)
    assert canonical_form(snap) == data["canonical"]
    assert canonical_hash(snap) == data["hash"]
    again = normalize_fixture(path)
    assert again["hash"] == data["hash"]


def test_unsupported_block_degrades() -> None:
    path = FIXTURE_DIR / "unsupported-block.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    with pytest.raises(NotionCanonicalDegradeError) as exc:
        blocks_to_markdown(data["blocks"])
    assert exc.value.code == data["expectedError"]
