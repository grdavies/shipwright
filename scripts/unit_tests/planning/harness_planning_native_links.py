#!/usr/bin/env python3
"""PRD 056 Phase 1 — native provider links fixtures (R1-R3, R10)."""
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
import sys
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts")
from issues_lib import FixtureIssuesStore
from planning_canonical import build_edges_block, parse_edges_block, reconcile_edges

root = Path("$ROOT")
store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
store.clear()
links = [{"type": "sub-issue-of", "target": "epic-42"}]
store.create(
    title="epic",
    body="<!-- sw-unit-id: epic-u -->",
    labels=["sw:project:fixture-native"],
    project_key="fixture-native",
    artifact_type="tasks",
    unit_id="epic-u",
)
child = store.create(
    title="child",
    body="<!-- sw-unit-id: child-u -->\n" + build_edges_block([], links),
    labels=["sw:project:fixture-native"],
    project_key="fixture-native",
    artifact_type="tasks",
    unit_id="child-u",
    native_links=links,
)
got = store.get(child.id)
assert got.native_links == links, got.native_links
body_edges = parse_edges_block(got.body)
reconciled = reconcile_edges(body_edges, got.native_links)
assert reconciled.get("native") == links
print("fixture-round-trip-ok")
PY
then
  ok "fixture:create-get-reconcile"
else
  bad "fixture:create-get-reconcile"
fi

if python3 - <<'PY'
import json, sys
from pathlib import Path
from unittest.mock import MagicMock
sys.path.insert(0, "$ROOT/scripts")
import issues_http
import planning_github_client as gc

calls = []
issue_counter = {"n": 0}

def fake_urlopen(req, timeout=30):
    method = req.method
    url = req.full_url
    payload = None
    if req.data:
        payload = json.loads(req.data.decode("utf-8"))
    calls.append((method, url, payload))
    if method == "POST" and url.endswith("/issues") and "/repos/" in url:
        issue_counter["n"] += 1
        num = issue_counter["n"]
        body = json.dumps({"number": num, "id": 9000 + num, "title": "t", "body": payload.get("body", ""), "state": "open", "labels": [], "updated_at": "2026-01-01T00:00:00Z"})
        return MagicMock(status=200, headers={}, read=lambda b=body: b.encode(), __enter__=lambda s: s, __exit__=lambda *a: None)
    if method == "POST" and "/sub_issues" in url:
        return MagicMock(status=200, headers={}, read=lambda: b"{}", __enter__=lambda s: s, __exit__=lambda *a: None)
    if method == "GET" and "/issues/" in url and "/comments" in url:
        return MagicMock(status=200, headers={}, read=lambda: b"[]", __enter__=lambda s: s, __exit__=lambda *a: None)
    if method == "GET" and "/parent" in url:
        body = json.dumps({"number": 1, "id": 9001})
        return MagicMock(status=200, headers={}, read=lambda b=body: b.encode(), __enter__=lambda s: s, __exit__=lambda *a: None)
    if method == "GET" and "/issues/" in url and "/sub_issues" not in url and "/comments" not in url and "/parent" not in url:
        num = int(url.rstrip("/").split("/")[-1])
        body = json.dumps({"number": num, "id": 9000 + num, "title": "t", "body": "<!-- sw-unit-id: child -->", "state": "open", "labels": [], "updated_at": "2026-01-01T00:00:00Z"})
        return MagicMock(status=200, headers={}, read=lambda b=body: b.encode(), __enter__=lambda s: s, __exit__=lambda *a: None)
    raise AssertionError(f"unexpected {method} {url}")

