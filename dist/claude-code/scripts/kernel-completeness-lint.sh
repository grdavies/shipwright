#!/usr/bin/env bash
# Kernel classification + orchestrator-step-plan completeness (PRD 024 TR8).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "$ROOT/scripts/kernel_classification_lint.py" --root "$ROOT"
python3 - "$ROOT" <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
from orchestrator_step_plan import lint_orchestrator_kernel_completeness
root = Path(sys.argv[1])
ok, missing = lint_orchestrator_kernel_completeness(root)
if not ok:
    print(json.dumps({"verdict": "fail", "failures": [f"unclassified orchestrator plan steps: {', '.join(missing)}"]}, indent=2))
    sys.exit(1)
from orchestrator_guidelines import lint_orchestrator_packs
ok_packs, pack_failures = lint_orchestrator_packs(root)
if not ok_packs:
    print(json.dumps({"verdict": "fail", "failures": pack_failures}, indent=2))
    sys.exit(1)
print(json.dumps({"verdict": "pass"}))
PY
