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
# Fixtures for PRD 002 first-run onboarding UX (phase 1: config + gate honesty).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCHEMA="$ROOT/.sw/config.schema.json"
FAIL=0

# --- config schema: doc.afterTasks + review.provider default ---
python3 - "$SCHEMA" <<'PY' || FAIL=1
import json, sys
from pathlib import Path

schema = json.loads(Path(sys.argv[1]).read_text())
props = schema["properties"]

doc = props.get("doc", {}).get("properties", {}).get("afterTasks", {})
assert doc.get("enum") == ["stop", "confirm", "auto"], doc.get("enum")
assert doc.get("default") == "confirm", doc.get("default")

review = props["review"]["properties"]
assert review["provider"]["default"] == "none", review["provider"]["default"]
assert "deprecated" in review["enabled"]["description"].lower(), review["enabled"]["description"]

example = Path(sys.argv[1]).parent / "workflow.config.example.json"
ex = json.loads(example.read_text())
assert ex.get("doc", {}).get("afterTasks") == "confirm"
assert ex.get("review", {}).get("provider") == "none"
print("OK  config-schema: doc.afterTasks + review.provider default none")
PY

# --- no literal disabled in gate emitter (root script) ---
if grep -nE 'CR_STATE="disabled"|state=disabled|case.*disabled\)' \
  "$ROOT/scripts/check-gate.py" 2>/dev/null; then
  echo "FAIL gate files still contain disabled literal"
  FAIL=1
else
  echo "OK  no disabled literal in gate emitter/fixtures"
fi

# --- gate fixtures (delegates to run-gate-fixtures) ---
python3 "$ROOT/scripts/unit_tests/meta/harness_gate.py" || FAIL=1

# --- tasks single-pass (phase 3) ---
bash "$ROOT/scripts/test/fixtures/onboarding-ux/tasks-single-pass.sh" || FAIL=1

# --- doc boundary modes (phase 4) ---
bash "$ROOT/scripts/test/fixtures/onboarding-ux/boundary-stop.sh" || FAIL=1
bash "$ROOT/scripts/test/fixtures/onboarding-ux/boundary-confirm.sh" || FAIL=1
bash "$ROOT/scripts/test/fixtures/onboarding-ux/boundary-auto.sh" || FAIL=1
bash "$ROOT/scripts/test/fixtures/onboarding-ux/boundary-no-inline.sh" || FAIL=1
bash "$ROOT/scripts/test/fixtures/onboarding-ux/boundary-guard-wire.sh" || FAIL=1

# --- setup + review docs (phase 5) ---
bash "$ROOT/scripts/test/fixtures/onboarding-ux/setup-review-choice.sh" || FAIL=1
bash "$ROOT/scripts/test/fixtures/onboarding-ux/setup-doctor-implicit-coderabbit.sh" || FAIL=1
bash "$ROOT/scripts/test/fixtures/onboarding-ux/sw-review-opt-in.sh" || FAIL=1

# --- ready + living-status review echo (phase 6) ---
bash "$ROOT/scripts/test/fixtures/onboarding-ux/ready-review-echo.sh" || FAIL=1

# --- build chain regen (phase 7) ---
bash "$ROOT/scripts/test/fixtures/onboarding-ux/build-chain-regen.sh" || FAIL=1

# --- user-facing docs (phase 8) ---
bash "$ROOT/scripts/test/fixtures/onboarding-ux/user-docs-onboarding.sh" || FAIL=1

# --- worktree guard (phase 2) ---
if [[ -f "$ROOT/scripts/sw-assert-worktree.py" ]]; then
  bash "$ROOT/scripts/test/fixtures/onboarding-ux/worktree-guard-negative.sh" || FAIL=1
  bash "$ROOT/scripts/test/fixtures/onboarding-ux/worktree-guard-positive-linked.sh" || FAIL=1
  bash "$ROOT/scripts/test/fixtures/onboarding-ux/worktree-guard-positive-hotfix.sh" || FAIL=1
  if bash "$ROOT/scripts/sw-assert-worktree.py" >/dev/null 2>&1; then
    echo "OK  worktree-guard: active worktree checkout passes"
  else
    echo "FAIL worktree-guard active worktree should pass"
    FAIL=1
  fi
else
  echo "FAIL sw-assert-worktree.py missing or not executable"
  FAIL=1
fi

# --- verify.test registration ---
WF="$ROOT/.cursor/workflow.config.json"
if python3 -c "import json; r=json.load(open('$ROOT/core/sw-reference/suite-registry.json')); assert any(s['id']=='onboarding-ux-fixtures' for s in r.get('suites',[]))" 2>/dev/null; then
  echo "OK  verify.test registers onboarding-ux runner"
else
  echo "FAIL verify.test missing onboarding-ux runner"
  FAIL=1
fi

# --- PRD 018 phase 1 portability setup fixtures ---
python3 "$ROOT/scripts/unit_tests/w4/harness_portability_setup.py" || FAIL=1

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