issues_http._urlopen = fake_urlopen
cfg = {"planning": {"store": {"projectKey": "fixture-native", "storeLocation": {"mode": "separate-project", "owner": "o", "repo": "r"}, "issues": {"tokenEnv": "ISSUES_GITHUB_TOKEN"}}}, "host": {"provider": "github"}}
import os
os.environ["ISSUES_GITHUB_TOKEN"] = "token"
os.environ["SW_NATIVE_LINKS_CAPABLE"] = "1"
gc.load_workflow_config = lambda _r: cfg
client = gc.GitHubIssuesClient(Path("$ROOT"))
created = client.create(title="child", body="<!-- sw-unit-id: child -->", labels=[], project_key="fixture-native", artifact_type="tasks", unit_id="child", native_links=[{"type": "sub-issue-of", "target": "1"}])
assert any("/sub_issues" in c[1] for c in calls if c[0] == "POST"), calls
got = client.get(created.id)
assert got.native_links, got.native_links
from planning_canonical import reconcile_edges
reconciled = reconcile_edges({"version": 1, "edges": [], "native": got.native_links}, got.native_links)
assert reconciled["native"]
print("github-stub-round-trip-ok")
PY
then
  ok "github-stub:create-get-reconcile"
else
  bad "github-stub:create-get-reconcile"
fi

if python3 - <<'PY'
import sys
from pathlib import Path
from unittest.mock import MagicMock
sys.path.insert(0, "$ROOT/scripts")
import issues_http
import planning_store as ps

def fake_urlopen(req, timeout=15):
    if req.full_url.endswith("/user"):
        return MagicMock(status=200, headers={"X-OAuth-Scopes": "repo"}, read=lambda: b"{}", __enter__=lambda s: s, __exit__=lambda *a: None)
    if "/repos/o/r/issues/1/sub_issues" in req.full_url:
        return MagicMock(status=200, read=lambda: b"[]", __enter__=lambda s: s, __exit__=lambda *a: None)
    if "/repos/o/r" in req.full_url:
        return MagicMock(status=200, read=lambda: b"{}", __enter__=lambda s: s, __exit__=lambda *a: None)
    raise AssertionError(req.full_url)

issues_http._urlopen = fake_urlopen
cfg = {"planning": {"store": {"backend": "issue-store", "issuesProvider": "github-issues", "projectKey": "fixture-native", "storeLocation": {"mode": "separate-project", "owner": "o", "repo": "r"}, "issues": {"tokenEnv": "ISSUES_GITHUB_TOKEN"}}}, "host": {"provider": "github"}}
import os
os.environ["ISSUES_GITHUB_TOKEN"] = "token"
out = ps.probe_issues_token(Path("$ROOT"), cfg)
assert out.get("nativeLinksCapable") is True, out
print("probe-capable-ok")
PY
then
  ok "probe:nativeLinksCapable"
else
  bad "probe:nativeLinksCapable"
fi


if python3 - <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts")
from planning_canonical import native_links_from_edges

index = {"fixture-native:epic-u": "1", "fixture-native:child-u": "2"}
edges = [{"rel": "depends", "target": "epic-u"}]
links = native_links_from_edges(edges, index, project_key="fixture-native")
assert links == [{"type": "depends-on", "target": "1"}], links
print("native-links-from-edges-ok")
PY
then
  ok "canonical:native_links_from_edges"
else
  bad "canonical:native_links_from_edges"
fi

if python3 - <<'PY'
import json, sys
from pathlib import Path
from unittest.mock import MagicMock
sys.path.insert(0, "$ROOT/scripts")
import issues_http
import planning_gitlab_client as glc

calls = []
issue_counter = {"n": 0}

