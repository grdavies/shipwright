"""PRD 364 — punctuation wrap narrowing and Markdown-link wrapper exemption."""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

_WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def _load_matcher():
    path = _WORKTREE_ROOT / "scripts/spec-rigor-check.py"
    spec = importlib.util.spec_from_file_location("spec_rigor_check_prd364", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _gap487_probe_rows() -> list[dict]:
    table = _WORKTREE_ROOT / "scripts/test/fixtures/spec-rigor/gap-487-probe-table.md"
    text = table.read_text(encoding="utf-8")
    match = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", text)
    assert match is not None
    payload = json.loads(match.group(1))
    return list(payload["rows"])


def test_prd364_r2_markdown_link_ready_https_not_wrapper_hit() -> None:
    """PRD 364 R2 — ordinary ready/https links are not wrap hits (GAP-487 golden)."""
    m = _load_matcher()
    rows = {row["id"]: row for row in _gap487_probe_rows()}
    ready = rows["markdown-link-ready-https"]["text"]
    assert m.text_has_ambiguity_marker(ready) is False
    assert m.text_has_ambiguity_marker(
        f"Docs at {ready} and also <https://example.com/ready>"
    ) is False
    assert (
        m.text_has_ambiguity_marker(
            "See [ready](https://example.com/fixme:legacy) for citation source."
        )
        is False
    )


def test_prd364_r4_colliding_token_markdown_link_label_still_fails() -> None:
    """PRD 364 R4 — colliding unfinished-work tokens in link labels still fail wraps."""
    m = _load_matcher()
    assert m.text_has_ambiguity_marker("[TODO](https://example.com)") is True
    assert m.text_has_ambiguity_marker("[todo](https://example.com/path)") is True
    assert m.text_has_ambiguity_marker("See [TBD: scope](https://example.com)") is True


def test_prd364_r4_unfinished_authorization_link_label_hard_marker() -> None:
    """PRD 364 R4 — authorization gaps fail hard-marker layers inside link labels."""
    m = _load_matcher()
    assert (
        m.text_has_ambiguity_marker(
            "[TODO implement authorization.](https://example.com/spec)"
        )
        is True
    )
    rows = {row["id"]: row for row in _gap487_probe_rows()}
    unfinished = rows["unfinished-authorization-fail-closed"]["text"]
    assert m.text_has_ambiguity_marker(unfinished) is True


def test_prd364_r5_gap487_probe_table_installed_matcher() -> None:
    """PRD 364 R5 — GAP-487 probe rows drive installedMatcherAmbiguity expectations."""
    m = _load_matcher()
    for row in _gap487_probe_rows():
        if not row.get("installedMatcherAmbiguity"):
            continue
        expect = bool(row["expectAmbiguity"])
        assert m.text_has_ambiguity_marker(row["text"]) is expect, row["id"]
