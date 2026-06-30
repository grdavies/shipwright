#!/usr/bin/env python3
"""Ported fixture suite (R27) — embedded harness executed without on-disk shell files."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))

from _fixture_lib import repo_root
from _harness_patch import patch_source as _patch_source


def main() -> int:
    root = repo_root(__file__)
    env = os.environ.copy()
    env["ROOT"] = str(root)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(root / "scripts"), env.get("PYTHONPATH", "")) if p
    )
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
# Golden assertions for dist/claude-code/ (manifest, hooks, samples, rule downgrade).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIST="$ROOT/dist/claude-code"
FAIL=0

assert_file() {
  local label="$1" path="$2"
  if [ -f "$path" ]; then
    echo "OK  $label present"
  else
    echo "FAIL $label missing at $path"
    FAIL=1
  fi
}

assert_grep() {
  local label="$1" path="$2" pattern="$3"
  if [ -f "$path" ] && grep -qE "$pattern" "$path"; then
    echo "OK  $label"
  else
    echo "FAIL $label (pattern=$pattern path=$path)"
    FAIL=1
  fi
}

assert_not_grep() {
  local label="$1" path="$2" pattern="$3"
  if [ -f "$path" ] && ! grep -qE "$pattern" "$path"; then
    echo "OK  $label"
  else
    echo "FAIL $label still matches $pattern"
    FAIL=1
  fi
}

if [ ! -d "$DIST" ]; then
  echo "FAIL dist/claude-code missing — run: python3 -m sw generate claude-code"
  exit 1
fi

assert_file "claude-plugin-manifest" "$DIST/.claude-plugin/plugin.json"
assert_grep "manifest-name" "$DIST/.claude-plugin/plugin.json" '"name"[[:space:]]*:[[:space:]]*"shipwright"'

assert_file "hooks-json" "$DIST/hooks/hooks.json"
assert_grep "hooks-session-start" "$DIST/hooks/hooks.json" 'SessionStart'
assert_grep "hooks-user-prompt" "$DIST/hooks/hooks.json" 'UserPromptSubmit'
assert_grep "hooks-stop" "$DIST/hooks/hooks.json" 'Stop'
assert_grep "hooks-claude-root-env" "$DIST/hooks/hooks.json" 'CLAUDE_PLUGIN_ROOT'

assert_file "claude-md" "$DIST/CLAUDE.md"
assert_grep "claude-md-always-apply" "$DIST/CLAUDE.md" 'sw-naming'
assert_grep "claude-md-freeze-rule" "$DIST/CLAUDE.md" 'sw-freeze-guardrail'

assert_file "sample-command" "$DIST/commands/sw-watch-ci.md"
assert_grep "command-claude-root" "$DIST/commands/sw-watch-ci.md" 'CLAUDE_PLUGIN_ROOT'
assert_not_grep "command-no-cursor-root" "$DIST/commands/sw-watch-ci.md" 'CURSOR_PLUGIN_ROOT'

assert_file "sample-skill" "$DIST/skills/checks-gate/SKILL.md"
assert_grep "skill-use-when-downgrade" "$DIST/skills/stabilize-loop/SKILL.md" 'USE WHEN'

assert_file "sample-agent" "$DIST/agents/sw-security-reviewer.md"
assert_grep "agent-frontmatter" "$DIST/agents/sw-security-reviewer.md" '^name:'

# R3: core/ bodies stay platform-neutral (env var still in core command source).
if grep -q 'CURSOR_PLUGIN_ROOT' "$ROOT/core/commands/sw-ship.md" 2>/dev/null; then
  echo "OK  core-source-retains-cursor-env"
else
  echo "FAIL core-source-missing-cursor-env (expected neutral core/)"
  FAIL=1
fi

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
