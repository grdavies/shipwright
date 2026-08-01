"""PRD 085 R12 — sw-doc.md doc_loop CLI examples round-trip."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

DOC_LOOP_DOC_PATHS = (
    Path("core/commands/sw-doc.md"),
    Path("dist/cursor/commands/sw-doc.md"),
    Path("dist/claude-code/commands/sw-doc.md"),
)

DOC_LOOP_LINE = re.compile(
    r"^python3 scripts/doc_loop\.py\s+(.+)$",
    re.MULTILINE,
)


def _extract_doc_loop_invocations(text: str) -> list[str]:
    return [match.strip() for match in DOC_LOOP_LINE.findall(text)]


def _substitute_placeholders(args: str, *, root: Path, topic: str) -> list[str]:
    normalized = (
        args.replace("<root>", str(root))
        .replace("<topic>", topic)
        .replace("<Standard|Full>", "Standard")
        .replace("<Full|Standard>", "Standard")
    )
    return ["python3", str(scripts / "doc_loop.py"), *normalized.split()]


@pytest.mark.parametrize("rel_path", DOC_LOOP_DOC_PATHS, ids=[str(p) for p in DOC_LOOP_DOC_PATHS])
def test_doc_loop_examples_use_doc_loop_subcommand(repo_root: Path, rel_path: Path) -> None:
    text = (repo_root / rel_path).read_text(encoding="utf-8")
    invocations = _extract_doc_loop_invocations(text)
    assert invocations, f"expected at least one doc_loop.py example in {rel_path}"
    for args in invocations:
        tokens = args.split()
        assert tokens, f"empty doc_loop invocation in {rel_path}"
        assert tokens[0] != "provision", (
            f"{rel_path}: doc_loop.py has no provision subcommand — use "
            f"'<root> doc-loop --topic …' (got: {args!r})"
        )
        root_token = tokens[0].replace("<root>", "fixture-root")
        if root_token != "fixture-root" and tokens[1:2] != ["doc-loop"]:
            # Placeholder root form: <root> doc-loop …
            assert tokens[0] == "<root>" and tokens[1] == "doc-loop", (
                f"{rel_path}: expected '<root> doc-loop …' contract (got: {args!r})"
            )
        else:
            assert tokens[1] == "doc-loop", f"{rel_path}: missing doc-loop subcommand (got: {args!r})"


@pytest.mark.parametrize("rel_path", DOC_LOOP_DOC_PATHS, ids=[str(p) for p in DOC_LOOP_DOC_PATHS])
def test_doc_loop_examples_do_not_hit_unknown_subcommand(
    repo_root: Path, rel_path: Path, tmp_git_repo: Path
) -> None:
    fixture_root = tmp_git_repo
    (fixture_root / ".cursor").mkdir(parents=True, exist_ok=True)
    text = (repo_root / rel_path).read_text(encoding="utf-8")
    topic = "doc-example-roundtrip"
    with patch("wave_lock._canonical_repo_root_for_locks", return_value=fixture_root):
        for args in _extract_doc_loop_invocations(text):
            argv = _substitute_placeholders(args, root=fixture_root, topic=topic)
            if "doc-loop" in argv and "--dry-run" not in argv:
                argv = [*argv, "--dry-run"]
            completed = subprocess.run(
                argv,
                cwd=str(repo_root),
                env={**os_environ(), "PYTHONPATH": str(scripts)},
                capture_output=True,
                text=True,
                check=False,
            )
            combined = f"{completed.stdout}\n{completed.stderr}"
            assert "unknown doc-loop subcommand" not in combined, (
                f"{rel_path}: {args!r} produced unknown subcommand:\n{combined}"
            )
            if completed.returncode == 0 and completed.stdout.strip():
                payload = json.loads(completed.stdout)
                assert payload.get("verdict") != "fail", payload
                assert "unknown doc-loop subcommand" not in json.dumps(payload)


def os_environ() -> dict[str, str]:
    import os

    return dict(os.environ)


def test_corrected_doc_loop_example_dry_run_round_trips(
    repo_root: Path, tmp_git_repo: Path
) -> None:
    fixture_root = tmp_git_repo
    (fixture_root / ".cursor").mkdir(parents=True, exist_ok=True)
    topic = "cli-contract-fixture"
    argv = [
        "python3",
        str(scripts / "doc_loop.py"),
        str(fixture_root),
        "doc-loop",
        "--topic",
        topic,
        "--tier",
        "Standard",
        "--dry-run",
    ]
    with patch("wave_lock._canonical_repo_root_for_locks", return_value=fixture_root):
        completed = subprocess.run(
            argv,
            cwd=str(repo_root),
            env={**os_environ(), "PYTHONPATH": str(scripts)},
            capture_output=True,
            text=True,
            check=False,
        )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    payload = json.loads(completed.stdout)
    assert payload.get("verdict") == "pass"
    assert payload.get("action") == "doc-loop"
    assert "unknown doc-loop subcommand" not in completed.stdout
