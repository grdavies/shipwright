"""PRD 361 phase 1 — layered ambiguity matcher at every call site."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def _prd_skeleton(*req_lines: str) -> str:
    reqs = "\n".join(f"- **R{n}** {body}" for n, body in enumerate(req_lines, start=1))
    return (
        "---\n"
        "frozen: false\n"
        "---\n"
        "# PRD 361 matcher fixture\n\n"
        "## Overview\n\n"
        "Fixture body for layered matcher tests.\n\n"
        "## Goals\n\n"
        "- Validate ambiguity layering\n\n"
        "## Non-Goals\n\n"
        "- None\n\n"
        "## Requirements\n\n"
        f"{reqs}\n\n"
        "## Technical Requirements\n\n"
        "None\n\n"
        "## Security & Compliance\n\n"
        "None\n\n"
        "## Testing Strategy\n\n"
        "Unit tests\n\n"
        "## Rollout Plan\n\n"
        "Ship\n\n"
        "## Decision Log\n\n"
        "## Open Questions\n\n"
        "(none)\n"
    )


def _run_prd(repo: Path, body: str, *, tier: str = "standard") -> tuple[int, dict]:
    fix = repo / "scripts/test/fixtures/spec-rigor/_tmp-prd361-phase1.md"
    fix.parent.mkdir(parents=True, exist_ok=True)
    fix.write_text(body, encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts/spec-rigor-check.py"),
            "--root",
            str(repo),
            "--artifact",
            "prd",
            "--path",
            str(fix),
            "--tier",
            tier,
        ],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        data = {"verdict": "fail", "raw": proc.stdout, "stderr": proc.stderr}
    return proc.returncode, data


def _ambiguity_messages(data: dict) -> list[str]:
    return [
        f.get("message", "")
        for f in data.get("findings", [])
        if f.get("severity") == "error" and "ambiguity marker" in f.get("message", "")
    ]


def test_r1_all_caps_and_tbd_still_fail() -> None:
    body = _prd_skeleton("Something TBD later", "Use TODO before ship")
    code, data = _run_prd(_WORKTREE_ROOT, body)
    assert code != 0
    msgs = _ambiguity_messages(data)
    assert any("R1" in m for m in msgs)
    assert any("R2" in m for m in msgs)


def test_r1_triple_question_mark_fails() -> None:
    body = _prd_skeleton("Scope ??? unknown")
    _, data = _run_prd(_WORKTREE_ROOT, body)
    assert _ambiguity_messages(data)


def test_r1_unresolved_phrase_fails() -> None:
    body = _prd_skeleton("Timing to be determined in Q4")
    _, data = _run_prd(_WORKTREE_ROOT, body)
    assert _ambiguity_messages(data)


def test_r2_title_case_named_state_passes() -> None:
    body = _prd_skeleton("Workflow enters Todo when criteria met")
    code, data = _run_prd(_WORKTREE_ROOT, body)
    assert code == 0
    assert data.get("verdict") == "pass"
    assert not _ambiguity_messages(data)


def test_r3_slash_taxonomy_lowercase_passes() -> None:
    body = _prd_skeleton("Tags use idea/todo/note taxonomy")
    code, data = _run_prd(_WORKTREE_ROOT, body)
    assert code == 0
    assert not _ambiguity_messages(data)


def test_r3_all_caps_slash_segment_fails() -> None:
    body = _prd_skeleton("Legacy IDEA/TODO bucket still blocked")
    _, data = _run_prd(_WORKTREE_ROOT, body)
    assert _ambiguity_messages(data)


def test_r4_colon_and_bracket_wrap_fail() -> None:
    body = _prd_skeleton("State Pending: must be explicit", "Label [Pending] in UI copy")
    _, data = _run_prd(_WORKTREE_ROOT, body)
    msgs = _ambiguity_messages(data)
    assert len(msgs) >= 2


def test_r8_finding_message_unchanged() -> None:
    body = _prd_skeleton("Still has FIXME marker")
    _, data = _run_prd(_WORKTREE_ROOT, body)
    assert _ambiguity_messages(data) == ["ambiguity marker in R1"]


def test_existing_fixtures_regression() -> None:
    for fixture, expect_pass in (
        ("prd-pass.md", True),
        ("prd-pass-v2.md", True),
        ("prd-fail-clarify.md", False),
    ):
        path = _WORKTREE_ROOT / "scripts/test/fixtures/spec-rigor" / fixture
        proc = subprocess.run(
            [
                sys.executable,
                str(_WORKTREE_ROOT / "scripts/spec-rigor-check.py"),
                "--root",
                str(_WORKTREE_ROOT),
                "--artifact",
                "prd",
                "--path",
                str(path),
                "--tier",
                "full" if fixture == "prd-fail-clarify.md" else "standard",
            ],
            cwd=str(_WORKTREE_ROOT),
            capture_output=True,
            text=True,
        )
        data = json.loads(proc.stdout)
        if expect_pass:
            assert proc.returncode == 0 and data.get("verdict") == "pass", fixture
        else:
            assert data.get("verdict") == "fail", fixture
