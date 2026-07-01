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


def load_workflow_config_dict(start: Path | None = None) -> dict:
    root = repo_root(start)
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        candidate = root / rel
        if not candidate.is_file():
            continue
        raw = candidate.read_text(encoding="utf-8")
        try:
            return json.loads(strip_jsonc(raw))
        except json.JSONDecodeError:
            return {}
    return {}


def allocate_port(cfg: dict) -> int:
    wt = cfg.get("worktree", {})
    scaffold = wt.get("scaffold", {})
    start = int(scaffold.get("portRangeStart", 9100))
    end = int(scaffold.get("portRangeEnd", 9199))
    used: set[int] = set()
    try:
        out = subprocess.check_output(["git", "worktree", "list", "--porcelain"], text=True)
    except subprocess.CalledProcessError:
        out = ""
    block: dict[str, str] = {}
    for line in out.splitlines():
        if not line.strip():
            if block:
                sp = _resolve_state_path(block.get("worktree", ""), block.get("gitdir", ""))
                if sp and sp.is_file():
                    try:
                        data = json.loads(sp.read_text(encoding="utf-8"))
                        if data.get("worktreeRole") == "orchestrator" or data.get("countsTowardCeiling") is False:
                            block = {}
                            continue
                        port = data.get("scaffold", {}).get("port")
                        if isinstance(port, int):
                            used.add(port)
                    except (json.JSONDecodeError, OSError):
                        pass
                block = {}
            continue
        key, _, val = line.partition(" ")
        block[key] = val
    if block:
        sp = _resolve_state_path(block.get("worktree", ""), block.get("gitdir", ""))
        if sp and sp.is_file():
            try:
                data = json.loads(sp.read_text(encoding="utf-8"))
                port = data.get("scaffold", {}).get("port")
                if isinstance(port, int):
                    used.add(port)
            except (json.JSONDecodeError, OSError):
                pass
    for port in range(start, end + 1):
        if port not in used:
            return port
    raise RuntimeError("no free scaffold port in configured range")


def cmd_provision(argv: list[str]) -> int:
    import re
    from datetime import datetime, timezone

    name = ""
    branch = ""
    base = ""
    tier = "standard"
    workstream = "implementation"
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--branch" and i + 1 < len(argv):
            branch = argv[i + 1]
            i += 2
            continue
        if arg == "--base" and i + 1 < len(argv):
            base = argv[i + 1]
            i += 2
            continue
        if arg == "--tier" and i + 1 < len(argv):
            tier = argv[i + 1]
            i += 2
            continue
        if arg == "--workstream" and i + 1 < len(argv):
            workstream = argv[i + 1]
            i += 2
            continue
        if arg.startswith("-"):
            print(f"unknown flag: {arg}", file=sys.stderr)
            return 1
        if not name:
            name = arg
        else:
            print(f"unexpected arg: {arg}", file=sys.stderr)
            return 1
        i += 1

    if not name:
        print("usage: worktree.py provision <name> [--branch <branch>] [--base <ref>]", file=sys.stderr)
        return 1

    cfg = load_workflow_config_dict()
    if ceiling_check() != 0:
        print(
            "parallel ceiling reached — run recombination before provisioning another worktree",
            file=sys.stderr,
        )
        ceiling_check()
        return 10

    parent = base or str(cfg.get("defaultBaseBranch", "main"))
    top = repo_root()
    wt_root = top / ".sw-worktrees"
    wt_root.mkdir(parents=True, exist_ok=True)
    wt_path = wt_root / name
    if wt_path.exists():
        print(f"worktree path already exists: {wt_path}", file=sys.stderr)
        return 1

    if branch:
        new_branch = branch
    else:
        derive_proc = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "branch-name-guard.py"), "derive", name],
            capture_output=True,
            text=True,
            check=False,
        )
        if derive_proc.returncode != 0:
            print(derive_proc.stderr.strip() or "branch derive failed", file=sys.stderr)
            return 12
        new_branch = derive_proc.stdout.strip()

    if not _validate_branch_name(new_branch):
        print(f"worktree.py: refusing non-conforming branch name {new_branch!r}", file=sys.stderr)
        return 12

    subprocess.run(["git", "-C", str(top), "fetch", "origin", parent], check=False)
    subprocess.run(
        ["git", "-C", str(top), "worktree", "add", "-b", new_branch, str(wt_path), parent],
        check=True,
    )

    port = allocate_port(cfg)
    db_strategy = str(cfg.get("worktree", {}).get("scaffold", {}).get("dbStrategy", "schema-prefix"))
    db_template = str(cfg.get("worktree", {}).get("scaffold", {}).get("dbTemplate", ""))
    state_payload = json.dumps(
        {
            "worktreeName": name,
            "worktreePath": str(wt_path),
            "tier": tier,
            "workstream": workstream,
            "parentBranch": parent,
            "currentBranch": new_branch,
            "scaffold": {
                "port": port,
                "dbStrategy": db_strategy,
                "dbTemplate": db_template,
                "dbInstance": re.sub(r"[^a-zA-Z0-9]", "_", name),
            },
            "startedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )
    init_proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "shipwright-state.py"), "init", state_payload],
        cwd=str(wt_path),
        capture_output=True,
        text=True,
        check=False,
    )
    if init_proc.returncode != 0:
        print(init_proc.stderr.strip() or init_proc.stdout.strip() or "shipwright-state init failed", file=sys.stderr)
        return init_proc.returncode or 2

    print(
        json.dumps(
            {
                "verdict": "provisioned",
                "path": str(wt_path),
                "branch": new_branch,
                "parent": parent,
                "port": port,
                "dbStrategy": db_strategy,
            },
            indent=2,
        )
    )
    return 0


