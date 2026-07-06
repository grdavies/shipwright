#!/usr/bin/env python3
"""PRD 056 Phase 4 — deliver provision hierarchy wiring fixtures (R5, R9, R10)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
_SCRIPTS_ROOT = SCRIPT_DIR.parents[1]
_TEST_DIR = _SCRIPTS_ROOT / "test"
for _entry in (str(_TEST_DIR), str(_SCRIPTS_ROOT)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from _sw.vendor_paths import repo_root
from unit_tests._harness_runtime import harness_subprocess_env as _harness_env
from unit_tests._harness_runtime import patch_source as _patch_source


def main() -> int:
    root = repo_root(__file__)
    env = _harness_env(root)
    src = _patch_source(_SOURCE, root)
    completed = subprocess.run(["bash", "-c", src], cwd=str(root), env=env, shell=False)
    return completed.returncode


_SOURCE = r"""
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT/scripts:${PYTHONPATH:-}"
export SW_ISSUES_FIXTURE=1
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

if python3 - <<'PY'
import json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts")
import planning_progress as pp
from issues_lib import FixtureIssuesStore

tmp = Path(tempfile.mkdtemp())
import subprocess
subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp, check=True)
subprocess.run(["git", "config", "user.name", "T"], cwd=tmp, check=True)
(tmp / ".cursor" / "hooks" / "state").mkdir(parents=True)
(tmp / "docs" / "prds" / "056-test").mkdir(parents=True)
(tmp / "docs/prds/056-test/tasks-056-test.md").write_text(
    "---\nfrozen: true\n---\n### 1. Alpha phase\n### 2. Beta phase\n",
    encoding="utf-8",
)
(tmp / ".cursor/workflow.config.json").write_text(json.dumps({
    "version": 1,
    "planning": {"store": {"backend": "in-repo-public"}},
}), encoding="utf-8")
state = {"source_task_list": "docs/prds/056-test/tasks-056-test.md"}
import planning_hierarchy as ph
hierarchy_calls = []
orig = ph.project_task_list_hierarchy
def track(*a, **k):
    hierarchy_calls.append(1)
    return orig(*a, **k)
ph.project_task_list_hierarchy = track
out = pp.provision_deliver_hierarchy(tmp, state)
assert out.get("skipped") and out.get("notice"), out
assert not hierarchy_calls, hierarchy_calls
assert "hierarchyMap" not in state
print("file-store-skip-ok")
PY
then
  ok "file-store:no-hierarchy-calls"
else
  bad "file-store:no-hierarchy-calls"
fi

if python3 - <<'PY'
import json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts")
import planning_progress as pp
from issues_lib import FixtureIssuesStore
from wave_state import load_hierarchy_map

tmp = Path(tempfile.mkdtemp())
import subprocess
subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp, check=True)
subprocess.run(["git", "config", "user.name", "T"], cwd=tmp, check=True)
(tmp / ".cursor" / "hooks" / "state").mkdir(parents=True)
(tmp / "docs" / "prds" / "056-test").mkdir(parents=True)
(tmp / "docs/prds/056-test/tasks-056-test.md").write_text(
    "---\nfrozen: true\n---\n### 1. Alpha phase\n### 2. Beta phase\n",
    encoding="utf-8",
)
(tmp / ".cursor/workflow.config.json").write_text(json.dumps({
    "version": 1,
    "planning": {
        "store": {
            "backend": "issue-store",
            "issuesProvider": "github-issues",
            "projectKey": "deliver-progress-056",
        }
    },
    "host": {"provider": "github"},
}), encoding="utf-8")
os.environ["SW_ISSUES_FIXTURE"] = "1"
fixture_path = tmp / ".cursor/hooks/state/issue-store-fixture.json"
if fixture_path.is_file():
    fixture_path.unlink()
state = {"source_task_list": "docs/prds/056-test/tasks-056-test.md"}
out = pp.provision_deliver_hierarchy(tmp, state)
assert out.get("verdict") == "ok" and out.get("applied"), out
hmap = load_hierarchy_map(state)
assert hmap.get("epicIssueId"), hmap
assert hmap.get("mode") == "epic-sub-issue", hmap
assert len(hmap.get("phases") or {}) == 2, hmap
store = FixtureIssuesStore(fixture_path)
issues = list(store._issues.values())
assert len(issues) == 3, len(issues)
epic = next(i for i in issues if i.unit_id == "056-test")
subs = [i for i in issues if (i.unit_id or "") != "056-test"]
assert len(subs) == 2, [i.unit_id for i in issues]
out2 = pp.provision_deliver_hierarchy(tmp, state)
assert out2.get("idempotent"), out2
print("issue-store-hierarchy-ok")
PY
then
  ok "issue-store:epic-and-sub-issues"
else
  bad "issue-store:epic-and-sub-issues"
fi

exit "$FAIL"
"""

if __name__ == "__main__":
    raise SystemExit(main())
