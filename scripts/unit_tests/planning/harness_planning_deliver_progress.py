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
    "---\nfrozen: true\n---\n### 1. Alpha phase\n- [ ] 1.1 First task\n### 2. Beta phase\n- [ ] 2.1 Second task\n",
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
assert out.get("applied"), out
hmap = load_hierarchy_map(state)
phase1 = (hmap.get("phases") or {}).get("1")
assert phase1 and phase1.get("issueId"), hmap
sync1 = pp.sync_phase_done(tmp, state, "1")
assert sync1.get("synced") and sync1.get("label") == "sw:phase:1:done", sync1
store = FixtureIssuesStore(fixture_path)
issue = store.get(str(phase1["issueId"]))
assert "sw:phase:1:done" in issue.labels, issue.labels
sync2 = pp.sync_phase_done(tmp, state, "1")
assert sync2.get("idempotent"), sync2
print("phase-green-label-ok")
PY
then
  ok "issue-store:phase-green-label"
else
  bad "issue-store:phase-green-label"
fi

if python3 - <<'PY'
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts")
import planning_progress as pp

tmp = Path(tempfile.mkdtemp())
(tmp / ".cursor").mkdir(parents=True)
(tmp / ".cursor/workflow.config.json").write_text(json.dumps({
    "version": 1,
    "planning": {"store": {"backend": "in-repo-public"}},
}), encoding="utf-8")
state = {
    "hierarchyMap": {
        "applied": True,
        "phases": {"1": {"issueId": "x", "phaseId": "1"}},
    }
}
out = pp.sync_phase_done(tmp, state, "1")
assert out.get("skipped") and out.get("reason") == "file-store", out
out2 = pp.sync_task_checkbox(tmp, state, phase_id="1", task_list="missing.md")
assert out2.get("skipped") and out2.get("reason") == "file-store", out2
print("file-store-sync-skip-ok")
PY
then
  ok "file-store:sync-phase-noop"
else
  bad "file-store:sync-phase-noop"
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
task_rel = "docs/prds/056-test/tasks-056-test.md"
(tmp / task_rel).write_text(
    "---\nfrozen: true\n---\n### 1. Alpha phase\n- [ ] 1.1 First task\n### 2. Beta phase\n",
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
state = {"source_task_list": task_rel, "phases": {"1": {"slug": "alpha-phase"}}}
pp.provision_deliver_hierarchy(tmp, state)
hmap = load_hierarchy_map(state)
phase1 = (hmap.get("phases") or {}).get("1")
task_path = tmp / task_rel
text = task_path.read_text(encoding="utf-8")
text = text.replace("- [ ] 1.1", "- [x] 1.1", 1)
task_path.write_text(text, encoding="utf-8")
sync = pp.sync_task_checkbox(tmp, state, phase_id="1", task_list=task_rel, task_ref="1.1")
assert sync.get("synced"), sync
store = FixtureIssuesStore(fixture_path)
issue = store.get(str(phase1["issueId"]))
assert "- [x] 1.1" in issue.body, issue.body
print("checkbox-sync-ok")
PY
then
  ok "issue-store:checkbox-body-sync"
else
  bad "issue-store:checkbox-body-sync"
fi

exit "$FAIL"
"""

if __name__ == "__main__":
    raise SystemExit(main())