def fake_urlopen(req, timeout=30):
    method = req.method
    url = req.full_url
    payload = None
    if req.data:
        payload = json.loads(req.data.decode("utf-8"))
    calls.append((method, url, payload))
    if method == "GET" and "/projects/" in url and url.endswith("/projects/o%2Fr"):
        body = json.dumps({"id": 42})
        return MagicMock(status=200, headers={}, read=lambda b=body: b.encode(), __enter__=lambda s: s, __exit__=lambda *a: None)
    if method == "POST" and "/issues" in url and "/links" not in url and "/notes" not in url:
        issue_counter["n"] += 1
        num = issue_counter["n"]
        body = json.dumps({"iid": num, "id": 9000 + num, "title": "t", "description": payload.get("description", ""), "state": "opened", "labels": [], "updated_at": "2026-01-01T00:00:00Z"})
        return MagicMock(status=200, headers={}, read=lambda b=body: b.encode(), __enter__=lambda s: s, __exit__=lambda *a: None)
    if method == "POST" and "/links" in url:
        return MagicMock(status=201, headers={}, read=lambda: b"{}", __enter__=lambda s: s, __exit__=lambda *a: None)
    if method == "GET" and "/notes" in url:
        return MagicMock(status=200, headers={}, read=lambda: b"[]", __enter__=lambda s: s, __exit__=lambda *a: None)
    if method == "GET" and "/links" in url:
        body = json.dumps([{"link_type": "relates_to", "target_issue": {"iid": 1}}])
        return MagicMock(status=200, headers={}, read=lambda b=body: b.encode(), __enter__=lambda s: s, __exit__=lambda *a: None)
    if method == "GET" and "/issues/" in url:
        num = int(url.rstrip("/").split("/")[-1])
        body = json.dumps({"iid": num, "id": 9000 + num, "title": "t", "description": "<!-- sw-unit-id: child -->", "state": "opened", "labels": [], "updated_at": "2026-01-01T00:00:00Z"})
        return MagicMock(status=200, headers={}, read=lambda b=body: b.encode(), __enter__=lambda s: s, __exit__=lambda *a: None)
    raise AssertionError(f"unexpected {method} {url}")

issues_http._urlopen = fake_urlopen
cfg = {"planning": {"store": {"projectKey": "fixture-native", "storeLocation": {"mode": "separate-project", "owner": "o", "repo": "r"}, "issues": {"tokenEnv": "ISSUES_GITLAB_TOKEN"}}}, "host": {"provider": "gitlab"}}
import os
os.environ["ISSUES_GITLAB_TOKEN"] = "token"
os.environ["SW_NATIVE_LINKS_CAPABLE"] = "1"
glc.load_workflow_config = lambda _r: cfg
client = glc.GitLabIssuesClient(Path("$ROOT"))
created = client.create(title="child", body="<!-- sw-unit-id: child -->", labels=[], project_key="fixture-native", artifact_type="tasks", unit_id="child", native_links=[{"type": "sub-issue-of", "target": "1"}])
assert any("/links" in c[1] for c in calls if c[0] == "POST"), calls
got = client.get(created.id)
assert got.native_links, got.native_links
from planning_canonical import reconcile_edges
reconciled = reconcile_edges({"version": 1, "edges": [], "native": got.native_links}, got.native_links)
assert reconciled["native"]
print("gitlab-stub-round-trip-ok")
PY
then
  ok "gitlab-stub:create-get-reconcile"
else
  bad "gitlab-stub:create-get-reconcile"
fi

if python3 - <<'PY'
import json, sys
from pathlib import Path
from unittest.mock import MagicMock
sys.path.insert(0, "$ROOT/scripts")
import issues_http
import planning_jira_client as jc

calls = []

def fake_urlopen(req, timeout=30):
    method = req.method
    url = req.full_url
    payload = None
    if req.data:
        payload = json.loads(req.data.decode("utf-8"))
    calls.append((method, url, payload))
    if method == "POST" and url.endswith("/issue") and "/issueLink" not in url:
        body = json.dumps({"key": "FIX-9", "id": "10009"})
        return MagicMock(status=201, headers={}, read=lambda b=body: b.encode(), __enter__=lambda s: s, __exit__=lambda *a: None)
    if method == "POST" and url.endswith("/issueLink"):
        return MagicMock(status=201, headers={}, read=lambda: b"", __enter__=lambda s: s, __exit__=lambda *a: None)
    if method == "GET" and "/issue/FIX-" in url:
        key = url.split("/issue/")[1].split("?")[0]
        body = json.dumps({"key": key, "fields": {"summary": "t", "description": "<!-- sw-unit-id: child -->", "labels": [], "updated": "2026-01-01T00:00:00Z", "status": {"statusCategory": {"key": "new"}}, "comment": {"comments": []}, "issuelinks": [{"type": {"name": "Relates"}, "inwardIssue": {"key": key}, "outwardIssue": {"key": "FIX-1"}}]}})
        return MagicMock(status=200, headers={}, read=lambda b=body: b.encode(), __enter__=lambda s: s, __exit__=lambda *a: None)
    raise AssertionError(f"unexpected {method} {url}")

