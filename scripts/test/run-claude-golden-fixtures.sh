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
