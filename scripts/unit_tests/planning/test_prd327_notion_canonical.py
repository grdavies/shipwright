"""PRD 327 R3 — Notion block-children canonicalization fixtures and round-trip."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from planning_canonical import canonical_form, canonical_hash, reassemble_body
from planning_notion_canonical import (
    NotionCanonicalDegradeError,
    NOTION_BLOCK_APPEND_LIMIT,
    NOTION_RICH_TEXT_CHAR_LIMIT,
    blocks_to_markdown,
    chunk_body_for_notion,
    markdown_to_blocks,
    notion_markdown_canonical,
    normalize_fixture,
    paginate_blocks,
    snapshot_from_fixture,
    split_rich_text_chunks,
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


def test_comment_chunk_overflow_and_block_pagination() -> None:
    long_line = "x" * 2500
    body = long_line + "\n\nSecond paragraph."
    head, extra = chunk_body_for_notion(body, [])
    assert "<!-- sw-chunk-overflow -->" in extra[0].body
    assert "sw-chunk-manifest" in head
    reassembled = reassemble_body(head, extra)
    assert len(reassembled) > NOTION_RICH_TEXT_CHAR_LIMIT
    assert "Second paragraph." in reassembled

    many_blocks = markdown_to_blocks("\n".join(f"- item {i}" for i in range(150)))
    batches = paginate_blocks(many_blocks)
    assert len(batches) == 2
    assert len(batches[0]) == NOTION_BLOCK_APPEND_LIMIT

    chunks = split_rich_text_chunks("a" * 5000)
    assert all(len(chunk) <= 2000 for chunk in chunks)
    assert "".join(chunks) == "a" * 5000


def test_comment_mutation_degraded_fixture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from planning_notion_client import NotionIssuesClient, comment_mutation_capability

    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path / "repo"
    root.mkdir()
    (root / "workflow.config.json").write_text(
        '{"planning":{"store":{"backend":"issue-store","projectKey":"acme","issuesProvider":"notion","issues":{"notionDatabaseId":"db-fixture"}}}}\n',
        encoding="utf-8",
    )
    from issues_lib import FixtureIssuesStore

    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
    client = NotionIssuesClient(root, fixture_store=store)
    created = client.create(
        title="[acme] prd:327-amend",
        body="Amend me.",
        labels=["sw:prd"],
        project_key="acme",
        artifact_type="prd",
        unit_id="prd-327-amend",
    )
    comment = client.add_comment(created.id, "Original.", markers=[])
    amended = client.amend_comment(created.id, comment.id, "Amended body.")
    assert "sw-comment-amendment" in amended.markers
    cap = comment_mutation_capability()
    assert cap["capability"] == "degraded"
