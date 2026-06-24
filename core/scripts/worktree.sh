#!/usr/bin/env bash
# Worktree provision, scaffold allocation, safe teardown, parallelism ceiling.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_HELPER="$ROOT/scripts/phase-state.sh"

usage() {
  cat <<'EOF'
Usage:
  worktree.sh list [--json]
  worktree.sh provision <name> [--branch <branch>] [--base <ref>] [--tier T] [--workstream W]
  worktree.sh teardown <name|path> [--force]
  worktree.sh ceiling-check

Never use raw rm on a worktree path — teardown refuses unsafe deletes.
EOF
}

read_config() {
  python3 - "$ROOT" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
for candidate in (root / ".cursor/workflow.config.json", root / "workflow.config.json"):
    if candidate.is_file():
        print(candidate.read_text(encoding="utf-8"))
        break
else:
    print("{}")
PY
}

active_worktree_count() {
  python3 <<'PY'
import subprocess

try:
    out = subprocess.check_output(["git", "worktree", "list", "--porcelain"], text=True)
except subprocess.CalledProcessError:
    print(0)
    raise SystemExit

count = 0
block = {}
for line in out.splitlines():
    if not line.strip():
        if block:
            wt = block.get("worktree", "")
            if "/.pf-worktrees/" in wt:
                count += 1
            block = {}
        continue
    key, _, val = line.partition(" ")
    block[key] = val
if block:
    wt = block.get("worktree", "")
    if "/.pf-worktrees/" in wt:
        count += 1
print(count)
PY
}

allocate_port() {
  local cfg="$1"
  python3 - "$cfg" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

cfg = json.loads(sys.argv[1] or "{}")
wt = cfg.get("worktree", {})
scaffold = wt.get("scaffold", {})
start = int(scaffold.get("portRangeStart", 9100))
end = int(scaffold.get("portRangeEnd", 9199))
used = set()

try:
    out = subprocess.check_output(["git", "worktree", "list", "--porcelain"], text=True)
except subprocess.CalledProcessError:
    out = ""

def resolve_state_path(worktree: str, gitdir: str):
    if not gitdir:
        return None
    gd = Path(gitdir)
    if not gd.is_absolute():
        gd = (Path(worktree) / gd).resolve()
    else:
        gd = gd.resolve()
    return gd / "phase-flow.json"

block: dict[str, str] = {}
for line in out.splitlines():
    if not line.strip():
        if block:
            sp = resolve_state_path(block.get("worktree", ""), block.get("gitdir", ""))
            if sp and sp.is_file():
                try:
                    data = json.loads(sp.read_text(encoding="utf-8"))
                    port = data.get("scaffold", {}).get("port")
                    if isinstance(port, int):
                        used.add(port)
                except (json.JSONDecodeError, OSError):
                    pass
        block = {}
        continue
    key, _, val = line.partition(" ")
    block[key] = val
if block:
    sp = resolve_state_path(block.get("worktree", ""), block.get("gitdir", ""))
    if sp and sp.is_file():
        try:
            data = json.loads(sp.read_text(encoding="utf-8"))
            port = data.get("scaffold", {}).get("port")
            if isinstance(port, int):
                used.add(port)
        except (json.JSONDecodeError, OSError):
            pass

for port in range(start, end + 1):
    if port not in used:
        print(port)
        break
else:
    sys.exit(2)
PY
}

cmd_list() {
  local as_json="${1:-}"
  if [[ "$as_json" == "--json" ]]; then
    bash "$STATE_HELPER" index
  else
    git worktree list
  fi
}

cmd_ceiling_check() {
  local cfg count ceiling
  cfg="$(read_config)"
  count="$(active_worktree_count)"
  ceiling="$(python3 -c "import json,sys; c=json.loads(sys.argv[1] or '{}'); print(c.get('worktree',{}).get('parallelCeiling',4))" "$cfg")"
  python3 - "$count" "$ceiling" <<'PY'
import json
import sys

count = int(sys.argv[1])
ceiling = int(sys.argv[2])
# ceiling applies to .pf-worktrees slots only (main checkout excluded from count)
verdict = "ok" if count < ceiling else "at-ceiling"
print(json.dumps({"pfWorktrees": count, "ceiling": ceiling, "verdict": verdict}))
sys.exit(0 if verdict == "ok" else 10)
PY
}

