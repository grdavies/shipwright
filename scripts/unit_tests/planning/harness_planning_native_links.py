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

exit "$FAIL"
"""


if __name__ == "__main__":
    raise SystemExit(main())
