"""PRD 066 phase 7 — Linear Public Markdown fidelity suite (R15)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_linear_canonical as plc
from planning_canonical import canonical_hash

FIXTURE_DIR = scripts / "tests" / "fixtures" / "canonical" / "linear"
GOLDEN_IDS = (
    "mention-url-roundtrip",
    "collapsible",
    "headers",
    "gfm-table",
    "checkboxes",
    "fenced-code",
)


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("fixture_id", GOLDEN_IDS)
def test_r15_golden_public_markdown_round_trip(fixture_id: str) -> None:
    """R15 — golden fixtures round-trip via Public Markdown and match expected hash."""
    data = _load(fixture_id)
    assert data.get("contract") == plc.SUPPORTED_CONTRACT
    submit = plc.simulate_public_markdown_round_trip(data["submitMarkdown"])
    refetch = plc.linear_markdown_canonical(data["refetchedMarkdown"])
    assert submit == refetch == data["expectedCanonicalBody"]
    result = plc.normalize_fixture(FIXTURE_DIR / f"{fixture_id}.json")
    assert result["verdict"] == "ok"
    assert result["contract"] == "public-markdown"
    assert result["body"] == data["expectedCanonicalBody"]
    assert result["hash"] == data["expectedHash"]
    assert result["hash"] == canonical_hash(plc.snapshot_from_fixture(data))


def test_r15_mention_link_normalizes_to_bare_url() -> None:
    """R15 — [@user](url) mention links canonicalize to bare Linear URLs."""
    md = "Ping [@alice](https://linear.app/acme/profiles/alice) please."
    out = plc.linear_markdown_canonical(md)
    assert "[@alice]" not in out
    assert "https://linear.app/acme/profiles/alice" in out


def test_r15_collapsible_whitespace_normalized() -> None:
    """R15 — +++ collapsible blocks normalize to a stable shape."""
    messy = "+++  Notes  \n\n  body line  \n\n+++\n"
    out = plc.linear_markdown_canonical(messy)
    assert out.startswith("+++ Notes")
    assert out.endswith("+++")
    assert "body line" in out


def test_r15_content_data_not_adapter_complete() -> None:
    """R15 — contentData/contentState are not a supported adapter contract."""
    payload = {
        "title": "x",
        "contentData": {"type": "doc", "content": []},
        "submitMarkdown": "# hi\n",
    }
    with pytest.raises(plc.LinearCanonicalContractError) as exc:
        plc.assert_public_markdown_contract(payload)
    assert exc.value.code == "unsupported-internal-content-contract"

    with pytest.raises(plc.LinearCanonicalContractError):
        plc.snapshot_from_fixture(payload)

    assert plc.is_adapter_complete_field("description") is True
    assert plc.is_adapter_complete_field("content") is True
    assert plc.is_adapter_complete_field("contentData") is False
    assert plc.is_adapter_complete_field("contentState") is False


def test_r15_content_state_not_adapter_complete() -> None:
    """R15 — Yjs contentState is not adapter-complete."""
    with pytest.raises(plc.LinearCanonicalContractError) as exc:
        plc.assert_public_markdown_contract({"contentState": "yjs-blob"})
    assert "contentState" in exc.value.message


def test_r15_html_details_rejected() -> None:
    """R15 — non-round-trippable HTML details rejected; use +++ collapsibles."""
    with pytest.raises(plc.LinearCanonicalDegradeError) as exc:
        plc.linear_markdown_canonical("<details><summary>x</summary>y</details>")
    assert exc.value.code == "html-details-not-public-markdown"


def test_r15_cli_normalize_fixture() -> None:
    """R15 — CLI normalize emits ok + hash for a golden fixture."""
    code = plc.main(["normalize", "--fixture", str(FIXTURE_DIR / "headers.json")])
    assert code == 0


def test_r15_cli_rejects_internal_contract(tmp_path: Path) -> None:
    """R15 — CLI fails closed when fixture carries contentData."""
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "title": "bad",
                "contentData": {"type": "doc"},
                "submitMarkdown": "hi",
            }
        ),
        encoding="utf-8",
    )
    assert plc.main(["normalize", "--fixture", str(path)]) == 2
