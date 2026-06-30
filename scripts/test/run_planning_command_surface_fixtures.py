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
# PRD 035 phase 4 — planning command surface finalization fixtures (R15).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/test/fixture-lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/fixture-lib.sh"
GRAPH="$ROOT/scripts/planning-graph.py"
CORE_GRAPH="$ROOT/core/scripts/planning-graph.py"
SW_DOC="$(content_path commands/sw-doc.md)"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

check() {
  local name="$1" file="$2" pattern="$3"
  if grep -qE "$pattern" "$file" 2>/dev/null; then ok "$name"; else bad "$name"; fi
}

[[ -x "$GRAPH" ]] || chmod +x "$GRAPH"

# --- command-surface-wired: sw-doc.md ---
check "sw-doc-reconciler-entry" "$SW_DOC" "planning-graph[.]py reconcile"
check "sw-doc-scheduler-entry" "$SW_DOC" "/sw-deliver next"
check "sw-doc-posture-config" "$SW_DOC" "planning\.autonomy"
check "sw-doc-paths-helper" "$SW_DOC" "planning_paths[.]py"
check "sw-doc-no-sw-plan" "$SW_DOC" "no top-level \`/sw-plan\`"

# --- command-surface-wired: planning-graph.sh ---
check "planning-graph-next-subcommand" "$GRAPH" '== "next"'
check "planning-graph-posture-subcommand" "$GRAPH" '== "posture"'
check "planning-graph-paths-subcommand" "$GRAPH" '== "paths"'
check "planning-graph-help-reconcile" "$GRAPH" "planning-graph.py reconcile"
check "planning-graph-help-next" "$GRAPH" "planning-graph.py next"
check "planning-graph-help-posture" "$GRAPH" "planning-graph.py posture"

if diff -q "$GRAPH" "$CORE_GRAPH" >/dev/null 2>&1; then
  ok "planning-graph-core-parity"
else
  bad "planning-graph-core-parity"
fi

# --- command-surface-wired: live posture readback ---
if OUT=$(python3 "$GRAPH" posture 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('verdict')=='ok'
posture=d['posture']
assert posture['mode']=='maintenance-only'
"; then
  ok "command-surface-wired: posture-default"
else
  bad "command-surface-wired: posture-default"
fi

# --- command-surface-wired: paths helper delegation ---
if OUT=$(python3 "$GRAPH" paths dirs 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('verdict')=='pass'
assert 'planningDir' in d.get('dirs',{})
"; then
  ok "command-surface-wired: paths-dirs"
else
  bad "command-surface-wired: paths-dirs"
fi

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
