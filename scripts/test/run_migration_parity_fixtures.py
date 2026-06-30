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
# Migration parity golden fixtures — dual-run shadow per family (PRD 021 R13, TR9).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SHADOW="$ROOT/scripts/migration-parity-shadow.sh"
FIX="$ROOT/scripts/test/fixtures/migration-parity"
FAIL=0

chmod +x "$SHADOW" "$ROOT/scripts/doc-review-select.sh" "$ROOT/scripts/code-review-select.sh"

run_family() {
  local name="$1" family="$2" ctx="$3"
  set +e
  OUT=$(bash "$SHADOW" --family "$family" --context-json "$ctx" 2>&1)
  EC=$?
  set -e
  if [ "$EC" -eq 0 ]; then
    echo "OK  $name"
  else
    echo "FAIL $name"
    echo "$OUT"
    FAIL=1
  fi
}

# --- migration-parity-doc-review ---
run_family migration-parity-doc-review-core doc-review '{"version":1,"tier":"standard","phase_type":"sw-doc-review","body_snapshot":"# Minimal PRD\nPlain requirements."}'
run_family migration-parity-doc-review-security doc-review '{"version":1,"tier":"standard","phase_type":"sw-doc-review","body_snapshot":"# Auth PRD\nOAuth login and session handling."}'
run_family migration-parity-doc-review-design doc-review '{"version":1,"tier":"standard","phase_type":"sw-doc-review","body_snapshot":"# UI PRD\n## Screens\nCheckout wireframe."}'
run_family migration-parity-doc-review-requirements doc-review '{"version":1,"tier":"standard","phase_type":"sw-doc-review","body_snapshot":"# Backend PRD\n## Requirements\n- R1: Cache consistency."}'
run_family migration-parity-doc-review-quick doc-review '{"version":1,"tier":"quick","phase_type":"sw-doc-review","body_snapshot":"# Quick"}'

# --- migration-parity-code-review ---
for fixture in native-diff-minimal native-diff-selection native-diff-adversarial-50 native-diff-data-migration native-diff-reliability; do
  DIGEST=$(cat "$ROOT/scripts/test/fixtures/code-review/${fixture}.json")
  run_family "migration-parity-code-review-${fixture}" code-review "{\"version\":1,\"phase_type\":\"sw-review\",\"change_digest\":$DIGEST}"
done

# --- migration-parity-providers ---
CFG=$(python3 - <<'PY' "$ROOT/.cursor/workflow.config.json"
import json, sys
print(json.dumps({"version":1,"phase_type":"sw-ship","config":json.load(open(sys.argv[1]))}))
PY
)
run_family migration-parity-providers providers "$CFG"

# --- migration-parity-dispatch ---
run_family migration-parity-dispatch-inline dispatch '{"version":1,"file_paths":["a.ts","b.ts"],"conductor_mode":"inline"}'
run_family migration-parity-dispatch-delegate dispatch '{"version":1,"file_paths":["a.ts","b.ts","c.ts","d.ts"],"conductor_mode":"inline"}'
run_family migration-parity-dispatch-background dispatch '{"version":1,"file_paths":["a.ts"],"conductor_mode":"background_phase"}'

if [ "$FAIL" -eq 0 ]; then
  echo "ALL migration-parity fixtures passed"
else
  echo "SOME migration-parity fixtures FAILED"
  exit 1
fi

"""

if __name__ == "__main__":
    raise SystemExit(main())
