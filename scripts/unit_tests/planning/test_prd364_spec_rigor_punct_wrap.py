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


def _prd_skeleton(*req_lines: str, frontmatter_extra: str = "", decision_log: str = "") -> str:
    reqs = "\n".join(f"- **R{n}** {body}" for n, body in enumerate(req_lines, start=1))
    fm_extra = frontmatter_extra.rstrip() + "\n" if frontmatter_extra.strip() else ""
    log_body = decision_log if decision_log else ""
    return (
        "---\n"
        "frozen: false\n"
        f"{fm_extra}"
        "---\n"
        "# PRD 364 phase-4 fixture\n\n"
        "## Overview\n\nFixture.\n\n"
        "## Goals\n\n- Validate taxonomy\n\n"
        "## Non-Goals\n\n- None\n\n"
        "## Requirements\n\n"
        f"{reqs}\n\n"
        "## Technical Requirements\n\nNone\n\n"
        "## Security & Compliance\n\nNone\n\n"
        "## Testing Strategy\n\nUnit\n\n"
        "## Rollout Plan\n\nShip\n\n"
        "## Decision Log\n\n"
        f"{log_body}\n"
        "## Open Questions\n\n(none)\n"
    )


def _run_prd(body: str) -> tuple[int, dict]:
    fix = _WORKTREE_ROOT / "scripts/test/fixtures/spec-rigor/_tmp-prd364-phase4.md"
    fix.parent.mkdir(parents=True, exist_ok=True)
    fix.write_text(body, encoding="utf-8")
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(_WORKTREE_ROOT / "scripts/spec-rigor-check.py"),
                "--root",
                str(_WORKTREE_ROOT),
                "--artifact",
                "prd",
                "--path",
                str(fix),
                "--tier",
                "standard",
            ],
            cwd=str(_WORKTREE_ROOT),
            capture_output=True,
            text=True,
        )
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            data = {"verdict": "fail", "raw": proc.stdout, "stderr": proc.stderr}
        return proc.returncode, data
    finally:
        try:
            fix.unlink(missing_ok=True)
        except OSError:
            pass


def test_prd364_r3_title_case_and_slash_taxonomy_still_pass() -> None:
    """PRD 364 R3 — 361 Title-case + lowercase slash-taxonomy and critical-states sentence."""
    m = _load_matcher()
    rows = {row["id"]: row for row in _gap487_probe_rows()}
    for row_id in ("slash-taxonomy-lowercase-pass", "named-states-label-taxonomy"):
        assert m.text_has_ambiguity_marker(rows[row_id]["text"]) is False, row_id
    body = _prd_skeleton("Workflow enters Todo when criteria met", "Tags use idea/todo/note taxonomy")
    code, data = _run_prd(body)
    assert code == 0
    assert data.get("verdict") == "pass"


def test_prd364_r9_todo_wraps_fail_pending_colon_passes() -> None:
    """PRD 364 R9 — colliding Todo wraps fail; non-colliding Title-case Pending colon passes."""
    m = _load_matcher()
    assert m.text_has_ambiguity_marker("State Todo: must be explicit") is True
    assert m.text_has_ambiguity_marker("Label [Todo] in UI copy") is True
    assert m.text_has_ambiguity_marker("State Pending: optional detail") is False


def test_prd364_r4_unfinished_authorization_exit_20() -> None:
    """PRD 364 R4 — unfinished-authorization golden still fails spec-rigor (exit 20)."""
    rows = {row["id"]: row for row in _gap487_probe_rows()}
    text = rows["unfinished-authorization-fail-closed"]["text"]
    code, data = _run_prd(_prd_skeleton(text))
    assert code == 20
    assert data.get("verdict") != "pass"


def test_prd364_r5_wraps_fail_unless_reviewed_literal_exact_match() -> None:
    """PRD 364 R5 — colon/bracket Todo wraps fail unless exact reviewedLiterals + Decision Log."""
    m = _load_matcher()
    assert m.text_has_ambiguity_marker("Copy uses Todo: in UI") is True
    allow = frozenset({"Todo:"})
    assert m.text_has_ambiguity_marker("Copy uses Todo: in UI", allowlist=allow) is False
    body = _prd_skeleton(
        "State Todo: documented",
        "Label [Todo] in UI copy",
        frontmatter_extra='reviewedLiterals: ["Todo:", "[Todo]"]\n',
        decision_log="- Todo: and [Todo] are documented UI labels, not unfinished work.\n",
    )
    code, data = _run_prd(body)
    assert code == 0
    assert data.get("verdict") == "pass"
