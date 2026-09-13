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

from _sw.vendor_paths import repo_root
from unit_tests._harness_runtime import harness_subprocess_env as _harness_env
from unit_tests._harness_runtime import patch_source as _patch_source


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

assert_file "always-apply-skill" "$DIST/skills/sw-always-apply/SKILL.md"
assert_grep "always-apply-skill-naming" "$DIST/skills/sw-always-apply/SKILL.md" 'sw-naming'
assert_grep "always-apply-skill-freeze" "$DIST/skills/sw-always-apply/SKILL.md" 'sw-freeze-guardrail'
python3 - "$DIST/hooks/hooks.json" <<'PY2'
import json, sys
hooks = json.loads(open(sys.argv[1], encoding="utf-8").read())
raise SystemExit(0 if "ContextSwitch" not in hooks.get("hooks", {}) else 1)
PY2
if [ $? -eq 0 ]; then echo "OK  hooks-no-context-switch-registration"; else echo "FAIL hooks-no-context-switch-registration"; FAIL=1; fi
assert_file "no-root-claude-md" "$DIST/skills/sw-always-apply/SKILL.md"
if [ -f "$DIST/CLAUDE.md" ]; then
  echo "FAIL root-claude-md-must-not-exist"
  FAIL=1
else
  echo "OK  root-claude-md-absent"
fi
assert_grep "hooks-type-command" "$DIST/hooks/hooks.json" '"type"[[:space:]]*:[[:space:]]*"command"'
assert_grep "hooks-matcher-field" "$DIST/hooks/hooks.json" '"matcher"'

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
