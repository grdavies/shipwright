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
# Fixtures for worktree.py read_config JSONC tolerance.
#
# Regression guard: read_config() must tolerate // line and /* */ block comments
# in workflow.config.json WITHOUT mangling string values that contain "//"
# (e.g. "http://localhost:8001"). A naive `re.sub(r"//.*$", "", line)` truncated
# such a URL into invalid JSON, the parser fell back to {}, and the entire config
# silently collapsed (parallelCeiling and all other settings lost).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="$ROOT/scripts/worktree.py"
FAIL=0

ok()  { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

# Stage a throwaway repo-shaped dir with worktree.py and a config, run
# `ceiling-check`, and read the resolved ceiling. ceiling-check routes through
# read_config + the parallelCeiling parse, so a correct ceiling proves the whole
# config (including any line containing a URL) parsed cleanly.
resolved_ceiling() {
  local config_body="$1" tmp out
  tmp="$(mktemp -d)"
  mkdir -p "$tmp/scripts" "$tmp/.cursor"
  cp "$SRC" "$tmp/scripts/worktree.py"
  printf '%s\n' "$config_body" >"$tmp/.cursor/workflow.config.json"
  out="$(bash "$tmp/scripts/worktree.py" ceiling-check 2>/dev/null || true)"
  rm -rf "$tmp"
  python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('ceiling',''))" "$out" 2>/dev/null || echo ""
}

# --- jsonc-url-preserved: comments + a URL value must not break parsing ---
# parallelCeiling 7 is distinctive; the naive stripper collapses to {} -> 4.
url_cfg='{
  // line comment before
  "worktree": { "parallelCeiling": 7 },
  /* block comment */
  "sentry": { "restBaseUrl": "http://localhost:8001" }, // inline comment
  "defaultBaseBranch": "main"
}'
if [[ "$(resolved_ceiling "$url_cfg")" == "7" ]]; then
  ok "jsonc-url-preserved: comments stripped, http:// value survived (ceiling=7)"
else
  bad "jsonc-url-preserved: comments stripped, http:// value survived (ceiling=7)"
fi

# --- jsonc-plain: a comment-free config still parses (no regression) ---
plain_cfg='{ "worktree": { "parallelCeiling": 5 } }'
if [[ "$(resolved_ceiling "$plain_cfg")" == "5" ]]; then
  ok "jsonc-plain: comment-free config parses (ceiling=5)"
else
  bad "jsonc-plain: comment-free config parses (ceiling=5)"
fi

# --- read-config-emits-valid-json: output of read_config is parseable JSON ---
tmp="$(mktemp -d)"
mkdir -p "$tmp/scripts" "$tmp/.cursor"
cp "$SRC" "$tmp/scripts/worktree.py"
cat >"$tmp/.cursor/workflow.config.json" <<'JSON'
{
  // comment
  "url": "https://example.com//path", // double-slash inside a string
  "worktree": { "parallelCeiling": 3 }
}
JSON
emitted="$(cd "$tmp" && python3 "$tmp/scripts/worktree.py" read-config)"
rm -rf "$tmp"
if python3 -c "import json,sys; d=json.loads(sys.argv[1]); assert d['url']=='https://example.com//path'; assert d['worktree']['parallelCeiling']==3" "$emitted" 2>/dev/null; then
  ok "read-config-emits-valid-json: in-string // preserved, parses to expected dict"
else
  bad "read-config-emits-valid-json: in-string // preserved, parses to expected dict"
fi

if [[ "$FAIL" -ne 0 ]]; then
  echo "worktree-config-fixtures: FAIL"
  exit 1
fi
echo "worktree-config-fixtures: PASS"

"""

if __name__ == "__main__":
    raise SystemExit(main())
