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
# Guidelines harness reuse + floor evaluator fixtures (PRD 022 phase 2 — R30, R33, R25).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LINT="$ROOT/scripts/capability-manifest-lint.sh"
FIX="$ROOT/scripts/test/fixtures/guidelines-floor"
WF="$ROOT/.cursor/workflow.config.json"
FAIL=0

ok()  { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

# --- guidelines-harness-reuse passing-after (real repo) ---
if "$LINT" >/dev/null 2>&1; then
  ok "guidelines-harness-reuse passing-after"
else
  bad "guidelines-harness-reuse passing-after"
fi

# --- guidelines-harness-reuse failing-before (invalid guidelines version) ---
GUIDE="$ROOT/core/sw-reference/guidelines.json"
BACKUP=$(mktemp)
cp "$GUIDE" "$BACKUP"
python3 - <<PY
import json
from pathlib import Path
p = Path("$GUIDE")
data = json.loads(p.read_text())
data["version"] = 99
p.write_text(json.dumps(data, indent=2) + "\n")
PY
if "$LINT" >/dev/null 2>&1; then
  bad "guidelines-harness-reuse failing-before"
else
  ok "guidelines-harness-reuse failing-before"
fi
cp "$BACKUP" "$GUIDE"
rm -f "$BACKUP"

# --- floor-mistagging-forces-review passing-after ---
if python3 - <<PY
import sys
sys.path.insert(0, "$ROOT/scripts")
from plan_floor_evaluator import validate_plan_against_floor
from kernel_classification import load_classification
from pathlib import Path

root = Path("$ROOT")
classification = load_classification(root)
signal_context = {
    "version": 1,
    "derived_tags": ["docs", "cheap"],
    "file_paths": ["auth/session.ts"],
}
plan_with_review = [
    "sw-tmp-init", "sw-execute", "sw-verify", "verification-gate",
    "sw-review", "sw-commit", "sw-pr", "sw-watch-ci", "sw-stabilize", "sw-ready", "sw-tmp-clean",
]
ok, reasons = validate_plan_against_floor(classification, plan_with_review, signal_context, ["auth/session.ts"])
assert ok, reasons
PY
then
  ok "floor-mistagging-forces-review passing-after"
else
  bad "floor-mistagging-forces-review passing-after"
fi

# --- floor-mistagging-forces-review failing-before (mis-tagged, review omitted) ---
if python3 - <<PY
import sys
sys.path.insert(0, "$ROOT/scripts")
from plan_floor_evaluator import validate_plan_against_floor
from kernel_classification import load_classification
from pathlib import Path

root = Path("$ROOT")
classification = load_classification(root)
signal_context = {
    "version": 1,
    "derived_tags": ["docs", "cheap"],
    "file_paths": ["auth/session.ts"],
}
plan_without_review = [
    "sw-tmp-init", "sw-execute", "sw-verify", "verification-gate",
    "sw-commit", "sw-pr", "sw-watch-ci", "sw-stabilize", "sw-ready", "sw-tmp-clean",
]
ok, reasons = validate_plan_against_floor(classification, plan_without_review, signal_context, ["auth/session.ts"])
assert not ok and reasons, (ok, reasons)
PY
then
  ok "floor-mistagging-forces-review failing-before"
else
  bad "floor-mistagging-forces-review failing-before"
fi

# --- triage tags alone do not trigger floor ---
if python3 - <<PY
import sys
sys.path.insert(0, "$ROOT/scripts")
from plan_floor_evaluator import validate_plan_against_floor
from kernel_classification import load_classification
from pathlib import Path

root = Path("$ROOT")
classification = load_classification(root)
signal_context = {
    "version": 1,
    "derived_tags": ["security", "auth"],
    "file_paths": [],
}
plan_without_review = [
    "sw-tmp-init", "sw-execute", "sw-verify", "verification-gate",
    "sw-commit", "sw-pr", "sw-watch-ci", "sw-stabilize", "sw-ready", "sw-tmp-clean",
]
ok, reasons = validate_plan_against_floor(classification, plan_without_review, signal_context, [])
assert ok, reasons
PY
then
  ok "floor-triage-alone-insufficient passing-after"
else
  bad "floor-triage-alone-insufficient passing-after"
fi

# --- verify.test registration ---
if grep -q 'guidelines-floor-fixtures' "$ROOT/core/sw-reference/suite-registry.json" && grep -q 'scripts/unit_tests/guidelines' "$ROOT/core/sw-reference/suite-registry.json" 2>/dev/null; then
  ok "guidelines-floor-verify-registration"
else
  bad "guidelines-floor-verify-registration"
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "guidelines-floor fixtures: all passed"
  exit 0
fi
echo "guidelines-floor fixtures: $FAIL failure(s)"
exit 1

"""

if __name__ == "__main__":
    raise SystemExit(main())
