"""Bash harness source patching for embedded fixture ports (R27)."""
from __future__ import annotations
import re
from pathlib import Path


def _dash_fixtures(name: str) -> str:
    if not name.startswith("run-") or not name.endswith("-fixtures.sh"):
        return name.replace(".sh", ".py")
    mid = name[len("run"):-len("-fixtures.sh")].lstrip("-")
    return "run_" + mid.replace("-", "_") + "_fixtures.py"


def patch_source(src: str, root: Path) -> str:
    src = src.replace("#!/usr/bin/env bash", "")
    src = src.replace("set -euo pipefail", "set -eu")
    src = re.sub(
        r'ROOT="\$\(cd "\$\(dirname "\$\{BASH_SOURCE\[0\]\}"\)/\.\./\.\." && pwd\)"',
        f'ROOT="{root}"',
        src,
    )
    src = re.sub(r'ROOT="[^"]*worktrees/[^"]*"', f'ROOT="{root}"', src)
    src = re.sub(r"scripts/test/run-[a-z0-9-]+-fixtures\.sh", lambda m: "scripts/test/" + _dash_fixtures(m.group(0).split("/",1)[-1]), src)
    src = re.sub(r"scripts/[A-Za-z0-9_./-]+\.sh", lambda m: m.group(0)[:-3] + ".py", src)
    src = re.sub(r'bash\s+"([^"]+\.py)"', r'python3 "\1"', src)
    src = re.sub(r'bash\s+"\$([A-Z_][A-Z0-9_]*)"', r'python3 "$\1"', src)
    src = re.sub(r'bash\s+"\$ROOT/([^"]+)"', r'python3 "$ROOT/\1"', src)
    src = re.sub(r'source\s+"[^"]*fixture-lib\.sh"', "", src)
    src = src.replace("scripts/test/fixture-lib.sh", "")
    src = src.replace("| jq ", "| python3 -c 'import json,sys; print(json.load(sys.stdin)", 1)  # naive skip
    return src
