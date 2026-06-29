#!/usr/bin/env bash
# Workflow push wrapper — secret scan before every git push (R50 / conductor R23 chokepoint).
# The conductor and all phase `/sw-ship` pushes MUST use this script — never raw `git push`.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$(git rev-parse --show-toplevel)"
export PYTHONPATH="$ROOT:${PYTHONPATH:-}"
if [[ -f "$ROOT/planning_materialize.py" ]]; then
  python3 "$ROOT/planning_materialize.py" --root "$PWD" guard-staged --push
fi
bash "$ROOT/secret-scan.sh" pre-push
exec git push "$@"
