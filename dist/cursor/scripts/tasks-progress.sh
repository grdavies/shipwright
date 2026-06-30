#!/usr/bin/env bash
# Toggle task checkboxes on frozen task files; reject non-checkbox edits (R13/R14).
#
# Usage:
#   tasks-progress.py toggle --file PATH --ref TASK_REF [--done true|false]
#   tasks-progress.py check-diff --old PATH --new PATH
#   tasks-progress.py parse --file PATH
#
# Exit: 0 pass; 1 rejected edit; 2 usage error
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CB="$ROOT/scripts/checkbox_diff.py"

usage() {
  sed -n '2,8p' "$0"
}

FILE=""
REF=""
DONE=""
OLD=""
NEW=""
CMD="${1:-}"
shift || true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --file) FILE="${2:-}"; shift 2 ;;
    --ref) REF="${2:-}"; shift 2 ;;
    --done) DONE="${2:-}"; shift 2 ;;
    --old) OLD="${2:-}"; shift 2 ;;
    --new) NEW="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo '{"verdict":"fail","error":"unknown argument"}' >&2; exit 2 ;;
  esac
done

case "$CMD" in
  toggle)
    [[ -n "$FILE" && -n "$REF" && -f "$FILE" ]] || { usage >&2; exit 2; }
  python3 - "$FILE" "$REF" "$DONE" "$CB" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[4]).parent))
from checkbox_diff import is_checkbox_only_diff, toggle_checkbox

path = Path(sys.argv[1])
ref = sys.argv[2]
done_arg = sys.argv[3]
old = path.read_text(encoding="utf-8")
done = None
if done_arg in ("true", "false"):
    done = done_arg == "true"
try:
    new = toggle_checkbox(old, ref, done)
except ValueError as exc:
    print(json.dumps({"verdict": "fail", "error": str(exc)}))
    sys.exit(1)
if not is_checkbox_only_diff(old, new):
    print(json.dumps({"verdict": "fail", "error": "non-checkbox edit rejected"}))
    sys.exit(1)
path.write_text(new, encoding="utf-8")
print(json.dumps({"verdict": "pass", "action": "toggle", "ref": ref, "file": str(path)}))
PY
    ;;
  check-diff)
    [[ -n "$OLD" && -n "$NEW" && -f "$OLD" && -f "$NEW" ]] || { usage >&2; exit 2; }
    if python3 "$CB" is-checkbox-only "$OLD" "$NEW" >/dev/null; then
      echo '{"verdict":"pass","checkboxOnly":true}'
    else
      echo '{"verdict":"fail","checkboxOnly":false}'
      exit 1
    fi
    ;;
  parse)
    [[ -n "$FILE" && -f "$FILE" ]] || { usage >&2; exit 2; }
    python3 - "$FILE" "$ROOT" <<'PY'
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[2]) / "scripts"))
from checkbox_diff import parse_task_checkboxes

path = Path(sys.argv[1])
boxes = parse_task_checkboxes(path.read_text(encoding="utf-8"))
print(json.dumps({"verdict": "pass", "checkboxes": boxes}))
PY
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
