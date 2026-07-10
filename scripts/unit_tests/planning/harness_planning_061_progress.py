#!/usr/bin/env python3
"""PRD 061 phase 2 — progress model + no default phase mint (R6–R9, R8a, R24)."""
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
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

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
(tmp / "docs" / "prds" / "061-test").mkdir(parents=True)
(tmp / "docs/prds/061-test/tasks-061-test.md").write_text(
    "---\nfrozen: true\n---\n### 1. Alpha phase\n### 2. Beta phase\n",
    encoding="utf-8",
)
(tmp / ".cursor/workflow.config.json").write_text(json.dumps({
    "version": 1,
    "planning": {
        "store": {
            "backend": "issue-store",
            "issuesProvider": "github-issues",
            "projectKey": "deliver-progress-061",
        }
    },
    "host": {"provider": "github"},
}), encoding="utf-8")
os.environ["SW_ISSUES_FIXTURE"] = "1"
fixture_path = tmp / ".cursor/hooks/state/issue-store-fixture.json"
if fixture_path.is_file():
    fixture_path.unlink()
state = {"source_task_list": "docs/prds/061-test/tasks-061-test.md"}
out = pp.provision_deliver_hierarchy(tmp, state)
assert out.get("applied"), out
hmap = load_hierarchy_map(state)
assert hmap.get("mode") == "parent-checkbox", hmap
assert hmap.get("epicIssueId"), hmap
store = FixtureIssuesStore(fixture_path)
issues = list(store._issues.values())
assert len(issues) == 1, len(issues)
subs = [i for i in issues if (i.unit_id or "").endswith("-phase-1") or (i.unit_id or "").endswith("-phase-2")]
assert not subs, [i.unit_id for i in issues]
print("no-default-phase-issues-ok")
PY
then
  ok "no-default-phase-issues"
else
  bad "no-default-phase-issues"
fi

if python3 - <<'PY'
import json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts")
import planning_hierarchy as ph

tmp = Path(tempfile.mkdtemp())
(tmp / ".cursor").mkdir(parents=True)
(tmp / ".cursor/workflow.config.json").write_text(json.dumps({
    "version": 1,
    "planning": {"store": {"backend": "in-repo-public", "issuesProvider": "jira"}},
}), encoding="utf-8")
out = ph.resolve_progress_hierarchy_mode("jira", json.loads((tmp / ".cursor/workflow.config.json").read_text()))
assert out.get("mode") == "checkbox" and out.get("notice"), out
print("degrade-single-notice-ok")
PY
then
  ok "degrade-single-notice"
else
  bad "degrade-single-notice"
fi

if python3 - <<'PY'
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts")
import planning_hierarchy as ph

tmp = Path(tempfile.mkdtemp())
(tmp / ".cursor").mkdir(parents=True)
(tmp / ".cursor/workflow.config.json").write_text(json.dumps({
    "version": 1,
    "planning": {"store": {"backend": "issue-store", "issuesProvider": "github-issues"}},
}), encoding="utf-8")
cfg = json.loads((tmp / ".cursor/workflow.config.json").read_text())
assert ph.resolve_progress_hierarchy_mode("github-issues", cfg).get("mode") == "parent-checkbox"
cfg["planning"]["store"]["hierarchy"] = {"epicSubIssues": False}
assert ph.resolve_progress_hierarchy_mode("github-issues", cfg).get("mode") == "parent-checkbox"
cfg["planning"]["store"]["hierarchy"] = {"epicSubIssues": True}
assert ph.resolve_progress_hierarchy_mode("github-issues", cfg).get("mode") == "epic-sub-issue"
print("opt-in-hierarchy-off-ok")
PY
then
  ok "opt-in-hierarchy-off"
else
  bad "opt-in-hierarchy-off"
fi

if python3 - <<'PY'
import json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts")
import planning_store as ps
from issues_lib import FixtureIssuesStore

