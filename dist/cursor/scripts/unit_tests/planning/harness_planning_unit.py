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
# Planning-unit schema + validator fixtures (PRD 031 phase 3).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT/scripts:$ROOT/core/scripts"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

SCHEMA="$ROOT/core/sw-reference/planning-unit.schema.json"
LAYOUT="$ROOT/core/sw-reference/layout.md"
VALIDATOR="$ROOT/scripts/planning-unit-validate.sh"
FIX_SRC="$ROOT/scripts/test/fixtures/planning-unit"

# --- schema-fields-and-type-enum (R1) ---
if [[ -f "$SCHEMA" ]] && \
   python3 - "$SCHEMA" <<'PY'
import json, sys
schema = json.load(open(sys.argv[1]))
props = schema.get("properties", {})
required = {"id", "type", "status", "title", "visibility", "depends", "blocks",
            "supersedes", "extends", "absorbs", "priority", "tags"}
missing = required - set(props)
if missing:
    raise SystemExit(f"missing properties: {missing}")
types = set(props["type"]["enum"])
expected = {"brainstorm", "gap", "prd", "decision", "amendment"}
if types != expected:
    raise SystemExit(f"type enum mismatch: {types}")
if schema.get("additionalProperties") is not False:
    raise SystemExit("additionalProperties must be false")
print("ok")
PY
then
  ok "schema-fields-and-type-enum"
else
  bad "schema-fields-and-type-enum"
fi

# --- unit-folder-and-id-stability (R2) ---
if grep -q 'Unit folder layout' "$LAYOUT" && \
   grep -q 'never reused' "$LAYOUT" && \
   grep -q 'unit id' "$LAYOUT" && \
   grep -q 'amendments/' "$LAYOUT"; then
  ok "unit-folder-and-id-stability"
else
  bad "unit-folder-and-id-stability"
fi

# --- gap-unit-in-unified-index (R3) ---
if grep -q 'type: gap' "$LAYOUT" && \
   grep -q 'single generated unified INDEX' "$LAYOUT" && \
   grep -q 'not a separate gap-only' "$LAYOUT"; then
  ok "gap-unit-in-unified-index"
else
  bad "gap-unit-in-unified-index"
fi

# --- status-type-conditioned (R4) ---
if python3 <<'PY'
import planning_status_enum as pse
assert pse.validate_status("gap", "open") is None
assert pse.validate_status("gap", "planned") is None
assert pse.validate_status("prd", "planned") is None
assert pse.validate_status("prd", "proposed") is None
assert "homonym" in pse.PLANNED_HOMONYM_NOTE
print("ok")
PY
then
  ok "status-type-conditioned"
else
  bad "status-type-conditioned"
fi

# --- cross-enum-token-rejected (R4) ---
if python3 <<'PY'
import planning_status_enum as pse
assert pse.validate_status("gap", "in-progress") is not None
assert pse.validate_status("prd", "open") is not None
print("ok")
PY
then
  ok "cross-enum-token-rejected"
else
  bad "cross-enum-token-rejected"
fi

# --- status-enum-stub (R4) — PRD 033: transitions live in planning_lifecycle ---
if python3 <<'PY'
import planning_lifecycle as plc
import planning_status_enum as pse
assert "TRANSITION_CLASSIFICATION" in dir(plc)
assert plc.transition_kind("proposed", "planned") == "freeze-gate"
assert len(pse.GAP_STATUSES) == 4
assert len(pse.LIFECYCLE_STATUSES) == 8
print("ok")
PY
then
  ok "status-enum-stub"
else
  bad "status-enum-stub"
fi

# --- validate-unknown-key (R19) ---
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cp "$FIX_SRC/unknown-key.md" "$TMP/unknown-key.md"
if OUT=$(bash "$VALIDATOR" --path "$TMP/unknown-key.md" --repo-root "$ROOT" 2>/dev/null || true) && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='fail'; assert any('unknown key' in e for e in d.get('errors',[]))"; then
  ok "validate-unknown-key"
else
  bad "validate-unknown-key"
fi

# --- validate-tracked-private-rejected (R19) ---
if OUT=$(bash "$VALIDATOR" --path "$FIX_SRC/private-tracked.md" --repo-root "$ROOT" 2>/dev/null || true) && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='fail'"; then
  ok "validate-tracked-private-rejected"
else
  bad "validate-tracked-private-rejected"
fi

# --- validate-valid-units-pass (R19) ---
if OUT=$(bash "$VALIDATOR" --path "$FIX_SRC/valid-gap.md" --repo-root "$ROOT" 2>/dev/null) && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='pass'"; then
  ok "validate-valid-units-pass"
else
  bad "validate-valid-units-pass"
fi

# --- validate-cross-enum-rejected (R19) ---
cp "$FIX_SRC/cross-enum.md" "$TMP/cross-enum.md"
if OUT=$(bash "$VALIDATOR" --path "$TMP/cross-enum.md" --repo-root "$ROOT" 2>/dev/null || true) && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='fail'"; then
  ok "validate-cross-enum-rejected"
else
  bad "validate-cross-enum-rejected"
fi

exit $FAIL

"""

if __name__ == "__main__":
    raise SystemExit(main())
