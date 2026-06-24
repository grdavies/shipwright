#!/usr/bin/env bash
# Wave plan + integration helpers.
# Usage:
#   wave.sh plan --items 'A,B,C' --edges 'C:A'
#   wave.sh integration --stamp <stamp> --branches 'branch1,branch2'
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CMD="${1:-}"
shift || true

exec python3 - "$ROOT" "$CMD" "$@" <<'PY'
import json, sys
from collections import defaultdict, deque
from pathlib import Path

root, cmd = sys.argv[1], sys.argv[2]
args = sys.argv[3:]

def parse_kv(flag, default=None):
    if flag in args:
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else default
    return default

if cmd == "plan":
    items_raw = parse_kv("--items", "")
    edges_raw = parse_kv("--edges", "")
    items = [x.strip() for x in items_raw.split(",") if x.strip()]
    edges = []
    for pair in [x.strip() for x in edges_raw.split(",") if x.strip()]:
        if ":" not in pair:
            print(json.dumps({"error": f"invalid edge {pair!r}, want item:dependency"}))
            sys.exit(2)
        item, dep = pair.split(":", 1)
        edges.append({"from": dep.strip(), "to": item.strip()})

    item_set = set(items)
    indeg = {i: 0 for i in items}
    adj = defaultdict(list)
    for e in edges:
        if e["from"] not in item_set or e["to"] not in item_set:
            print(json.dumps({"error": f"edge references unknown item: {e}"}))
            sys.exit(2)
        adj[e["from"]].append(e["to"])
        indeg[e["to"]] += 1

    q = deque([i for i in items if indeg[i] == 0])
    order = []
    while q:
        n = q.popleft()
        order.append(n)
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                q.append(m)
    if len(order) != len(items):
        print(json.dumps({"verdict": "fail", "error": "dependency cycle detected"}))
        sys.exit(20)

    waves = []
    remaining = set(items)
    deps = {i: {e["from"] for e in edges if e["to"] == i} for i in items}
    while remaining:
        wave = sorted([i for i in remaining if not (deps[i] & remaining)])
        if not wave:
            print(json.dumps({"verdict": "fail", "error": "unable to assign wave"}))
            sys.exit(20)
        waves.append(wave)
        remaining -= set(wave)

    out = {
        "verdict": "pass",
        "items": [{"id": i, "branch": f"pf/{i}"} for i in items],
        "edges": edges,
        "waves": waves,
        "contention": {"serialized": ["docs/prds/INDEX.md", "docs/decisions/INDEX.md", "doc-numbering"]},
    }
    plan_path = Path(root) / ".cursor" / "sw-wave-plan.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(0)

elif cmd == "integration":
    stamp = parse_kv("--stamp")
    branches_raw = parse_kv("--branches", "")
    if not stamp:
        print(json.dumps({"error": "--stamp required"}))
        sys.exit(2)
    branches = [b.strip() for b in branches_raw.split(",") if b.strip()]
    print(json.dumps({
        "verdict": "pass",
        "integrationBranch": f"integration/{stamp}",
        "mergedBranches": branches,
        "note": "merge + whole-suite check delegated to orchestrator",
    }))
    sys.exit(0)

else:
    print(json.dumps({"error": f"unknown command: {cmd}"}))
    sys.exit(2)
PY
