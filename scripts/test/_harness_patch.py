"""Bash harness source patching for embedded fixture ports (R27)."""
from __future__ import annotations

import re
from pathlib import Path

_FIXTURE_LIB_SHIM = """
content_path() {
  local rel="${1:?relative path}"
  if [[ -f "$ROOT/core/$rel" ]]; then
    printf '%s\\n' "$ROOT/core/$rel"
  elif [[ -f "$ROOT/$rel" ]]; then
    printf '%s\\n' "$ROOT/$rel"
  else
    printf '%s\\n' "$ROOT/$rel"
    return 1
  fi
}
""".strip()


def _dash_fixtures(name: str) -> str:
    if not name.startswith("run-") or not name.endswith("-fixtures.sh"):
        return name.replace(".sh", ".py")
    mid = name[len("run") : -len("-fixtures.sh")].lstrip("-")
    return "run_" + mid.replace("-", "_") + "_fixtures.py"


def patch_source(src: str, root: Path) -> str:
    src = src.replace("#!/usr/bin/env bash", "")
    src = src.replace("set -euo pipefail", "set -eu")
    src = re.sub(
        r'ROOT="\$\(cd "\$\(dirname "\$\{BASH_SOURCE\[0\]\}"\)/\.\./\.\." && pwd\)"',
        f'ROOT="{root}"',
        src,
    )
    src = re.sub(
        r'ROOT="\$\(cd "\$\(dirname "\$\{BASH_SOURCE\[0\]\}"\)/\.\." && pwd\)"',
        f'ROOT="{root}"',
        src,
    )
    src = re.sub(r'ROOT="[^"]*worktrees/[^"]*"', f'ROOT="{root}"', src)
    src = re.sub(r"# shellcheck source=[^\n]*\n", "", src)
    src = re.sub(
        r'source\s+"\$\(dirname\s+"\$\{BASH_SOURCE\[0\]\}"\)/fixture-lib\.sh"\s*\n?',
        "",
        src,
    )
    src = re.sub(r'source\s+"\$ROOT/scripts/test/fixture-lib\.sh"\s*\n?', "", src)
    src = re.sub(r'source\s+"[^"]*fixture-lib\.sh"\s*\n?', "", src)
    src = re.sub(
        r"scripts/test/run-[a-z0-9-]+-fixtures\.sh",
        lambda m: "scripts/test/" + _dash_fixtures(m.group(0).rsplit("/", 1)[-1]),
        src,
    )
    src = re.sub(r'bash\s+"\$DOC_AFTER/\$\{fx\}\.sh"', r'python3 "$DOC_AFTER/${fx}.py"', src)
    src = re.sub(r"scripts/[A-Za-z0-9_./-]+\.sh", lambda m: m.group(0)[:-3] + ".py", src)
    src = re.sub(r'bash\s+"([^"]+\.py)"', r'python3 "\1"', src)
    src = re.sub(r'bash\s+"\$([A-Z_][A-Z0-9_]*)"', r'python3 "$\1"', src)
    src = re.sub(r'bash\s+"\$ROOT/([^"]+)"', r'python3 "$ROOT/\1"', src)
    if "content_path()" not in src and "fixture-lib" in src:
        pass
    if "content_path()" not in src:
        src = re.sub(
            rf'(ROOT="{re.escape(str(root))}"\s*\n)',
            r"\1" + _FIXTURE_LIB_SHIM + "\n",
            src,
            count=1,
        )
    return src
