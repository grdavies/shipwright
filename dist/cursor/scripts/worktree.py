#!/usr/bin/env python3
"""Worktree provision, scaffold allocation, safe teardown, parallelism ceiling."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import build_parser, run_module_main


def strip_jsonc(text: str) -> str:
    """Strip // line and /* */ block comments outside JSON strings."""
    out: list[str] = []
    i, n = 0, len(text)
    in_str = escape = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
            i += 1
        elif c == '"':
            in_str = True
            out.append(c)
            i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def repo_root(start: Path | None = None) -> Path:
    script_root = SCRIPT_DIR.parent
    if (script_root / ".cursor/workflow.config.json").is_file() or (
        script_root / "workflow.config.json"
    ).is_file():
        return script_root
    start = start or Path.cwd()
    proc = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return start
    return Path(proc.stdout.strip())


def read_config(start: Path | None = None) -> None:
    root = repo_root(start)
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        candidate = root / rel
        if not candidate.is_file():
            continue
        raw = candidate.read_text(encoding="utf-8")
        try:
            data = json.loads(strip_jsonc(raw))
        except json.JSONDecodeError:
            print(raw)
            return
        print(json.dumps(data))
        return
    print("{}")


def _resolve_state_path(worktree: str, gitdir: str) -> Path | None:
    if not gitdir:
        return None
    gd = Path(gitdir)
    if not gd.is_absolute():
        gd = (Path(worktree) / gd).resolve()
    else:
        gd = gd.resolve()
    return gd / "shipwright.json"


def _counts_toward_ceiling(worktree: str, gitdir: str) -> bool:
    sp = _resolve_state_path(worktree, gitdir)
    if sp and sp.is_file():
        try:
            data = json.loads(sp.read_text(encoding="utf-8"))
            if data.get("worktreeRole") == "orchestrator":
                return False
            if data.get("countsTowardCeiling") is False:
                return False
        except (json.JSONDecodeError, OSError):
            pass
    return True


def active_worktree_count() -> int:
    try:
        out = subprocess.check_output(["git", "worktree", "list", "--porcelain"], text=True)
    except subprocess.CalledProcessError:
        return 0
    count = 0
    block: dict[str, str] = {}
    for line in out.splitlines():
        if not line.strip():
            if block:
                wt = block.get("worktree", "")
                if "/.sw-worktrees/" in wt and _counts_toward_ceiling(wt, block.get("gitdir", "")):
                    count += 1
                block = {}
            continue
        key, _, val = line.partition(" ")
        block[key] = val
    if block:
        wt = block.get("worktree", "")
        if "/.sw-worktrees/" in wt and _counts_toward_ceiling(wt, block.get("gitdir", "")):
            count += 1
    return count


def _validate_branch_name(branch: str) -> bool:
    """Refuse non-conforming branch names (PRD 007 R23/R27) via worktree_lib.py."""
    guard_proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "branch-name-guard.py"), "validate", branch],
        capture_output=True,
        text=True,
        check=False,
    )
    wlib_proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "worktree_lib.py"), "validate", branch],
        capture_output=True,
        text=True,
        check=False,
    )
    return guard_proc.returncode == 0 and wlib_proc.returncode == 0


def ceiling_check(start: Path | None = None) -> int:
    root = repo_root(start)
    cfg: dict = {}
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        candidate = root / rel
        if candidate.is_file():
            raw = candidate.read_text(encoding="utf-8")
            try:
                cfg = json.loads(strip_jsonc(raw))
            except json.JSONDecodeError:
                cfg = {}
            break
    count = active_worktree_count()
    ceiling = int(cfg.get("worktree", {}).get("parallelCeiling", 4))
    verdict = "ok" if count < ceiling else "at-ceiling"
    print(json.dumps({"swWorktrees": count, "ceiling": ceiling, "verdict": verdict}))
    return 0 if verdict == "ok" else 10


def cmd_read_config(_args: argparse.Namespace) -> int:
    read_config()
    return 0


def cmd_ceiling_check(_args: argparse.Namespace) -> int:
    return ceiling_check()


def cmd_list(args: argparse.Namespace) -> int:
    if args.json:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "shipwright-state.py"), "index"],
            check=False,
        )
        return proc.returncode
    proc = subprocess.run(["git", "worktree", "list"], check=False)
    return proc.returncode


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(prog="worktree", description="Worktree provision and ceiling helpers.")
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(handler=cmd_list)

    sub.add_parser("ceiling-check").set_defaults(handler=cmd_ceiling_check)
    sub.add_parser("read-config").set_defaults(handler=cmd_read_config)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 1
    return int(args.handler(args))


if __name__ == "__main__":
    run_module_main(main)
