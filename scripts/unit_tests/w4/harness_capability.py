#!/usr/bin/env python3
"""Ported fixture suite (R27) — embedded harness executed without on-disk shell files."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
_SCRIPTS_ROOT = SCRIPT_DIR.parents[1]
_TEST_DIR = _SCRIPTS_ROOT / "test"
for _entry in (str(_TEST_DIR), str(_SCRIPTS_ROOT)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from _fixture_lib import repo_root
from _harness_patch import harness_subprocess_env as _harness_env
from _harness_patch import patch_source as _patch_source


def main() -> int:
    root = repo_root(__file__)
    env = _harness_env(root)
    src = _patch_source(_SOURCE, root)
    completed = subprocess.run(
        ["bash", "-c", src],
        cwd=str(root),
        env=env,
        shell=False,
    )
    return completed.returncode


_SOURCE = r"""
#!/usr/bin/env bash
# Golden tests for platform capability descriptors (M0–M3 schema scope).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VALIDATE="$ROOT/scripts/validate_descriptor.py"
FIX="$ROOT/scripts/test/fixtures/capability"

chmod +x "$VALIDATE"
mkdir -p "$FIX"

FAIL=0

run_expect() {
  local name="$1" expect_ec="$2" desc="$3"
  set +e
  OUT=$(python3 "$VALIDATE" "$desc" 2>&1)
  EC=$?
  set -e
  if [ "$EC" -eq "$expect_ec" ]; then
    echo "OK  $name exit=$EC"
  else
    echo "FAIL $name expected exit=$expect_ec got exit=$EC"
    echo "$OUT"
    FAIL=1
  fi
}

run_expect cursor-tier1 0 "$ROOT/platforms/cursor/descriptor.json"
run_expect claude-code-tier1 0 "$ROOT/platforms/claude-code/descriptor.json"

# Unknown flag value (M4-only vocabulary rejected in M1 schema)
cat >"$FIX/bad-hooks-wrapper.json" <<'JSON'
{
  "platform": "codex",
  "hooks": "wrapper",
  "skills": "native",
  "commands": "slash-md",
  "rules": "mdc",
  "subagents": "native",
  "mcp": "yes",
  "memoryXport": "mcp"
}
JSON
run_expect unknown-hooks-value 1 "$FIX/bad-hooks-wrapper.json"

# Missing required flag
cat >"$FIX/missing-flag.json" <<'JSON'
{
  "platform": "cursor",
  "hooks": "native",
  "skills": "native",
  "commands": "slash-md",
  "rules": "mdc",
  "subagents": "native",
  "mcp": "yes"
}
JSON
run_expect missing-memoryXport 1 "$FIX/missing-flag.json"

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
