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
from _harness_patch import patch_source as _patch_source


def main() -> int:
    root = repo_root(__file__)
    env = os.environ.copy()
    env["ROOT"] = str(root)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(root / "scripts" / "test"), str(root / "scripts"), env.get("PYTHONPATH", "")) if p
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
# PRD 019 pre-work memory search recorder fixtures (R6, R7).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WAVE="$ROOT/scripts/wave.sh"
FAIL=0

ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

FIX_DIR="$(mktemp -d "${TMPDIR:-/tmp}/sw-memory-prework.XXXXXX")"
trap 'rm -rf "$FIX_DIR"' EXIT

mkdir -p "$FIX_DIR/.cursor"
cp "$ROOT/.cursor/workflow.config.json" "$FIX_DIR/.cursor/" 2>/dev/null || true

pushd "$FIX_DIR" >/dev/null
git init -q
git config user.email "fixture@shipwright.local"
git config user.name "fixture"

# memory-prework-breadcrumb-audited + degrade-open offline path
if OUT=$(bash "$WAVE" memory prework record --surface sw-execute --offline 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('verdict')=='pass'
assert d.get('outcome')=='memory:offline'
assert d.get('nonce')
"; then
  ok "memory-prework-degrade-open"
else
  bad "memory-prework-degrade-open"
fi

if [[ -f .cursor/hooks/state/memory-prework-search.json ]] && \
   grep -q 'memory:offline' .cursor/hooks/state/memory-prework-search.json && \
   [[ -f .cursor/sw-deliver-runs/run.legacy.log ]]; then
  ok "memory-prework-breadcrumb-audited"
else
  bad "memory-prework-breadcrumb-audited"
fi

# memory:none path (reachable in-repo provider)
rm -f .cursor/hooks/state/memory-prework-search.json .cursor/sw-deliver-runs/run.legacy.log
mkdir -p .cursor/sw-memory/memories
echo in-repo > .cursor/sw-memory.provider
if OUT=$(bash "$WAVE" memory prework record --surface sw-execute --hit-count 0 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('outcome')=='memory:none'
"; then
  ok "memory-prework-none-breadcrumb"
else
  bad "memory-prework-none-breadcrumb"
fi

popd >/dev/null

# --- memory-prework-pretooluse-deny (R8) ---
pushd "$FIX_DIR" >/dev/null
rm -f .cursor/hooks/state/memory-prework-search.json
DENY=$(python3 - <<'PY' "$ROOT" "$FIX_DIR"
import json, sys
from pathlib import Path
plugin_root = Path(sys.argv[1])
root = Path(sys.argv[2])
sys.path.insert(0, str(plugin_root / "core" / "hooks"))
from before_task_dispatch import evaluate_pre_tool_use

blocked = evaluate_pre_tool_use(
    {"tool_name": "Write", "tool_input": {"path": "x.txt", "contents": "y"}, "cwd": str(root)},
    root,
)
print(json.dumps({"verdict": blocked.verdict, "cause": blocked.cause}))
PY
)
if echo "$DENY" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['verdict']=='fail'
assert d['cause']=='missing-prework-search-record'
"; then
  ok "memory-prework-pretooluse-deny"
else
  bad "memory-prework-pretooluse-deny"
  echo "$DENY"
fi

bash "$WAVE" memory prework record --surface sw-execute --offline >/dev/null 2>&1
ALLOW=$(python3 - <<'PY' "$ROOT" "$FIX_DIR"
import sys
from pathlib import Path
plugin_root = Path(sys.argv[1])
root = Path(sys.argv[2])
sys.path.insert(0, str(plugin_root / "core" / "hooks"))
from before_task_dispatch import evaluate_pre_tool_use
r = evaluate_pre_tool_use(
    {"tool_name": "Write", "tool_input": {"path": "x.txt", "contents": "y"}, "cwd": str(root)},
    root,
)
print(r.verdict)
PY
)
if [[ "$ALLOW" == "skip" ]]; then
  ok "memory-prework-pretooluse-allow-with-record"
else
  bad "memory-prework-pretooluse-allow-with-record (got $ALLOW)"
fi
popd >/dev/null

# --- memory-prework-dispatch-inherited (R2) ---
if grep -q 'Pre-work memory search inheritance' "$ROOT/core/rules/sw-subagent-dispatch.mdc" && \
   grep -q 'untrusted_payload' "$ROOT/core/rules/sw-subagent-dispatch.mdc"; then
  ok "memory-prework-dispatch-inherited"
else
  bad "memory-prework-dispatch-inherited"
fi

# --- memory-prework-prompt-redacted (R9) ---
if grep -q 'memory-redact.sh' "$ROOT/core/rules/sw-subagent-dispatch.mdc" && \
   grep -q 'untrusted_payload' "$ROOT/core/rules/sw-subagent-dispatch.mdc"; then
  ok "memory-prework-prompt-redacted"
else
  bad "memory-prework-prompt-redacted"
fi

# --- memory-prework-search-entry (R1, R4) ---
ENTRY_FAIL=0
for cmd in sw-execute sw-debug sw-prd sw-brainstorm sw-amend sw-review sw-stabilize; do
  if ! grep -q 'Pre-work search (mandatory)' "$ROOT/core/commands/${cmd}.md" 2>/dev/null; then
    bad "memory-prework-search-entry: missing in ${cmd}"
    ENTRY_FAIL=1
  fi
done
if [[ "$ENTRY_FAIL" -eq 0 ]]; then
  ok "memory-prework-search-entry"
fi

# --- memory-prework-provider-agnostic (R3) ---
if grep -q 'providers/<memory.provider>.md' "$ROOT/core/skills/memory/SKILL.md" && \
   grep -q 'never call a provider tool directly' "$ROOT/core/skills/memory/SKILL.md"; then
  ok "memory-prework-provider-agnostic"
else
  bad "memory-prework-provider-agnostic"
fi

# --- memory-prework-docs-presence (R10) ---
if grep -q 'Pre-work memory search' "$ROOT/.sw/layout.md" && \
   grep -q 'Pre-work memory search' "$ROOT/docs/guides/workflows.md" && \
   grep -q 'Pre-work search (mandatory)' "$ROOT/core/skills/memory/SKILL.md"; then
  ok "memory-prework-docs-presence"
else
  bad "memory-prework-docs-presence"
fi

if [[ "$FAIL" -ne 0 ]]; then
  echo "run-memory-prework-fixtures: FAIL"
  exit 1
fi
echo "run-memory-prework-fixtures: PASS"

"""

if __name__ == "__main__":
    raise SystemExit(main())
