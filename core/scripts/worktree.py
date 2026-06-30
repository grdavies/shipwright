#!/usr/bin/env python3
"""Worktree provision, scaffold allocation, safe teardown, parallelism ceiling.

Branch validation delegates to worktree_lib.py (PRD 026 R24)."""
from __future__ import annotations
import sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main

def _validate_branch_via_worktree_lib(branch: str) -> bool:
    import subprocess
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "worktree_lib.py"), "validate", branch],
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


def main(argv: list[str] | None = None) -> int:
    import json
    import subprocess
    import sys
    from pathlib import Path

    cfg = json.loads(sys.argv[1] or "{}")
    wt = cfg.get("worktree", {})
    scaffold = wt.get("scaffold", {})
    start = int(scaffold.get("portRangeStart", 9100))
    end = int(scaffold.get("portRangeEnd", 9199))
    used = set()

    try:
        out = subprocess.check_output(["git", "worktree", "list", "--porcelain"], text=True)
    except subprocess.CalledProcessError:
        out = ""

    def resolve_state_path(worktree: str, gitdir: str):
        if not gitdir:
            return None
        gd = Path(gitdir)
        if not gd.is_absolute():
            gd = (Path(worktree) / gd).resolve()
        else:
            gd = gd.resolve()
        return gd / "shipwright.json"

    block: dict[str, str] = {}
    for line in out.splitlines():
        if not line.strip():
            if block:
                sp = resolve_state_path(block.get("worktree", ""), block.get("gitdir", ""))
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
        sp = resolve_state_path(block.get("worktree", ""), block.get("gitdir", ""))
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
            print(port)
            break
    else:
        sys.exit(2)
    return 0

if __name__ == "__main__":
    run_module_main(main)
