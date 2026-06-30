#!/usr/bin/env bash
# Worktree provision, scaffold allocation, safe teardown, parallelism ceiling.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_HELPER="$ROOT/scripts/shipwright-state.py"

usage() {
  cat <<'EOF'
Usage:
  worktree.py list [--json]
  worktree.py provision <name> [--branch <branch>] [--base <ref>] [--tier T] [--workstream W]
  worktree.py teardown <name|path> [--force]
  worktree.py ceiling-check

Never use raw rm on a worktree path — teardown refuses unsafe deletes.
EOF
}

read_config() {
  python3 - "$ROOT" <<'PY'
import json
import sys
from pathlib import Path


def strip_jsonc(text: str) -> str:
    """Strip // line and /* */ block comments that are not inside JSON strings.

    String-aware so string values such as "http://localhost:8001" are never
    truncated (a naive `//`-strip turns that into invalid JSON).
    """
    out = []
    i, n = 0, len(text)
    in_str = escape = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
            i += 1
        elif c == '"':
            in_str = True
            out.append(c)
            i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


root = Path(sys.argv[1])
for candidate in (root / ".cursor/workflow.config.json", root / "workflow.config.json"):
    if candidate.is_file():
        raw = candidate.read_text(encoding="utf-8")
        try:
            data = json.loads(strip_jsonc(raw))
        except json.JSONDecodeError:
            # Unparseable input: emit raw so the downstream consumer surfaces the
            # real error rather than silently collapsing to an empty config.
            print(raw)
            break
        print(json.dumps(data))
        break
else:
    print("{}")
PY
}

active_worktree_count() {
  python3 <<'PY'
import json
import subprocess
from pathlib import Path

def resolve_state_path(worktree: str, gitdir: str):
    if not gitdir:
        return None
    gd = Path(gitdir)
    if not gd.is_absolute():
        gd = (Path(worktree) / gd).resolve()
    else:
        gd = gd.resolve()
    return gd / "shipwright.json"

def counts_toward_ceiling(worktree: str, gitdir: str) -> bool:
    sp = resolve_state_path(worktree, gitdir)
    if sp and sp.is_file():
        try:
            data = json.loads(sp.read_text(encoding="utf-8"))
            if data.get("worktreeRole") == "orchestrator":
                return False
            if data.get("countsTowardCeiling") is False:
                return False
        except (json.JSONDecodeError, OSError):
            pass
    return True

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
            if "/.sw-worktrees/" in wt and counts_toward_ceiling(wt, block.get("gitdir", "")):
                count += 1
            block = {}
        continue
    key, _, val = line.partition(" ")
    block[key] = val
if block:
    wt = block.get("worktree", "")
    if "/.sw-worktrees/" in wt and counts_toward_ceiling(wt, block.get("gitdir", "")):
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
    return gd / "shipwright.json"

block: dict[str, str] = {}
for line in out.splitlines():
    if not line.strip():
        if block:
            sp = resolve_state_path(block.get("worktree", ""), block.get("gitdir", ""))
            if sp and sp.is_file():
                try:
                    data = json.loads(sp.read_text(encoding="utf-8"))
                    if data.get("worktreeRole") == "orchestrator" or data.get("countsTowardCeiling") is False:
                        block = {}
                        continue
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
# ceiling applies to .sw-worktrees slots only (main checkout excluded from count)
verdict = "ok" if count < ceiling else "at-ceiling"
print(json.dumps({"swWorktrees": count, "ceiling": ceiling, "verdict": verdict}))
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

  local parent="${base:-}"
  if [[ -z "$parent" ]]; then
    if [[ -x "$ROOT/scripts/resolve-base-branch.py" ]]; then
      parent="$(bash "$ROOT/scripts/resolve-base-branch.py" resolve --quiet --name-only 2>/dev/null || true)"
    fi
  fi
  if [[ -z "$parent" ]]; then
    parent="$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('defaultBaseBranch','main'))" "$cfg")"
  fi
  local wt_root
  wt_root="$(git rev-parse --show-toplevel)/.sw-worktrees"
  mkdir -p "$wt_root"
  local path="$wt_root/$name"
  [[ -e "$path" ]] && {
    echo "worktree path already exists: $path" >&2
    exit 1
  }

  # Branch-name conformance floor (PRD 007 R23/R27): never default to pf/.
  # When no explicit --branch is given, derive a conforming <type>/<slug> name;
  # always validate the final name against release-please-config.json types and
  # fail closed (with remediation) rather than minting a non-conforming branch.
  local new_branch
  if [[ -n "$branch" ]]; then
    new_branch="$branch"
  else
    new_branch="$("$ROOT/scripts/branch-name-guard.py" derive "$name")"
  fi
  if ! "$ROOT/scripts/branch-name-guard.py" validate "$new_branch"      || ! python3 "$ROOT/scripts/worktree_lib.py" validate "$new_branch" >/dev/null 2>&1; then
    echo "worktree.py: refusing non-conforming branch name '$new_branch'" >&2
    exit 12
  fi
  local host_remote; host_remote="$(python3 "$ROOT/scripts/host_lib.py" --root "$ROOT" remote-name)"
  git fetch "$host_remote" "$parent" 2>/dev/null || true
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
    wt_root="$(git rev-parse --show-toplevel)/.sw-worktrees"
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
