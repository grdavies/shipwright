#!/usr/bin/env bash
# PRD 045 doc-impact gate — delegates to pytest harness (R49); phases 1–3.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec python3 "$ROOT/scripts/test/run_pytest.py" scripts/unit_tests/planning/test_planning_045_doc_impact.py -q