issues_http._urlopen = fake_urlopen
cfg = {"planning": {"store": {"projectKey": "fixture-native", "issues": {"tokenEnv": "ISSUES_JIRA_TOKEN", "emailEnv": "ISSUES_JIRA_EMAIL", "endpoint": "https://example.atlassian.net", "issueType": "Task", "linkDefaults": {"sub-issue-of": "Relates"}}}}, "host": {"provider": "none"}}
import os
os.environ["ISSUES_JIRA_TOKEN"] = "token"
os.environ["ISSUES_JIRA_EMAIL"] = "user@example.com"
os.environ["SW_NATIVE_LINKS_CAPABLE"] = "1"
jc.load_workflow_config = lambda _r: cfg
client = jc.JiraIssuesClient(Path("$ROOT"))
created = client.create(title="child", body="<!-- sw-unit-id: child -->", labels=[], project_key="fixture-native", artifact_type="tasks", unit_id="child", native_links=[{"type": "sub-issue-of", "target": "FIX-1"}])
assert any("/issueLink" in c[1] for c in calls if c[0] == "POST"), calls
got = client.get(created.id)
assert got.native_links, got.native_links
from planning_canonical import reconcile_edges
reconciled = reconcile_edges({"version": 1, "edges": [], "native": got.native_links}, got.native_links)
assert reconciled["native"]
print("jira-stub-round-trip-ok")
PY
then
  ok "jira-stub:create-get-reconcile"
else
  bad "jira-stub:create-get-reconcile"
fi

if python3 - <<'PY'
import sys
from pathlib import Path
from unittest.mock import MagicMock
sys.path.insert(0, "$ROOT/scripts")
import issues_http
import planning_store as ps

def fake_urlopen(req, timeout=15):
    if "/projects/o%2Fr/issues/1/links" in req.full_url:
        return MagicMock(status=200, read=lambda: b"[]", __enter__=lambda s: s, __exit__=lambda *a: None)
    if req.full_url.endswith("/user"):
        return MagicMock(status=200, read=lambda: b"{}", __enter__=lambda s: s, __exit__=lambda *a: None)
    raise AssertionError(req.full_url)

issues_http._urlopen = fake_urlopen
cfg = {"planning": {"store": {"backend": "issue-store", "issuesProvider": "gitlab-issues", "projectKey": "fixture-native", "storeLocation": {"mode": "separate-project", "owner": "o", "repo": "r"}, "issues": {"tokenEnv": "ISSUES_GITLAB_TOKEN"}}}, "host": {"provider": "gitlab"}}
import os
os.environ["ISSUES_GITLAB_TOKEN"] = "token"
out = ps.probe_issues_token(Path("$ROOT"), cfg)
# PRD 057 R7 / D1: gitlab-issues is demoted to deferred / fail-closed, so its
# token probe short-circuits as not-shipped instead of advertising capability.
assert out.get("skipped") is True and out.get("reason") == "issues-provider-not-shipped", out
print("gitlab-probe-deferred-ok")
PY
then
  ok "probe:gitlab-deferred-not-shipped"
else
  bad "probe:gitlab-deferred-not-shipped"
fi