tmp = Path(tempfile.mkdtemp())
import subprocess
subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
(tmp / ".cursor" / "hooks" / "state").mkdir(parents=True)
(tmp / ".cursor/workflow.config.json").write_text(json.dumps({
    "version": 1,
    "planning": {
        "store": {
            "backend": "issue-store",
            "issuesProvider": "github-issues",
            "projectKey": "orphan-061",
        }
    },
    "host": {"provider": "github"},
}), encoding="utf-8")
os.environ["SW_ISSUES_FIXTURE"] = "1"
fixture_path = tmp / ".cursor/hooks/state/issue-store-fixture.json"
store = FixtureIssuesStore(fixture_path)
store.create(
    title="[sw] phase:061-test:1",
    body="unit-id: 061-test-phase-1\n",
    labels=["sw:project:orphan-061", "sw:type:tasks", "sw:phase:1"],
    project_key="orphan-061",
    artifact_type="tasks",
    unit_id="061-test-phase-1",
)
cfg = json.loads((tmp / ".cursor/workflow.config.json").read_text())
dry = ps.migrate_orphan_phase_issues(tmp, cfg, tasks_unit_id="061-test", dry_run=True)
assert dry.get("count") == 1, dry
live = ps.migrate_orphan_phase_issues(tmp, cfg, tasks_unit_id="061-test", dry_run=False)
assert live.get("count") == 1, live
again = ps.migrate_orphan_phase_issues(tmp, cfg, tasks_unit_id="061-test", dry_run=False)
assert again.get("count") == 0, again
print("orphan-phase-migration-ok")
PY
then
  ok "orphan-phase-migration"
else
  bad "orphan-phase-migration"
fi

if python3 - <<'PY'
import json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts")
import planning_progress as pp

tmp = Path(tempfile.mkdtemp())
import subprocess
subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp, check=True)
subprocess.run(["git", "config", "user.name", "T"], cwd=tmp, check=True)
(tmp / ".cursor" / "hooks" / "state").mkdir(parents=True)
(tmp / "docs" / "prds" / "061-test").mkdir(parents=True)
(tmp / "docs/prds/061-test/tasks-061-test.md").write_text("### 1. Alpha\n", encoding="utf-8")
(tmp / ".cursor/workflow.config.json").write_text(json.dumps({
    "version": 1,
    "planning": {
        "store": {
            "backend": "issue-store",
            "issuesProvider": "github-issues",
            "projectKey": "once-061",
        }
    },
    "host": {"provider": "github"},
}), encoding="utf-8")
os.environ["SW_ISSUES_FIXTURE"] = "1"
state = {"source_task_list": "docs/prds/061-test/tasks-061-test.md"}
pp._PROVISION_APPLY_COUNT = 0
first = pp.provision_deliver_hierarchy(tmp, state)
second = pp.provision_deliver_hierarchy(tmp, state)
assert first.get("applied") and second.get("idempotent"), (first, second)
assert pp._PROVISION_APPLY_COUNT == 1, pp._PROVISION_APPLY_COUNT
print("once-per-run-apply-ok")
PY
then
  ok "once-per-run-apply"
else
  bad "once-per-run-apply"
fi

if python3 - <<'PY'
import json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts")
import planning_discover as pd
import planning_index_gen as pig
from issues_lib import FixtureIssuesStore

assert "tasks" in pig.UNIT_TYPES
tmp = Path(tempfile.mkdtemp())
import subprocess
subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
(tmp / ".cursor" / "hooks" / "state").mkdir(parents=True)
(tmp / ".cursor/workflow.config.json").write_text(json.dumps({
    "version": 1,
    "planning": {
        "store": {
            "backend": "issue-store",
            "issuesProvider": "github-issues",
            "projectKey": "discover-061",
        }
    },
    "host": {"provider": "github"},
}), encoding="utf-8")
os.environ["SW_ISSUES_FIXTURE"] = "1"
store = FixtureIssuesStore(tmp / ".cursor/hooks/state/issue-store-fixture.json")
store.create(
    title="[sw] tasks:061-discover",
    body="artifact-type: tasks\nunit-id: 061-discover\n",
    labels=["sw:project:discover-061", "sw:type:tasks", "sw:visibility:public"],
    project_key="discover-061",
    artifact_type="tasks",
    unit_id="061-discover",
)
units = pd.discover_units(tmp)
ids = {u.id for u in units}
assert "061-discover" in ids, ids
print("tasks-in-discover-ok")
PY
then
  ok "tasks-in-discover"
else
  bad "tasks-in-discover"
fi

if OUT=$(python3 "$ROOT/scripts/planning_store.py" --root "$ROOT" list-facade) && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert any(o['name']=='progress_update' and o['status']=='shipped' for o in d['operations'])";
then
  ok "progress-update-facade-shipped"
else
  bad "progress-update-facade-shipped"
fi

exit $FAIL
"""

if __name__ == "__main__":
    raise SystemExit(main())