cmd_provision() {
  local name="" branch="" base="" tier="standard" workstream="implementation"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --branch) branch="$2"; shift 2 ;;
      --base) base="$2"; shift 2 ;;
      --tier) tier="$2"; shift 2 ;;
      --workstream) workstream="$2"; shift 2 ;;
      -*) echo "unknown flag: $1" >&2; exit 1 ;;
      *)
        if [[ -z "$name" ]]; then
          name="$1"
        else
          echo "unexpected arg: $1" >&2
          exit 1
        fi
        shift
        ;;
    esac
  done
  [[ -n "$name" ]] || { usage >&2; exit 1; }

  local cfg
  cfg="$(read_config)"
  if ! cmd_ceiling_check >/dev/null 2>&1; then
    echo "parallel ceiling reached — run recombination before provisioning another worktree" >&2
    cmd_ceiling_check || true
    exit 10
  fi

  local parent="${base:-$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('defaultBaseBranch','main'))" "$cfg")}"
  local wt_root
  wt_root="$(git rev-parse --show-toplevel)/.pf-worktrees"
  mkdir -p "$wt_root"
  local path="$wt_root/$name"
  [[ -e "$path" ]] && {
    echo "worktree path already exists: $path" >&2
    exit 1
  }

  local new_branch="${branch:-pf/$name}"
  git fetch origin "$parent" 2>/dev/null || true
  git worktree add -b "$new_branch" "$path" "$parent"

  local port db_strategy db_template
  port="$(allocate_port "$cfg")"
  db_strategy="$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('worktree',{}).get('scaffold',{}).get('dbStrategy','schema-prefix'))" "$cfg")"
  db_template="$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('worktree',{}).get('scaffold',{}).get('dbTemplate',''))" "$cfg")"

  (
    cd "$path"
    python3 - "$name" "$path" "$tier" "$workstream" "$parent" "$new_branch" "$port" "$db_strategy" "$db_template" <<'PY' | bash "$STATE_HELPER" init -
import json
import re
import sys
from datetime import datetime, timezone

name, path, tier, workstream, parent, branch, port_s, db_strategy, db_template = sys.argv[1:10]
port = int(port_s)
print(
    json.dumps(
        {
            "worktreeName": name,
            "worktreePath": path,
            "tier": tier,
            "workstream": workstream,
            "parentBranch": parent,
            "currentBranch": branch,
            "scaffold": {
                "port": port,
                "dbStrategy": db_strategy,
                "dbTemplate": db_template,
                "dbInstance": re.sub(r"[^a-zA-Z0-9]", "_", name),
            },
            "startedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )
)
PY
  )

  python3 - "$path" "$new_branch" "$parent" "$port" "$db_strategy" <<'PY'
import json
import sys

path, branch, parent, port_s, db_strategy = sys.argv[1:6]
print(
    json.dumps(
        {
            "verdict": "provisioned",
            "path": path,
            "branch": branch,
            "parent": parent,
            "port": int(port_s),
            "dbStrategy": db_strategy,
        },
        indent=2,
    )
)
PY
}

cmd_teardown() {
  local target="" force=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --force) force="--force"; shift ;;
      -*) echo "unknown flag: $1" >&2; exit 1 ;;
      *)
        target="$1"
        shift
        ;;
    esac
  done
  [[ -n "$target" ]] || { usage >&2; exit 1; }

  if [[ "$target" == rm ]] || [[ "$target" == *" rm "* ]]; then
    echo "refused: never rm a worktree directory — use git worktree remove" >&2
    exit 2
  fi

  local path="$target"
  if [[ ! -d "$path" ]]; then
    local wt_root
    wt_root="$(git rev-parse --show-toplevel)/.pf-worktrees"
    path="$wt_root/$target"
  fi
  [[ -d "$path" ]] || {
    echo "worktree not found: $target" >&2
    exit 1
  }

  local before after
  before="$(du -sk "$path" 2>/dev/null | awk '{print $1}')"
  git worktree remove "$path" $force
  git worktree prune
  after=0
  python3 - "$path" "$before" <<'PY'
import json
import sys

path, before_s = sys.argv[1], sys.argv[2]
before = int(before_s)
print(
    json.dumps(
        {
            "verdict": "removed",
            "path": path,
            "diskReclaimedKb": max(0, before),
        },
        indent=2,
    )
)
PY
}

main() {
  chmod +x "$STATE_HELPER" 2>/dev/null || true
  local cmd="${1:-}"
  shift || true
  case "$cmd" in
    list) cmd_list "$@" ;;
    provision) cmd_provision "$@" ;;
    teardown) cmd_teardown "$@" ;;
    ceiling-check) cmd_ceiling_check ;;
    -h | --help | "") usage ;;
    *)
      echo "unknown command: $cmd" >&2
      usage >&2
      exit 1
      ;;
  esac
}

main "$@"
