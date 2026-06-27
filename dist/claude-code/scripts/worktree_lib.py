#!/usr/bin/env python3
"""Worktree/branch helpers — Python façade over branch-name-guard (PRD 026 R24)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
GUARD = SCRIPT_DIR / "branch-name-guard.sh"
RELEASE_PLEASE = ROOT / "release-please-config.json"
FALLBACK_TYPES = frozenset(
    {"feat", "fix", "perf", "revert", "docs", "chore", "refactor", "test"}
)


def load_branch_types() -> frozenset[str]:
    """Single-source allowed types from release-please-config.json."""
    if not RELEASE_PLEASE.is_file():
        return FALLBACK_TYPES
    try:
        data = json.loads(RELEASE_PLEASE.read_text(encoding="utf-8"))
        types = [
            sec["type"]
            for pkg in data.get("packages", {}).values()
            for sec in pkg.get("changelog-sections", [])
            if sec.get("type")
        ]
        return frozenset(types) if types else FALLBACK_TYPES
    except (json.JSONDecodeError, OSError):
        return FALLBACK_TYPES


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"^[a-z]+/", "", text)
    text = re.sub(r"[^a-z0-9._/-]+", "-", text)
    return text.strip("-/")


def docs_branch_for_topic(topic: str) -> str:
    slug = slugify(topic) or "docs"
    return f"docs/{slug}"


def _run_guard(cmd: str, *args: str) -> subprocess.CompletedProcess[str]:
    if not GUARD.is_file():
        raise FileNotFoundError(f"branch-name-guard missing: {GUARD}")
    return subprocess.run(
        ["bash", str(GUARD), cmd, *args],
        capture_output=True,
        text=True,
        check=False,
    )


def validate_branch(branch: str) -> dict:
    proc = _run_guard("validate", branch)
    try:
        payload = json.loads(proc.stdout or proc.stderr or "{}")
    except json.JSONDecodeError:
        payload = {"verdict": "fail", "branch": branch, "error": proc.stderr.strip()}
    payload["exitCode"] = proc.returncode
    return payload


def derive_branch(name: str, branch_type: str = "feat") -> str:
    proc = _run_guard("derive", name, branch_type)
    if proc.returncode != 0:
        raise ValueError(proc.stderr.strip() or "derive failed")
    return proc.stdout.strip()


def is_docs_branch(branch: str) -> bool:
    return branch.startswith("docs/")


def refuse_default_branch(branch: str, default: str) -> None:
    if branch == default:
        raise ValueError(f"refused: operation targets protected default branch {default!r}")


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "usage: worktree_lib.py {types|validate <branch>|derive <name> [type]|docs-branch <topic>}",
            file=sys.stderr,
        )
        sys.exit(2)
    cmd = sys.argv[1]
    if cmd == "types":
        print(" ".join(sorted(load_branch_types())))
        sys.exit(0)
    if cmd == "validate":
        if len(sys.argv) < 3:
            print("usage: worktree_lib.py validate <branch>", file=sys.stderr)
            sys.exit(2)
        result = validate_branch(sys.argv[2])
        print(json.dumps(result, indent=2))
        sys.exit(0 if result.get("verdict") == "pass" else 3)
    if cmd == "derive":
        if len(sys.argv) < 3:
            print("usage: worktree_lib.py derive <name> [type]", file=sys.stderr)
            sys.exit(2)
        btype = sys.argv[3] if len(sys.argv) > 3 else "feat"
        print(derive_branch(sys.argv[2], btype))
        sys.exit(0)
    if cmd == "docs-branch":
        if len(sys.argv) < 3:
            print("usage: worktree_lib.py docs-branch <topic>", file=sys.stderr)
            sys.exit(2)
        print(docs_branch_for_topic(sys.argv[2]))
        sys.exit(0)
    print(f"unknown command: {cmd}", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
