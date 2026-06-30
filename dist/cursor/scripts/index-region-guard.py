#!/usr/bin/env python3
"""Region-integrity guard for planning INDEX dual-region seam (PRD 031 R24). Usage:"""
from __future__ import annotations
import sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main

def main(argv: list[str] | None = None) -> int:
    import json
    import subprocess
    import sys
    from pathlib import Path

    plugin_root = Path(sys.argv[1])
    root = Path(sys.argv[2])
    index_rel = sys.argv[3]
    writer = sys.argv[4]
    index_path = root / index_rel

    sys.path.insert(0, str(plugin_root / "scripts"))
    import planning_index_gen as pig  # noqa: E402
    from wave_state import enumerate_scoped_runs  # noqa: E402

    errors: list[str] = []

    def git_show(ref: str) -> str | None:
        proc = subprocess.run(
            ["git", "-C", str(root), "show", f"{ref}:{index_rel}"],
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            return None
        return proc.stdout

    def region_changed(old: str | None, new: str, region: str) -> bool:
        if old is None:
            old_body = "\n"
        else:
            try:
                old_body = pig.parse_regions(old).__dict__[region]
            except ValueError:
                return True
        try:
            new_body = pig.parse_regions(new).__dict__[region]
        except ValueError:
            return True
        return old_body != new_body

    old_text = git_show("HEAD")
    new_text_content = index_path.read_text(encoding="utf-8") if index_path.is_file() else ""

    if not new_text_content:
        print(json.dumps({"verdict": "pass", "note": "no INDEX content"}))
        sys.exit(0)

    for region in ("structural", "derived", "inFlight"):
        if not region_changed(old_text, new_text_content, region):
            continue
        allowed = {
            "structural": frozenset({"generator", "structural"}),
            "derived": frozenset({"reconciler", "derived"}),
            "inFlight": frozenset({"deliver", "inFlight"}),
        }[region]
        if writer not in allowed:
            errors.append(
                f"region {region} modified without authorized writer "
                f"(got {writer!r}, allowed {sorted(allowed)})"
            )

    try:
        inflight_body = pig.parse_regions(new_text_content).inFlight
    except ValueError as exc:
        errors.append(f"INDEX region parse failed: {exc}")
        inflight_body = ""

    def has_live_run_state() -> bool:
        runs = enumerate_scoped_runs(root)
        for run in runs:
            if run.get("verdict") == "running":
                return True
            state_path = root / str(run.get("statePath", ""))
            if not state_path.is_file():
                continue
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            phases = state.get("phases") or {}
            if any((meta or {}).get("status") == "in-flight" for meta in phases.values()):
                return True
        return False

    if has_live_run_state() and not inflight_body.strip():
        errors.append("empty inFlight region while live deliver run-state exists")

    if errors:
        print(
            json.dumps(
                {"verdict": "fail", "error": "index region integrity violation", "violations": errors},
                indent=2,
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    print(json.dumps({"verdict": "pass", "action": "index-region-guard"}))
    return 0

if __name__ == "__main__":
    run_module_main(main)