if python3 - <<'PY'
import json, sys
from pathlib import Path
from unittest.mock import MagicMock
sys.path.insert(0, "$ROOT/scripts")
import issues_http
import planning_store as ps
import planning_jira_probe as jp

def fake_urlopen(req, timeout=15):
    if req.full_url.endswith("/issueLinkType"):
        body = json.dumps({"issueLinkTypes": [{"name": "Relates"}]})
        return MagicMock(status=200, read=lambda b=body: b.encode(), __enter__=lambda s: s, __exit__=lambda *a: None)
    if req.full_url.endswith("/myself"):
        return MagicMock(status=200, read=lambda: b"{}", __enter__=lambda s: s, __exit__=lambda *a: None)
    raise AssertionError(req.full_url)

issues_http._urlopen = fake_urlopen
jp.probe_jira_init = lambda c, t, root=None: {"verdict": "ok"}
cfg = {"planning": {"store": {"backend": "issue-store", "issuesProvider": "jira", "projectKey": "fixture-native", "issues": {"tokenEnv": "ISSUES_JIRA_TOKEN", "emailEnv": "ISSUES_JIRA_EMAIL", "endpoint": "https://example.atlassian.net"}}}, "host": {"provider": "none"}}
import os
os.environ["ISSUES_JIRA_TOKEN"] = "token"
os.environ["ISSUES_JIRA_EMAIL"] = "user@example.com"
out = ps.probe_issues_token(Path("$ROOT"), cfg)
assert out.get("nativeLinksCapable") is True, out
print("jira-probe-capable-ok")
PY
then
  ok "probe:jira-nativeLinksCapable"
else
  bad "probe:jira-nativeLinksCapable"
fi


if python3 - <<'PY'
import json, os, sys
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts")
from issues_lib import IssuesClient
from planning_canonical import parse_edges_block, normalize_body
from planning_migrate_issue_store import resolved_native_links_for_edges
from planning_store import issue_index_key, load_issue_unit_index, save_issue_unit_index

root = Path("$ROOT")
os.environ["SW_ISSUES_FIXTURE"] = "1"
cfg = {"planning": {"store": {"backend": "issue-store", "issuesProvider": "github-issues", "projectKey": "fixture-native"}}}
client = IssuesClient(root, "github-issues")
parent = client.issue_create(title="parent", body="<!-- sw-unit-id: parent-u -->", labels=[], project_key="fixture-native", artifact_type="prd", unit_id="parent-u")
index = {issue_index_key("fixture-native", "parent-u"): parent.id}
save_issue_unit_index(root, index)
links = resolved_native_links_for_edges(root, cfg, [{"rel": "depends", "target": "parent-u"}], [], "fixture-native")
assert links == [{"type": "depends-on", "target": parent.id}], links
child = client.issue_create(title="child", body="<!-- sw-unit-id: child-u -->", labels=[], project_key="fixture-native", artifact_type="prd", unit_id="child-u", native_links=links)
assert child.native_links == links
print("migrate-resolver-ok")
PY
then
  ok "migration:resolved-native-links"
else
  bad "migration:resolved-native-links"
fi

if python3 - <<'PY'
import json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts")
from issues_lib import IssuesClient
from planning_gap_capture import store_put_gap
from planning_store import issue_index_key, save_issue_unit_index

