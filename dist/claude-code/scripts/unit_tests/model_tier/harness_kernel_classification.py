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
# Kernel classification fixtures (PRD 022 phase 1 — R2, R3, R25, R28).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LINT="$ROOT/scripts/kernel_classification_lint.py"
FAIL=0

ok()  { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

# --- kernel-classification-completeness-lint (passing-after) ---
if OUT=$(python3 "$LINT" --root "$ROOT" 2>/dev/null) && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='pass'"; then
  ok "kernel-classification-completeness-lint passing-after"
else
  bad "kernel-classification-completeness-lint passing-after"
fi

# --- kernel-classification-completeness-lint (failing-before) ---
CLASS="$ROOT/core/sw-reference/kernel-classification.json"
BACKUP=$(mktemp)
cp "$CLASS" "$BACKUP"
python3 - <<PY
import json
from pathlib import Path
p = Path("$CLASS")
data = json.loads(p.read_text())
data['planPolicySteps'] = [s for s in data['planPolicySteps'] if s.get('id') != 'sw-execute']
p.write_text(json.dumps(data, indent=2) + "\n")
PY
if python3 "$LINT" --root "$ROOT" >/dev/null 2>&1; then
  bad "kernel-classification-completeness-lint failing-before"
else
  ok "kernel-classification-completeness-lint failing-before"
fi
cp "$BACKUP" "$CLASS"
rm -f "$BACKUP"

# --- kernel-ordering-inversion-rejected ---
if python3 - <<PY
import sys
sys.path.insert(0, "$ROOT/scripts")
from kernel_classification import load_classification, validate_chain_order
root = __import__('pathlib').Path("$ROOT")
data = load_classification(root)
inverted = [
    "sw-tmp-init", "sw-execute", "sw-commit", "sw-verify", "verification-gate",
    "sw-review", "sw-simplify", "gap-check", "sw-pr", "sw-watch-ci", "sw-stabilize", "sw-ready", "sw-tmp-clean",
]
ok, reasons = validate_chain_order(inverted, data)
assert not ok and reasons, (ok, reasons)
PY
then
  ok "kernel-ordering-inversion-rejected"
else
  bad "kernel-ordering-inversion-rejected"
fi

# --- kernel-membership-complete (passing-after) ---
if python3 - <<PY
import sys
sys.path.insert(0, "$ROOT/scripts")
from kernel_classification import canonical_ship_chain, chokepoints_reachable_before_merge_push, load_classification
from pathlib import Path
root = Path("$ROOT")
data = load_classification(root)
chain = canonical_ship_chain(root, data)
ok, missing = chokepoints_reachable_before_merge_push(data, chain)
assert ok, missing
PY
then
  ok "kernel-membership-complete passing-after"
else
  bad "kernel-membership-complete passing-after"
fi

# --- kernel-membership-complete (failing-before) ---
if python3 - <<PY
import sys
sys.path.insert(0, "$ROOT/scripts")
from kernel_classification import chokepoints_reachable_before_merge_push, load_classification
from pathlib import Path
root = Path("$ROOT")
data = load_classification(root)
bad_chain = [s for s in __import__('kernel_classification').canonical_ship_chain(root, data) if s != 'verification-gate']
ok, missing = chokepoints_reachable_before_merge_push(data, bad_chain)
assert not ok
PY
then
  ok "kernel-membership-complete failing-before"
else
  bad "kernel-membership-complete failing-before"
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "kernel-classification fixtures: all passed"
  exit 0
fi
echo "kernel-classification fixtures: $FAIL failure(s)"
exit 1

"""

if __name__ == "__main__":
    raise SystemExit(main())
