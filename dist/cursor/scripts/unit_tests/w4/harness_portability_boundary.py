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
# Fixtures for PRD 018 Phase 2 — clean install / dev-product boundary.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

EXAMPLE="$ROOT/core/sw-reference/workflow.config.example.json"
SW_EXAMPLE="$ROOT/.sw/workflow.config.example.json"
DIST_CURSOR="$ROOT/dist/cursor"
DEV_SCRIPTS=(copy-to-core.py snapshot-tree.py model-routing-check.py)
CLOSED_SWREF=(
  config.schema.json
  layout.md
  workflow.config.example.json
  communication-routing.defaults.json
  model-routing.defaults.json
  verify-presets.json
)

# --- example-config-neutral ---
if [[ -f "$EXAMPLE" ]] && \
   grep -q 'verify-require-configuration.py' "$EXAMPLE" && \
   ! grep -q 'run-pr-test-plan-manifest.py' "$EXAMPLE" && \
   ! grep -q 'prTestPlanManifest' "$EXAMPLE" && \
   grep -q 'http://localhost:8001' "$EXAMPLE"; then
  ok "example-config-neutral"
else
  bad "example-config-neutral"
fi

# --- dist-excludes-dev-scripts ---
MISSING=0
for script in "${DEV_SCRIPTS[@]}"; do
  if [[ -f "$DIST_CURSOR/scripts/$script" ]]; then
    bad "dist-excludes-dev-scripts: dist still ships scripts/$script"
    MISSING=1
  fi
done
[[ "$MISSING" -eq 0 ]] && ok "dist-excludes-dev-scripts"

# --- no-shipped-ref-to-dev-scripts ---
REF_FAIL=0
while IFS= read -r -d '' f; do
  for script in "${DEV_SCRIPTS[@]}"; do
    if grep -q "scripts/$script" "$f" 2>/dev/null; then
      bad "no-shipped-ref-to-dev-scripts: $(echo "$f" | sed "s|$ROOT/||") references scripts/$script"
      REF_FAIL=1
    fi
  done
done < <(find "$ROOT/core/commands" "$ROOT/core/skills" "$ROOT/core/rules" -type f \( -name '*.md' -o -name '*.mdc' \) -print0 2>/dev/null)
[[ "$REF_FAIL" -eq 0 ]] && ok "no-shipped-ref-to-dev-scripts"

# --- swref-closed-emit-and-tolerance ---
EMIT_FAIL=0
for name in "${CLOSED_SWREF[@]}"; do
  if [[ ! -f "$DIST_CURSOR/core/sw-reference/$name" ]]; then
    bad "swref-closed-emit-and-tolerance: missing dist core/sw-reference/$name"
    EMIT_FAIL=1
  fi
done
if python3 "$ROOT/scripts/sw-configure.py" schema-version >/dev/null 2>&1; then
  :
else
  bad "swref-closed-emit-and-tolerance: sw-configure schema-version failed"
  EMIT_FAIL=1
fi
[[ "$EMIT_FAIL" -eq 0 ]] && ok "swref-closed-emit-and-tolerance"

# --- dev-repo-marker ---
if [[ -f "$ROOT/.shipwright-dev" ]] && \
   python3 "$ROOT/scripts/is-shipwright-dev-repo.py" "$ROOT"; then
  ok "dev-repo-marker"
else
  bad "dev-repo-marker"
fi

# --- install-offers-init-in-repo ---
if grep -q '/sw-init' "$ROOT/scripts/install.py" && \
   grep -q 'workflow.config.json' "$ROOT/scripts/install.py" && \
   ! grep -q 'sw-configure.py' "$ROOT/scripts/install.py"; then
  ok "install-offers-init-in-repo"
else
  bad "install-offers-init-in-repo"
fi

if [[ "$FAIL" -ne 0 ]]; then
  echo "run-portability-boundary-fixtures: FAIL"
  exit 1
fi
echo "run-portability-boundary-fixtures: PASS"

"""

if __name__ == "__main__":
    raise SystemExit(main())