root = Path(tempfile.mkdtemp())
import subprocess
subprocess.run(["git", "init", "-q"], cwd=root, check=True)
subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=root, check=True)
subprocess.run(["git", "config", "user.name", "T"], cwd=root, check=True)
(root / ".cursor" / "hooks" / "state").mkdir(parents=True)
(root / ".cursor").mkdir(exist_ok=True)
(root / "docs" / "prds" / "gap").mkdir(parents=True)
(root / ".cursor" / "workflow.config.json").write_text(json.dumps({
  "version": 1,
  "planning": {"store": {"backend": "issue-store", "issuesProvider": "github-issues", "projectKey": "fixture-native"}},
  "host": {"provider": "github"},
}), encoding="utf-8")
subprocess.run(["git", "remote", "add", "origin", "https://github.com/o/r.git"], cwd=root, check=True)
subprocess.run(["git", "add", "-A"], cwd=root, check=True)
subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True)
os.environ["SW_ISSUES_FIXTURE"] = "1"
client = IssuesClient(root, "github-issues")
parent = client.issue_create(title="parent", body="<!-- sw-unit-id: parent-gap -->", labels=[], project_key="fixture-native", artifact_type="prd", unit_id="parent-gap")
save_issue_unit_index(root, {issue_index_key("fixture-native", "parent-gap"): parent.id})
content = (
    "---\n"
    "id: gap-001-test\n"
    "type: gap\n"
    "status: open\n"
    "title: Gap with depends\n"
    "visibility: public\n"
    "---\n"
    "# Gap body\n\n"
    "## Problem\n\nDepends linkage test.\n\n"
    "## Context/evidence\n\nFixture harness.\n\n"
    "## Related units\n\nnone\n\n"
    "## Suggested next step\n\ntriage\n\n"
    "```sw-edges\n"
    '{"version": 1, "edges": [{"rel": "depends", "target": "parent-gap"}], "native": []}\n'
    "```\n"
)
store_put_gap(root, "gap-001-test", "docs/prds/gap/gap-001-test/gap-001-test.md", content)
rec = IssuesClient(root, "github-issues").issue_search(project_key="fixture-native", unit_id="gap-001-test")[0]
assert rec.native_links == [{"type": "depends-on", "target": parent.id}], rec.native_links
print("gap-native-ok")
PY
then
  ok "gap-capture:native-links"
else
  bad "gap-capture:native-links"
fi

if python3 - <<'PY'
import json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts")
import planning_hierarchy as ph
from issues_lib import IssuesClient

tmp = Path(tempfile.mkdtemp())
import subprocess
subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp, check=True)
subprocess.run(["git", "config", "user.name", "T"], cwd=tmp, check=True)
(tmp / ".cursor" / "hooks" / "state").mkdir(parents=True)
(tmp / "docs" / "prds" / "046-test").mkdir(parents=True)
(tmp / ".cursor" / "workflow.config.json").write_text(json.dumps({
  "version": 1,
  "planning": {"store": {"backend": "issue-store", "issuesProvider": "github-issues", "projectKey": "phase3046"}},
  "host": {"provider": "github"},
}), encoding="utf-8")
(tmp / "docs/prds/046-test/tasks-046-test.md").write_text("---\nfrozen: true\n---\n### 1. Alpha\n", encoding="utf-8")
os.environ["SW_ISSUES_FIXTURE"] = "1"
out = ph.project_task_list_hierarchy(tmp, tmp / "docs/prds/046-test/tasks-046-test.md", dry_run=False)
client = IssuesClient(tmp, "github-issues")
subs = out.get("subIssues") or []
assert subs, subs
child = client.issue_get(subs[0]["issueId"])
assert child.native_links and child.native_links[0]["type"] == "sub-issue-of"
print("hierarchy-native-ok")
PY
then
  ok "hierarchy:sub-issue-native-links"
else
  bad "hierarchy:sub-issue-native-links"
fi

if python3 - <<'PY'
import json, os, sys
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts")
from planning_migrate_issue_store import resolved_native_links_for_edges

root = Path("$ROOT")
cfg = {"planning": {"store": {"backend": "file-store", "issuesProvider": "github-issues", "projectKey": "fixture-native"}}}
links = resolved_native_links_for_edges(root, cfg, [{"rel": "depends", "target": "parent-u"}], [], "fixture-native")
assert links == [], links
print("file-store-skip-ok")
PY
then
  ok "file-store:no-native-links"
else
  bad "file-store:no-native-links"
fi

exit "$FAIL"
"""


if __name__ == "__main__":
    raise SystemExit(main())
