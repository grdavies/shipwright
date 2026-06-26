#!/usr/bin/env bash
# Per-worktree Shipwright state — resolve path, read, write, aggregate index.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage:
  shipwright-state.sh path              Print resolved state file path for current checkout
  shipwright-state.sh read              Print state JSON (empty object if missing)
  shipwright-state.sh write <json|-)>   Merge JSON object into state file (- = stdin)
  shipwright-state.sh override-add <json|-)>  Append one override record (read-modify-write)
  shipwright-state.sh dispatch-override-add <json|-)>  Append one dispatch override audit record
  shipwright-state.sh init <json|-)>    Replace state file with JSON object (- = stdin)
  shipwright-state.sh sync-ship-steps   Merge phaseShip from durable ship-steps.json into state
  shipwright-state.sh index             Aggregate state from all linked worktrees (read-only)
EOF
}

resolve_state_path() {
  local git_dir
  git_dir="$(git rev-parse --git-dir 2>/dev/null)" || {
    echo "error: not a git repository" >&2
    return 1
  }
  if [[ "$git_dir" != /* ]]; then
    git_dir="$(cd "$git_dir" && pwd)"
  fi
  echo "${git_dir}/shipwright.json"
}

read_json_arg() {
  local arg="${1:-}"
  if [[ "$arg" == "-" ]]; then
    cat
  else
    printf '%s' "$arg"
  fi
}

cmd_path() {
  resolve_state_path
}

cmd_read() {
  local state
  state="$(resolve_state_path)"
  if [[ -f "$state" ]]; then
    cat "$state"
  else
    echo '{}'
  fi
}

cmd_write() {
  local patch
  patch="$(read_json_arg "${1:-}")"
  local state
  state="$(resolve_state_path)"
  mkdir -p "$(dirname "$state")"
  PATCH_JSON="$patch" python3 - "$state" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
patch = json.loads(os.environ["PATCH_JSON"])
current = {}
if path.exists():
    current = json.loads(path.read_text(encoding="utf-8"))
current.update(patch)
path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  echo "$state"
}

cmd_override_add() {
  local entry
  entry="$(read_json_arg "${1:-}")"
  local state
  state="$(resolve_state_path)"
  mkdir -p "$(dirname "$state")"
  ENTRY_JSON="$entry" python3 - "$state" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
entry = json.loads(os.environ["ENTRY_JSON"])
current = {}
if path.exists():
    current = json.loads(path.read_text(encoding="utf-8"))
overrides = current.get("overrides")
if not isinstance(overrides, list):
    overrides = []
overrides.append(entry)
current["overrides"] = overrides
path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  echo "$state"
}

cmd_dispatch_override_add() {
  local entry
  entry="$(read_json_arg "${1:-}")"
  local state
  state="$(resolve_state_path)"
  mkdir -p "$(dirname "$state")"
  ENTRY_JSON="$entry" python3 - "$state" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
entry = json.loads(os.environ["ENTRY_JSON"])
required = ("actor", "timestamp", "dispatchId", "skippedFields")
missing = [k for k in required if k not in entry]
if missing:
    print(json.dumps({"verdict": "fail", "error": "missing fields", "missing": missing}))
    raise SystemExit(2)
if not isinstance(entry.get("skippedFields"), list) or not entry.get("skippedFields"):
    print(json.dumps({"verdict": "fail", "error": "skippedFields must be a non-empty list"}))
    raise SystemExit(2)
current = {}
if path.exists():
    current = json.loads(path.read_text(encoding="utf-8"))
records = current.get("dispatchOverrides")
if not isinstance(records, list):
    records = []
records.append(entry)
current["dispatchOverrides"] = records
path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps({"verdict": "pass", "count": len(records)}))
PY
  echo "$state"
}

cmd_init() {
  local body
  body="$(read_json_arg "${1:-}")"
  local state
  state="$(resolve_state_path)"
  mkdir -p "$(dirname "$state")"
  printf '%s\n' "$body" >"$state"
  echo "$state"
}

cmd_sync_ship_steps() {
  local state steps_py sync_out
  state="$(resolve_state_path)"
  steps_py="$ROOT/scripts/ship-phase-steps.sh"
  if [[ ! -x "$steps_py" ]]; then
    echo "error: ship-phase-steps.sh missing" >&2
    return 1
  fi
  sync_out="$(bash "$steps_py" sync-state 2>/dev/null)" || {
    echo "error: ship-phase-steps sync-state failed" >&2
    return 1
  }
  PATCH_JSON="$sync_out" python3 - "$state" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
raw = json.loads(os.environ["PATCH_JSON"])
phase_ship = raw.get("phaseShip")
if not phase_ship:
    sys.exit(0)
current = {}
if path.exists():
    current = json.loads(path.read_text(encoding="utf-8"))
current["phaseShip"] = phase_ship
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  echo "$state"
}

cmd_index() {
  python3 - "$ROOT" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])


def resolve_state_path(worktree: str, gitdir: str):
    if not gitdir:
        return None
    gd = Path(gitdir)
    if not gd.is_absolute():
        gd = (Path(worktree) / gd).resolve()
    else:
        gd = gd.resolve()
    return gd / "shipwright.json"


try:
    out = subprocess.check_output(
        ["git", "-C", str(root), "worktree", "list", "--porcelain"],
        text=True,
    )
except subprocess.CalledProcessError:
    out = ""

entries = []
block = {}
for line in out.splitlines():
    if not line.strip():
        if block:
            entries.append(block)
            block = {}
        continue
    key, _, val = line.partition(" ")
    block[key] = val
if block:
    entries.append(block)

index = []
for e in entries:
    wt_path = e.get("worktree", "")
    gitdir = e.get("gitdir", "")
    state_path = resolve_state_path(wt_path, gitdir)
    state = {}
    if state_path and state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state = {"error": "invalid-json"}
    index.append(
        {
            "worktree": wt_path,
            "branch": e.get("branch", "").lstrip("refs/heads/"),
            "statePath": str(state_path) if state_path else None,
            "state": state,
        }
    )

print(json.dumps({"worktrees": index}, indent=2))
PY
}

main() {
  local cmd="${1:-}"
  shift || true
  case "$cmd" in
    path) cmd_path ;;
    read) cmd_read ;;
    write)
      [[ $# -ge 1 ]] || { usage >&2; exit 1; }
      cmd_write "$1"
      ;;
    override-add)
      [[ $# -ge 1 ]] || { usage >&2; exit 1; }
      cmd_override_add "$1"
      ;;
    dispatch-override-add)
      [[ $# -ge 1 ]] || { usage >&2; exit 1; }
      cmd_dispatch_override_add "$1"
      ;;
    init)
      [[ $# -ge 1 ]] || { usage >&2; exit 1; }
      cmd_init "$1"
      ;;
    sync-ship-steps) cmd_sync_ship_steps ;;
    index) cmd_index ;;
    -h | --help | "") usage ;;
    *)
      echo "unknown command: $cmd" >&2
      usage >&2
      exit 1
      ;;
  esac
}

main "$@"
