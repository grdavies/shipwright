#!/usr/bin/env python3
"""Planning graph + maintenance reconciler entrypoint (PRD 033)."""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_park as park  # noqa: E402
from _sw.cli import build_parser, run_module_main  # noqa: E402


def git_root(plugin_root: Path) -> Path:
    proc = subprocess.run(
        ["git", "-C", str(Path.cwd()), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        shell=False,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return plugin_root


def _parse_flag(rest: list[str], flag: str) -> str | None:
    if flag in rest:
        i = rest.index(flag)
        return rest[i + 1] if i + 1 < len(rest) else None
    return None




def cmd_status(root: Path, rest: list[str]) -> int:
    """Unified planning-unit status query (PRD 059 R2)."""
    import planning_unit_status as pus

    unit_id = _parse_flag(rest, "--unit-id")
    issue = _parse_flag(rest, "--issue")
    if not unit_id and not issue:
        print(json.dumps({"verdict": "fail", "error": "usage: planning-graph.py status --unit-id <id> | --issue <n>"}))
        return 2
    result = pus.query_unit_status(root, unit_id=unit_id, issue=issue)
    print(result["status"])
    return 0

def cmd_park(root: Path, action: str, rest: list[str]) -> int:
    """Park/unpark a unit under local-config allowlist + reason governance (R28).

    ``planning-graph.py park <unit-id> --reason <why> [--actor <actor>]`` and
    ``planning-graph.py unpark <unit-id> [--actor <actor>]``. A non-allowlisted
    actor (or a park without a reason) is refused fail-closed; the empty
    post-filter frontier surfaces via ``next`` as a ``scheduler-exhausted`` halt.
    """
    positional = [a for a in rest if not a.startswith("--")]
    # Drop values that belong to flags so the unit-id is the sole positional.
    flag_values = {v for f in ("--actor", "--reason") if (v := _parse_flag(rest, f)) is not None}
    positional = [a for a in positional if a not in flag_values]
    if not positional:
        print(json.dumps({"verdict": "fail", "error": f"usage: planning-graph.py {action} <unit-id> [--reason <why>] [--actor <actor>]"}))
        return 2
    unit_id = positional[0]
    actor = _parse_flag(rest, "--actor") or park.actor_id()
    if action == "park":
        result = park.park_unit(root, unit_id, reason=_parse_flag(rest, "--reason"), actor=actor)
    else:
        result = park.unpark_unit(root, unit_id, actor=actor)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("verdict") == "refused":
        return park.PARK_REFUSED_EXIT
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    plugin_root = SCRIPT_DIR.parent
    root = git_root(plugin_root)
    if not args or args[0] in {"-h", "--help"}:
        print(
            "usage: planning-graph.py reconcile|cycle-check|doctor|relief-check|next|status|park|unpark|posture|paths ...\n"
            "  planning-graph.py reconcile [--dry-run]\n"
            "  planning-graph.py next [--override]   # empty post-filter frontier → scheduler-exhausted halt\n"
            "  planning-graph.py park <unit-id> --reason <why> [--actor <actor>]\n"
            "  planning-graph.py unpark <unit-id> [--actor <actor>]\n"
            "  planning-graph.py status --unit-id <id> | --issue <n>\n"
            "  planning-graph.py posture\n"
        )
        return 0
    cmd = args[0]
    rest = args[1:]
    py = sys.executable
    if cmd == "reconcile":
        return subprocess.run([py, str(plugin_root / "scripts/reconcile.py"), "planning-reconcile", *rest], shell=False).returncode
    if cmd in {"cycle-check", "doctor", "relief-check"}:
        return subprocess.run([py, str(plugin_root / "scripts/planning_graph.py"), str(root), cmd, *rest], shell=False).returncode
    if cmd == "next":
        return subprocess.run([py, str(plugin_root / "scripts/wave_deliver.py"), str(root), "next", *rest], shell=False).returncode
    if cmd in {"park", "unpark"}:
        return cmd_park(root, cmd, rest)
    if cmd == "status":
        return cmd_status(root, rest)
    if cmd == "posture":
        return subprocess.run([py, str(plugin_root / "scripts/planning_autonomy.py"), str(root), "posture"], shell=False).returncode
    if cmd == "paths":
        if not rest:
            rest = ["dirs"]
        return subprocess.run([py, str(plugin_root / "scripts/planning_paths.py"), str(root), *rest], shell=False).returncode
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    run_module_main(main)
