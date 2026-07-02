#!/usr/bin/env python3
"""PRD 050 A1 — hook-state worktree cwd alignment fixtures."""
from __future__ import annotations

import json
import sys
import tempfile
import time
import uuid
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "core" / "hooks"))

from before_task_dispatch import evaluate_pre_tool_use
from memory_prework_gate import load_record, validate_fresh_record
from sw_hook_util import workspace_root


def _git(cmd: list[str], cwd: Path) -> None:
    import subprocess
    subprocess.run(["git", *cmd], cwd=str(cwd), check=True, capture_output=True, text=True)


def setup() -> tuple[Path, Path]:
    tmp = Path(tempfile.mkdtemp())
    primary = tmp / "repo"
    primary.mkdir()
    _git(["init", "-q"], primary)
    _git(["config", "user.email", "t@t.com"], primary)
    _git(["config", "user.name", "t"], primary)
    (primary / "README.md").write_text("x\n", encoding="utf-8")
    _git(["add", "README.md"], primary)
    _git(["commit", "-q", "-m", "init"], primary)
    wt = primary / ".sw-worktrees" / "docs-fixture"
    wt.parent.mkdir(parents=True, exist_ok=True)
    _git(["worktree", "add", str(wt), "-b", "docs/fixture"], primary)
    return primary, wt


def main() -> int:
    fail = 0
    primary, wt = setup()
    now = time.time()

    record = {
        "surface": "sw-execute",
        "outcome": "memory:offline",
        "nonce": uuid.uuid4().hex,
        "recordedAt": int(now),
        "expiresAt": int(now) + 3600,
    }
    (wt / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)
    (wt / ".cursor" / "hooks" / "state" / "memory-prework-search.json").write_text(
        json.dumps(record), encoding="utf-8"
    )
    payload = {"workspace_roots": [str(primary)], "cwd": str(wt), "tool_name": "Write"}
    root = workspace_root(payload)
    rec = load_record(root)
    if root.resolve() == wt.resolve() and rec and validate_fresh_record(rec) is None:
        print("OK  hook-state-worktree-cwd-alignment")
    else:
        print("FAIL hook-state-worktree-cwd-alignment", root, wt)
        fail += 1

    (primary / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)
    (primary / ".cursor" / "hooks" / "state" / "memory-prework-search.json").write_text(
        json.dumps({**record, "nonce": uuid.uuid4().hex}), encoding="utf-8"
    )
    payload2 = {"workspace_roots": [str(primary)], "cwd": str(primary), "tool_name": "Write"}
    root2 = workspace_root(payload2)
    rec2 = load_record(root2)
    if root2.resolve() == primary.resolve() and rec2 and validate_fresh_record(rec2) is None:
        print("OK  hook-state-primary-no-false-positive")
    else:
        print("FAIL hook-state-primary-no-false-positive")
        fail += 1

    nonce = uuid.uuid4().hex
    pre_dir = wt / ".cursor" / "hooks" / "state" / "task-dispatch-preflight"
    pre_dir.mkdir(parents=True, exist_ok=True)
    (pre_dir / f"{nonce}.json").write_text(
        json.dumps({
            "dispatchId": nonce,
            "agent": "sw-prd",
            "modelId": "build-m",
            "tier": "build",
            "recordedAt": now,
            "expiresAt": now + 900,
        }),
        encoding="utf-8",
    )
    payload3 = {
        "workspace_roots": [str(primary)],
        "cwd": str(wt),
        "tool_name": "Task",
        "tool_input": {"subagent_type": "sw-prd", "dispatchId": nonce},
    }
    root3 = workspace_root(payload3)
    result = evaluate_pre_tool_use(payload3, root3)
    if result.verdict in ("pass", "skip"):
        print("OK  hook-state-dispatch-preflight-worktree-alignment")
    else:
        print("FAIL hook-state-dispatch-preflight-worktree-alignment", result)
        fail += 1

    payload4 = {"workspace_roots": [str(primary)], "cwd": "/nonexistent/path", "tool_name": "Write"}
    root4 = workspace_root(payload4)
    if root4.resolve() == primary.resolve():
        print("OK  hook-state-ambiguous-worktree-fail-closed")
    else:
        print("FAIL hook-state-ambiguous-worktree-fail-closed", root4)
        fail += 1

    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