def cmd_teardown(argv: list[str]) -> int:
    target = ""
    force = False
    for arg in argv:
        if arg == "--force":
            force = True
        elif arg.startswith("-"):
            print(f"unknown flag: {arg}", file=sys.stderr)
            return 1
        else:
            target = arg
    if not target:
        print("usage: worktree.py teardown <name|path> [--force]", file=sys.stderr)
        return 1
    if target == "rm" or " rm " in target:
        print("refused: never rm a worktree directory — use git worktree remove", file=sys.stderr)
        return 2

    top = repo_root()
    wt_path = Path(target)
    if not wt_path.is_dir():
        wt_path = top / ".sw-worktrees" / target
    if not wt_path.is_dir():
        print(f"worktree not found: {target}", file=sys.stderr)
        return 1

    before_kb = 0
    try:
        du = subprocess.check_output(["du", "-sk", str(wt_path)], text=True)
        before_kb = int(du.split()[0])
    except (subprocess.CalledProcessError, ValueError, IndexError):
        pass

    remove_args = ["git", "-C", str(top), "worktree", "remove", str(wt_path)]
    if force:
        remove_args.append("--force")
    proc = subprocess.run(remove_args, check=False)
    if proc.returncode != 0:
        return proc.returncode
    subprocess.run(["git", "-C", str(top), "worktree", "prune"], check=False)
    print(
        json.dumps(
            {
                "verdict": "removed",
                "path": str(wt_path),
                "diskReclaimedKb": max(0, before_kb),
            },
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "provision":
        return cmd_provision(args[1:])
    if args and args[0] == "teardown":
        return cmd_teardown(args[1:])

    parser = build_parser(prog="worktree", description="Worktree provision and ceiling helpers.")
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(handler=cmd_list)

    sub.add_parser("ceiling-check").set_defaults(handler=cmd_ceiling_check)
    sub.add_parser("read-config").set_defaults(handler=cmd_read_config)

    ns = parser.parse_args(args)
    if not ns.command:
        parser.print_help()
        return 1
    return int(ns.handler(ns))


if __name__ == "__main__":
    run_module_main(main)
