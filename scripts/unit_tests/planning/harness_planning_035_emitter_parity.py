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
# PRD 035 phase 5 — copy-to-core + emitter freshness for autonomy/pull-in/two-track artifacts (R20).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GEN="python3 -m sw"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

SCRIPTS_035=(
  planning_related.py
  planning-related.py
  planning_autonomy.py
  docs-edit-route.py
  docs-merge.py
  two_track_lib.py
  host_lib.py
)

SW_REFERENCE=(
  config.schema.json
  workflow.config.example.json
)

CONTENT_035=(
  commands/sw-prd.md
  commands/sw-tasks.md
  commands/sw-doc.md
  skills/conductor/SKILL.md
  skills/visibility/references/emission-points.md
)

# --- copy-to-core-parity-035 (R20) ---
if bash "$ROOT/scripts/copy-to-core.sh" >/dev/null 2>&1; then
  :
else
  bad "copy-to-core-parity-035: copy-to-core.sh failed"
fi

if python3 "$ROOT/scripts/unit_tests/meta/harness_core_scripts_parity.py" >/dev/null 2>&1; then
  ok "copy-to-core-parity-035: core-scripts parity"
else
  bad "copy-to-core-parity-035: core-scripts parity"
fi

for rel in "${SCRIPTS_035[@]}"; do
  if [[ -f "$ROOT/scripts/$rel" && -f "$ROOT/core/scripts/$rel" ]] && cmp -s "$ROOT/scripts/$rel" "$ROOT/core/scripts/$rel"; then
    :
  else
    bad "copy-to-core-parity-035: scripts/$rel not mirrored in core/scripts/"
    break
  fi
done

if cmp -s "$ROOT/.sw/config.schema.json" "$ROOT/core/sw-reference/config.schema.json" && \
   cmp -s "$ROOT/.sw/workflow.config.example.json" "$ROOT/core/sw-reference/workflow.config.example.json"; then
  ok "copy-to-core-parity-035: sw-reference config parity"
else
  bad "copy-to-core-parity-035: sw-reference config drift"
fi

python3 - "$ROOT" <<'PY' || bad "copy-to-core-parity-035: planning.autonomy schema"
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
for rel in (".sw/config.schema.json", "core/sw-reference/config.schema.json"):
    s = json.loads((root / rel).read_text())
    pa = s["properties"]["planning"]["properties"]["autonomy"]
    assert pa["default"] == "maintenance-only"
    assert set(pa["enum"]) == {"maintenance-only", "full-conductor"}
    fc = s["properties"]["planning"]["properties"]["fullConductor"]["properties"]
    assert "mutationBudget" in fc
for rel in (".sw/workflow.config.example.json", "core/sw-reference/workflow.config.example.json"):
    wf = json.loads((root / rel).read_text())
    assert wf["planning"]["autonomy"] == "maintenance-only"
    assert "fullConductor" in wf["planning"]
PY

[[ "$FAIL" -eq 0 ]] && ok "copy-to-core-parity-035"

# --- emitter-freshness-035 (R20) ---
$GEN generate --all >/dev/null 2>&1 || bad "emitter-freshness-035: generate failed"
HASH1=$(find "$ROOT/dist/cursor" "$ROOT/dist/claude-code" -type f -print0 | sort -z | xargs -0 shasum -a 256 | shasum -a 256 | awk '{print $1}')
$GEN generate --all >/dev/null 2>&1 || bad "emitter-freshness-035: second generate failed"
HASH2=$(find "$ROOT/dist/cursor" "$ROOT/dist/claude-code" -type f -print0 | sort -z | xargs -0 shasum -a 256 | shasum -a 256 | awk '{print $1}')
if [[ "$HASH1" == "$HASH2" ]]; then
  ok "emitter-freshness-035: generate idempotent"
else
  bad "emitter-freshness-035: generate hash drift"
fi

for dist in "$ROOT/dist/cursor" "$ROOT/dist/claude-code"; do
  for rel in "${SCRIPTS_035[@]}"; do
    if [[ ! -f "$dist/scripts/$rel" ]]; then
      bad "emitter-freshness-035: missing $dist/scripts/$rel"
    elif ! cmp -s "$ROOT/core/scripts/$rel" "$dist/scripts/$rel"; then
      bad "emitter-freshness-035: drift $dist/scripts/$rel vs core/scripts/$rel"
    fi
  done
  for rel in "${SW_REFERENCE[@]}"; do
    if [[ ! -f "$dist/core/sw-reference/$rel" ]]; then
      bad "emitter-freshness-035: missing $dist/core/sw-reference/$rel"
    elif ! cmp -s "$ROOT/core/sw-reference/$rel" "$dist/core/sw-reference/$rel"; then
      bad "emitter-freshness-035: drift $dist/core/sw-reference/$rel"
    fi
  done
done

for rel in "${CONTENT_035[@]}"; do
  if [[ ! -f "$ROOT/dist/cursor/$rel" ]]; then
    bad "emitter-freshness-035: missing dist/cursor/$rel"
  elif ! cmp -s "$ROOT/core/$rel" "$ROOT/dist/cursor/$rel"; then
    bad "emitter-freshness-035: drift dist/cursor/$rel vs core/$rel"
  fi
done

if git -C "$ROOT" diff --exit-code -- dist/cursor dist/claude-code >/dev/null 2>&1; then
  ok "emitter-freshness-035"
else
  bad "emitter-freshness-035: committed dist/ drift from generate(core/)"
fi

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
