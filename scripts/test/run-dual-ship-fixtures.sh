#!/usr/bin/env bash
# PRD 036 R18 — dual-ship regression: concurrent lease + pr-create on one head → exactly one PR.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SHIPWRIGHT_ROOT="$(git -C "$ROOT" rev-parse --git-common-dir 2>/dev/null | xargs dirname 2>/dev/null || echo "$ROOT")"
# When running from a worktree, SHIPWRIGHT_ROOT may be the main repo; prefer explicit plugin scripts.
PLUGIN_SCRIPTS="${SHIPWRIGHT_ROOT}/scripts"
[[ -f "$ROOT/scripts/wave_lock.py" ]] && PLUGIN_SCRIPTS="$ROOT/scripts"
FAIL=0

ok()   { echo "OK  $1"; }
bad()  { echo "FAIL $1"; FAIL=1; }

FIX=$(mktemp -d)
trap 'rm -rf "$FIX"' EXIT

cd "$FIX"
git init -q
git config user.email test@test.com
git config user.name Test
git commit --allow-empty -q -m init
git branch -M main
git branch feat/integration
git branch feat/phase-head

mkdir -p .cursor scripts/test/fixtures/host
cp "$ROOT/.cursor/workflow.config.json" .cursor/workflow.config.json 2>/dev/null || echo '{"host":{"provider":"github","remote":"origin"}}' > .cursor/workflow.config.json
cp -R "${PLUGIN_SCRIPTS}/test/fixtures/host/"* scripts/test/fixtures/host/ 2>/dev/null || cp -R "${SHIPWRIGHT_ROOT}/scripts/test/fixtures/host/"* scripts/test/fixtures/host/
for f in host_lib.py host_invoke.py host_token.py wave_json_io.py wave_state.py plan_persist.py pilot_dependency_gate.py; do
  cp "${PLUGIN_SCRIPTS}/$f" scripts/ 2>/dev/null || cp "${SHIPWRIGHT_ROOT}/scripts/$f" scripts/ 2>/dev/null || true
done
cat >.cursor/sw-deliver-state.integration.json <<'EOF'
{
  "verdict": "running",
  "target": {"branch": "feat/integration"},
  "phases": {
    "1": {
      "slug": "ship-single-flight-r1-r5-l",
      "branch": "feat/phase-head",
      "status": "in-flight"
    }
  }
}
EOF

export SW_HOST_FIXTURE=green
export SW_PHASE_MODE=1
export SW_PHASE_SLUG=ship-single-flight-r1-r5-l
export SW_INTEGRATION_BRANCH=feat/integration
export SW_PHASE_BRANCH=feat/phase-head

if python3 - "$ROOT" "$FIX" <<'PY'
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

root_scripts = Path(sys.argv[1]) / "scripts"
fix = Path(sys.argv[2])
sys.path.insert(0, str(root_scripts))
os.chdir(fix)

from wave_lock import acquire_ship_lease, release_ship_lease
from wave_phase_pr import create_or_reuse_phase_pr

integration = "feat/integration"
head = "feat/phase-head"
args = ["--integration", integration, "--phase-branch", head]

results: list[dict] = []
barrier = threading.Barrier(2)

def contender(tag: str) -> dict:
    barrier.wait(timeout=5)
    lease = acquire_ship_lease(fix, args)
    if lease.get("verdict") != "pass":
        return {"tag": tag, "lease": "refused", "leaseOut": lease}
    time.sleep(0.25)
    try:
        pr = create_or_reuse_phase_pr(
            fix,
            phase_slug="ship-single-flight-r1-r5-l",
            head=head,
            title=f"phase pr {tag}",
            body="dual-ship fixture",
        )
        return {"tag": tag, "lease": "held", "pr": pr}
    finally:
        release_ship_lease(fix, args)

with ThreadPoolExecutor(max_workers=2) as pool:
    futs = [pool.submit(contender, t) for t in ("a", "b")]
    for fut in as_completed(futs):
        results.append(fut.result())

held = [r for r in results if r.get("lease") == "held"]
refused = [r for r in results if r.get("lease") == "refused"]
if len(held) != 1 or len(refused) != 1:
    print(json.dumps({"error": "lease-race", "results": results}))
    sys.exit(1)

pr_numbers = {
    r["pr"].get("number")
    for r in held
    if r.get("pr", {}).get("verdict") == "ok"
}
if len(pr_numbers) != 1:
    print(json.dumps({"error": "pr-count", "held": held}))
    sys.exit(1)

state = json.loads(
    Path(".cursor/sw-deliver-state.integration.json").read_text()
)
open_pr = state["phases"]["1"].get("openPrNumber")
if open_pr not in pr_numbers:
    print(json.dumps({"error": "openPrNumber", "open_pr": open_pr, "pr_numbers": list(pr_numbers)}))
    sys.exit(1)

print(json.dumps({"verdict": "pass", "held": len(held), "refused": len(refused), "pr": list(pr_numbers)[0], "openPrNumber": open_pr}))
PY
then
  ok "dual-ship-exactly-one-pr"
else
  bad "dual-ship-exactly-one-pr"
fi

exit "$FAIL"
