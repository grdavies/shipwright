#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec python3 "$ROOT/scripts/test/run_pytest.py" scripts/unit_tests/planning/test_planning_047_phase2.py -q
