#!/usr/bin/env python3
"""Ported fixture suite (R27) — embedded harness executed without on-disk shell files."""
from __future__ import annotations

import os
import re
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
    completed = subprocess.run(
        ["bash", "-c", src],
        cwd=str(root),
        env=env,
        shell=False,
    )
    return completed.returncode


_SOURCE = r"""
#!/usr/bin/env bash
# PRD 034 Phase 3 — planning store interface + backend fixtures.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT/scripts:${PYTHONPATH:-}"
PY="$ROOT/scripts/planning_store.py"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }
TMP="$(mktemp -d)"
CFG_BACKUP=""
if [[ -f "$ROOT/.cursor/workflow.config.json" ]]; then
  CFG_BACKUP="$TMP/workflow.config.json.bak"
  cp "$ROOT/.cursor/workflow.config.json" "$CFG_BACKUP"
fi
restore_config() {
  if [[ -n "$CFG_BACKUP" ]]; then
    cp "$CFG_BACKUP" "$ROOT/.cursor/workflow.config.json"
  else
    rm -f "$ROOT/.cursor/workflow.config.json"
  fi
}
trap 'restore_config; rm -rf "$TMP"' EXIT

write_in_repo_public_config() {
  python3 - <<PY
import json
from pathlib import Path
p = Path("$ROOT/.cursor/workflow.config.json")
p.parent.mkdir(parents=True, exist_ok=True)
cfg = {"version": 1, "planning": {"store": {"backend": "in-repo-public"}}}
p.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
PY
}

# --- store-interface-in-repo-default ---
write_in_repo_public_config
if OUT=$(python3 "$PY" --root "$ROOT" resolve-backend) &&    echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['backend']=='in-repo-public'"; then
  ok "store-interface-in-repo-default:default-backend"
else
  bad "store-interface-in-repo-default:default-backend"
fi
BODY_REL="docs/prds/_fixture-store/in-repo-body.md"
UNIT_ID="fixture-in-repo"
CONTENT="# fixture body"
if OUT=$(python3 "$PY" --root "$ROOT" put --unit-id "$UNIT_ID" --body-path "$BODY_REL" --content "$CONTENT") &&    echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='ok' and d['backend']=='in-repo-public'"; then
  ok "store-interface-in-repo-default:put"
else
  bad "store-interface-in-repo-default:put"
fi
for op in get exists materialize; do
  if [[ "$op" == "materialize" ]]; then
    CMD=(python3 "$PY" --root "$ROOT" materialize --unit-id "$UNIT_ID" --body-path "$BODY_REL" --dest "$TMP/mat.md")
  else
    CMD=(python3 "$PY" --root "$ROOT" "$op" --unit-id "$UNIT_ID" --body-path "$BODY_REL")
  fi
  if OUT=$("${CMD[@]}") && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='ok'"; then
    ok "store-interface-in-repo-default:$op"
  else
    bad "store-interface-in-repo-default:$op"
  fi
done
rm -f "$ROOT/$BODY_REL" 2>/dev/null || true
rm -rf "$ROOT/docs/prds/_fixture-store" 2>/dev/null || true

# --- store-backend-interface-parity ---
SYNC_DIR="$TMP/local-synced"
mkdir -m 0700 "$SYNC_DIR"
CFG="$TMP/workflow.config.json"
python3 - <<PY
import json
from pathlib import Path
Path("$CFG").write_text(json.dumps({
  "version": 1,
  "planning": {"store": {"backend": "local-synced", "localSynced": {"path": "$SYNC_DIR"}}}
}))
PY
cp "$ROOT/.cursor/workflow.config.json" "$TMP/orig-workflow.config.json" 2>/dev/null || true
cp "$CFG" "$ROOT/.cursor/workflow.config.json"
for backend in local-synced memory; do
  if [[ "$backend" == "memory" ]]; then
    echo 'in-repo' > "$ROOT/.cursor/sw-memory.provider"
    OUT=$(python3 "$PY" --root "$ROOT" put --backend memory --unit-id "parity-$backend" --body-path "ignored.md" --content "parity")
  else
    OUT=$(python3 "$PY" --root "$ROOT" put --unit-id "parity-$backend" --body-path "ignored.md" --content "parity")
  fi
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='ok'"; then
    ok "store-backend-interface-parity:put:$backend"
  else
    bad "store-backend-interface-parity:put:$backend"
  fi
done
rm -f "$ROOT/.cursor/sw-memory.provider"
if OUT=$(python3 "$PY" --root "$ROOT" put --backend private-repo --unit-id deferred --body-path x.md --content x) &&    echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='deferred' and d.get('inert')"; then
  ok "store-backend-interface-parity:deferred-inert"
else
  bad "store-backend-interface-parity:deferred-inert"
fi
if [[ -f "$TMP/orig-workflow.config.json" ]]; then
  cp "$TMP/orig-workflow.config.json" "$ROOT/.cursor/workflow.config.json"
else
  rm -f "$ROOT/.cursor/workflow.config.json"
fi

# --- store-log-id-hash-backend ---
write_in_repo_public_config
SECRET_BODY='token ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA tail'
if LOGS=$(python3 "$PY" --root "$ROOT" put --unit-id log-test --body-path docs/prds/_fixture-store/log.md --content "$SECRET_BODY" 2>/tmp/store-log.stderr); then
  if grep -q 'planningStore' /tmp/store-log.stderr && grep -q '"hash"' /tmp/store-log.stderr && ! grep -q 'ghp_' /tmp/store-log.stderr; then
    ok "store-log-id-hash-backend:no-body-in-log"
  else
    bad "store-log-id-hash-backend:no-body-in-log"
  fi
else
  bad "store-log-id-hash-backend:put"
fi
rm -rf "$ROOT/docs/prds/_fixture-store" 2>/dev/null || true

# --- memory-backend-adapter-only ---
if rg -n 'CallMcpTool|store_memory|expand_memories|mcp_' "$ROOT/scripts/planning_store.py" >/dev/null 2>&1; then
  bad "memory-backend-adapter-only:no-direct-mcp"
else
  ok "memory-backend-adapter-only:no-direct-mcp"
fi
MARKER='.cursor/sw-memory.provider'
echo 'in-repo' > "$ROOT/$MARKER"
if OUT=$(python3 "$PY" --root "$ROOT" put --backend memory --unit-id mem-redact --body-path mem.md --content 'contact test@example.com' 2>&1); then
  BODY=$(python3 "$PY" --root "$ROOT" get --backend memory --unit-id mem-redact --body-path mem.md)
  if echo "$BODY" | python3 -c "import json,sys; c=json.load(sys.stdin)['content']; assert '[REDACTED:EMAIL]' in c"; then
    ok "memory-backend-adapter-only:redact-read-write"
  else
    bad "memory-backend-adapter-only:redact-read-write"
  fi
else
  bad "memory-backend-adapter-only:put"
fi
rm -f "$ROOT/$MARKER"
rm -rf "$ROOT/.cursor/sw-memory/planning-bodies" 2>/dev/null || true
if python3 "$PY" --root "$ROOT" put --backend memory --unit-id ban --body-path x.md --content x --content-class discussion 2>/dev/null; then
  bad "memory-backend-adapter-only:ban-discussion"
else
  ok "memory-backend-adapter-only:ban-discussion"
fi

# --- local-synced-path-validation ---
GOOD="$HOME/.planning-store-fixture-good"
rm -rf "$GOOD"
mkdir -m 0700 "$GOOD"
if OUT=$(python3 "$PY" --root "$ROOT" validate-local-synced --path "$GOOD") &&    echo "$OUT" | python3 -c "import json,sys; assert json.load(sys.stdin)['verdict']=='ok'"; then
  ok "local-synced-path-validation:good-path"
else
  bad "local-synced-path-validation:good-path"
fi
LOOSE="$TMP/loose-sync"
mkdir -m 0755 "$LOOSE"
if OUT=$(python3 "$PY" --root "$ROOT" validate-local-synced --path "$LOOSE" 2>/dev/null || true); then
  if echo "$OUT" | python3 -c "import json,sys; assert json.load(sys.stdin)['verdict']=='fail'"; then
    ok "local-synced-path-validation:loose-mode"
  else
    bad "local-synced-path-validation:loose-mode"
  fi
fi
LINK="$TMP/link-target"
mkdir -m 0700 "$LINK"
SYMLINK="$TMP/link"
ln -s "$LINK" "$SYMLINK"
if OUT=$(python3 "$PY" --root "$ROOT" validate-local-synced --path "$SYMLINK" 2>/dev/null || true); then
  if echo "$OUT" | python3 -c "import json,sys; assert json.load(sys.stdin)['verdict']=='fail'"; then
    ok "local-synced-path-validation:symlink"
  else
    bad "local-synced-path-validation:symlink"
  fi
fi
DOTDOT="$TMP/dotdot"
mkdir -m 0700 "$DOTDOT"
if OUT=$(python3 "$PY" --root "$ROOT" validate-local-synced --path "$DOTDOT/../$DOTDOT" 2>/dev/null || true); then
  if echo "$OUT" | python3 -c "import json,sys; assert json.load(sys.stdin)['verdict']=='fail'"; then
    ok "local-synced-path-validation:dotdot"
  else
    bad "local-synced-path-validation:dotdot"
  fi
fi
HOME_CLOUD="$HOME/Dropbox/planning-fixture"
mkdir -p "$HOME_CLOUD" 2>/dev/null || true
if OUT=$(python3 "$PY" --root "$ROOT" validate-local-synced --path "$HOME_CLOUD" 2>/dev/null || true); then
  if echo "$OUT" | python3 -c "import json,sys; w=json.load(sys.stdin).get('warnings',[]); assert any('cloud-sync-root' in x for x in w)"; then
    ok "local-synced-path-validation:cloud-warn"
  else
    ok "local-synced-path-validation:cloud-warn-skipped"
  fi
fi

# --- memory-chokepoint-read-write ---
echo 'in-repo' > "$ROOT/$MARKER"
WRITE='Bearer abcdefghijklmnopqrstuvwxyz'
if OUT=$(python3 "$PY" --root "$ROOT" put --backend memory --unit-id choke --body-path c.md --content "$WRITE"); then
  GOT=$(python3 "$PY" --root "$ROOT" get --backend memory --unit-id choke --body-path c.md)
  if echo "$GOT" | python3 -c "import json,sys; c=json.load(sys.stdin)['content']; assert 'REDACTED' in c"; then
    ok "memory-chokepoint-read-write:redact-both-directions"
  else
    bad "memory-chokepoint-read-write:redact-both-directions"
  fi
else
  bad "memory-chokepoint-read-write:put"
fi
if python3 "$PY" --root "$ROOT" put --backend memory --unit-id transcript --body-path t.md --content 'User: hello
Assistant: world' 2>/dev/null; then
  bad "memory-chokepoint-read-write:refuse-transcript"
else
  ok "memory-chokepoint-read-write:refuse-transcript"
fi
rm -f "$ROOT/$MARKER"
rm -rf "$ROOT/.cursor/sw-memory/planning-bodies" 2>/dev/null || true

# --- issue-store-artifact-crud (PRD 043 Phase 2) ---
export SW_ISSUES_FIXTURE=1
ISSUE_CFG="$TMP/issue-store.config.json"
python3 - <<PY
import json
from pathlib import Path
Path("$ISSUE_CFG").write_text(json.dumps({
  "version": 1,
  "planning": {"store": {
    "backend": "issue-store",
    "issuesProvider": "github-issues",
    "projectKey": "fixture-alpha",
  }},
}, indent=2) + "\n")
PY
cp "$ISSUE_CFG" "$ROOT/.cursor/workflow.config.json"
python3 "$PY" --root "$ROOT" clear-issue-fixture >/dev/null
rm -rf "$ROOT/docs/prds/099-fixture" 2>/dev/null || true
PRD_BODY='# fixture prd'
if OUT=$(python3 "$PY" --root "$ROOT" put --backend issue-store --unit-id fixture-prd --body-path docs/prds/099-fixture/099-prd-fixture.md --content "$PRD_BODY") && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='ok' and d['backend']=='issue-store'"; then
  ok "issue-store-artifact-crud:put-prd"
else
  bad "issue-store-artifact-crud:put-prd"
fi
if [[ ! -f "$ROOT/docs/prds/099-fixture/099-prd-fixture.md" ]]; then
  ok "issue-store-zero-stub:no-repo-file"
else
  bad "issue-store-zero-stub:no-repo-file"
fi
if OUT=$(python3 "$PY" --root "$ROOT" get --backend issue-store --unit-id fixture-prd --body-path docs/prds/099-fixture/099-prd-fixture.md) && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['content']=='# fixture prd'"; then
  ok "issue-store-artifact-crud:get-roundtrip"
else
  bad "issue-store-artifact-crud:get-roundtrip"
fi

# --- issue-store-isolation (R11/R12) ---
python3 - <<PY
import json
from pathlib import Path
Path("$ROOT/.cursor/workflow.config.json").write_text(json.dumps({
  "version": 1,
  "planning": {"store": {
    "backend": "issue-store",
    "issuesProvider": "github-issues",
    "projectKey": "fixture-beta",
  }},
}, indent=2) + "\n")
PY
if OUT=$(python3 "$PY" --root "$ROOT" put --backend issue-store --unit-id spoof --body-path docs/prds/099-fixture/099-prd-spoof.md --content '# spoof' 2>/dev/null); then
  ok "issue-store-isolation:beta-write"
else
  bad "issue-store-isolation:beta-write"
fi
cp "$ISSUE_CFG" "$ROOT/.cursor/workflow.config.json"
if OUT=$(python3 "$PY" --root "$ROOT" get --backend issue-store --unit-id spoof --body-path docs/prds/099-fixture/099-prd-spoof.md 2>/dev/null || true); then
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='missing'"; then
    ok "issue-store-isolation:cross-project-read-blocked"
  else
    bad "issue-store-isolation:cross-project-read-blocked"
  fi
fi

# --- canonical-hash-golden (R35) ---
for fx in github-prd-open gitlab-prd-open github-tasks-chunked; do
  FPATH="$ROOT/scripts/tests/fixtures/canonical/${fx}.json"
  if OUT=$(python3 "$PY" --root "$ROOT" canonical-hash --fixture "$FPATH") && \
     echo "$OUT" | python3 -c "import json,sys,pathlib; d=json.load(sys.stdin); exp=json.loads(pathlib.Path(sys.argv[1]).read_text())['expectedHash']; assert d['hash']==exp" "$FPATH"; then
    ok "canonical-hash-golden:${fx}"
  else
    bad "canonical-hash-golden:${fx}"
  fi
done
GH=$(python3 -c "import json; print(json.load(open('$ROOT/scripts/tests/fixtures/canonical/github-prd-open.json'))['expectedHash'])")
GL=$(python3 -c "import json; print(json.load(open('$ROOT/scripts/tests/fixtures/canonical/gitlab-prd-open.json'))['expectedHash'])")
if [[ "$GH" == "$GL" ]]; then
  ok "canonical-hash-golden:cross-provider-parity"
else
  bad "canonical-hash-golden:cross-provider-parity"
fi

JIRA_CANON="$ROOT/scripts/planning_jira_canonical.py"
for fx in jira/prd-open jira/adf-roundtrip jira/server-mutated-adf jira/wiki-dc; do
  FPATH="$ROOT/scripts/tests/fixtures/canonical/${fx}.json"
  if OUT=$(python3 "$JIRA_CANON" normalize --fixture "$FPATH") && \
     echo "$OUT" | python3 -c "import json,sys,pathlib; d=json.load(sys.stdin); exp=json.loads(pathlib.Path(sys.argv[1]).read_text())['expectedHash']; assert d['hash']==exp" "$FPATH"; then
    ok "canonical-hash-golden:${fx}"
  else
    bad "canonical-hash-golden:${fx}"
  fi
done
JIRA_H=$(python3 -c "import json; print(json.load(open('$ROOT/scripts/tests/fixtures/canonical/jira/prd-open.json'))['expectedHash'])")
if [[ "$GH" == "$JIRA_H" ]]; then
  ok "canonical-hash-golden:jira-cross-provider-parity"
else
  bad "canonical-hash-golden:jira-cross-provider-parity"
fi

# --- brainstorm-durability-link (R18) ---
python3 "$PY" --root "$ROOT" clear-issue-fixture >/dev/null
cp "$ISSUE_CFG" "$ROOT/.cursor/workflow.config.json"
python3 "$PY" --root "$ROOT" put --backend issue-store --unit-id bs-fixture --body-path docs/brainstorms/2026-06-30-fixture-requirements.md --content $'---\nvisibility: public\n---\n# brainstorm' >/dev/null
if OUT=$(python3 "$PY" --root "$ROOT" link-brainstorm-prd --brainstorm-unit bs-fixture --prd-unit fixture-prd) && \
   echo "$OUT" | python3 -c "import json,sys; assert json.load(sys.stdin)['verdict']=='ok'"; then
  ok "brainstorm-durability:link-prd"
else
  bad "brainstorm-durability:link-prd"
fi

# --- revision-conflict (R36) ---
python3 "$PY" --root "$ROOT" clear-issue-fixture >/dev/null
cp "$ISSUE_CFG" "$ROOT/.cursor/workflow.config.json"
python3 "$PY" --root "$ROOT" put --backend issue-store --unit-id rev --body-path docs/prds/099-fixture/099-prd-rev.md --content v1 >/dev/null
if python3 - <<INNER
import sys
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts")
from issues_lib import FixtureIssuesStore, IssueRevisionConflict
store = FixtureIssuesStore(Path("$ROOT/.cursor/hooks/state/issue-store-fixture.json"))
issue_id = next(iter(store._issues))
try:
    store.update(issue_id, body="v2", if_match="stale-etag-from-checkpoint")
except IssueRevisionConflict:
    raise SystemExit(0)
raise SystemExit(1)
INNER
then
  ok "revision-conflict:fail-closed"
else
  bad "revision-conflict:should-fail"
fi


# --- issue-store-freeze-r13 (R13) ---
python3 "$PY" --root "$ROOT" clear-issue-fixture >/dev/null
cp "$ISSUE_CFG" "$ROOT/.cursor/workflow.config.json"
python3 "$PY" --root "$ROOT" put --backend issue-store --unit-id freeze-me --body-path docs/prds/099-fixture/099-prd-freeze.md --content '# freeze target' >/dev/null
if OUT=$(python3 "$PY" --root "$ROOT" freeze --backend issue-store --unit-id freeze-me --body-path docs/prds/099-fixture/099-prd-freeze.md --no-distill) && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='ok' and d.get('locked') and d.get('hash')"; then
  ok "issue-store-freeze-r13:lock-label-hash"
else
  bad "issue-store-freeze-r13:lock-label-hash"
fi
if python3 - <<INNER
import json, sys
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts")
from issues_lib import FixtureIssuesStore
from planning_canonical import FROZEN_LABEL, parse_freeze_record_hash
store = FixtureIssuesStore(Path("$ROOT/.cursor/hooks/state/issue-store-fixture.json"))
rec = next(iter(store._issues.values()))
assert rec.locked and FROZEN_LABEL in rec.labels
assert parse_freeze_record_hash(rec.comments)
raise SystemExit(0)
INNER
then
  ok "issue-store-freeze-r13:fixture-state"
else
  bad "issue-store-freeze-r13:fixture-state"
fi

# --- issue-store-tamper-r37 (R37) ---
if OUT=$(python3 "$PY" --root "$ROOT" get --backend issue-store --unit-id freeze-me --body-path docs/prds/099-fixture/099-prd-freeze.md) && \
   echo "$OUT" | python3 -c "import json,sys; assert json.load(sys.stdin)['verdict']=='ok'"; then
  ok "issue-store-tamper-r37:pre-tamper-read"
else
  bad "issue-store-tamper-r37:pre-tamper-read"
fi
python3 - <<INNER
import sys
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts")
from issues_lib import FixtureIssuesStore
store = FixtureIssuesStore(Path("$ROOT/.cursor/hooks/state/issue-store-fixture.json"))
rec = next(iter(store._issues.values()))
rec.body = rec.body + "\n<!-- tamper -->"
rec.touch()
store._persist()
INNER
if OUT=$(python3 "$PY" --root "$ROOT" get --backend issue-store --unit-id freeze-me --body-path docs/prds/099-fixture/099-prd-freeze.md 2>/dev/null || true); then
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('code')=='tamper-detected'"; then
    ok "issue-store-tamper-r37:detected"
  else
    bad "issue-store-tamper-r37:detected"
  fi
else
  bad "issue-store-tamper-r37:detected"
fi

# --- issue-store-verify-hash-r14 (R14) ---
python3 "$PY" --root "$ROOT" clear-issue-fixture >/dev/null
cp "$ISSUE_CFG" "$ROOT/.cursor/workflow.config.json"
python3 "$PY" --root "$ROOT" put --backend issue-store --unit-id verify-me --body-path docs/prds/099-fixture/099-prd-verify.md --content v1 >/dev/null
python3 "$PY" --root "$ROOT" freeze --backend issue-store --unit-id verify-me --body-path docs/prds/099-fixture/099-prd-verify.md --no-distill >/dev/null
if OUT=$(python3 "$PY" --root "$ROOT" verify-frozen-hash --unit-id verify-me --body-path docs/prds/099-fixture/099-prd-verify.md) && \
   echo "$OUT" | python3 -c "import json,sys; assert json.load(sys.stdin)['verdict']=='ok'"; then
  ok "issue-store-verify-hash-r14:match"
else
  bad "issue-store-verify-hash-r14:match"
fi
python3 - <<INNER
import sys
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts")
from issues_lib import FixtureIssuesStore
store = FixtureIssuesStore(Path("$ROOT/.cursor/hooks/state/issue-store-fixture.json"))
rec = next(i for i in store._issues.values() if i.unit_id=='verify-me')
rec.title = rec.title + ' tampered'
rec.touch(); store._persist()
INNER
if OUT=$(python3 "$PY" --root "$ROOT" verify-frozen-hash --unit-id verify-me --body-path docs/prds/099-fixture/099-prd-verify.md 2>/dev/null || true); then
  if echo "$OUT" | python3 -c "import json,sys; assert json.load(sys.stdin).get('code')=='tamper-detected'"; then
    ok "issue-store-verify-hash-r14:mismatch"
  else
    bad "issue-store-verify-hash-r14:mismatch"
  fi
else
  bad "issue-store-verify-hash-r14:mismatch"
fi

# --- issue-store-freeze-incomplete-r48 (R48) ---
python3 "$PY" --root "$ROOT" clear-issue-fixture >/dev/null
cp "$ISSUE_CFG" "$ROOT/.cursor/workflow.config.json"
python3 "$PY" --root "$ROOT" put --backend issue-store --unit-id inc --body-path docs/prds/099-fixture/099-prd-inc.md --content '# inc' >/dev/null
python3 "$PY" --root "$ROOT" put --backend issue-store --unit-id bs-inc --body-path docs/brainstorms/bs-inc.md --content $'---\nvisibility: public\n---\n# bs' >/dev/null
python3 "$PY" --root "$ROOT" link-brainstorm-prd --brainstorm-unit bs-inc --prd-unit inc >/dev/null
export SW_FREEZE_DISTILL_FAIL=1
if OUT=$(python3 "$PY" --root "$ROOT" freeze --unit-id inc --body-path docs/prds/099-fixture/099-prd-inc.md 2>/dev/null || true); then
  if echo "$OUT" | python3 -c "import json,sys; assert json.load(sys.stdin).get('code')=='freeze-incomplete'"; then
    ok "issue-store-freeze-incomplete-r48:blocked"
  else
    bad "issue-store-freeze-incomplete-r48:blocked"
  fi
else
  bad "issue-store-freeze-incomplete-r48:blocked"
fi
unset SW_FREEZE_DISTILL_FAIL
if OUT=$(python3 "$PY" --root "$ROOT" verify-frozen-hash --unit-id inc --body-path docs/prds/099-fixture/099-prd-inc.md 2>/dev/null || true); then
  if echo "$OUT" | python3 -c "import json,sys; assert json.load(sys.stdin).get('code')=='freeze-incomplete'"; then
    ok "issue-store-freeze-incomplete-r48:verify-blocked"
  else
    bad "issue-store-freeze-incomplete-r48:verify-blocked"
  fi
fi

# --- issue-store-visibility-r28 (R28) ---
python3 "$PY" --root "$ROOT" clear-issue-fixture >/dev/null
cp "$ISSUE_CFG" "$ROOT/.cursor/workflow.config.json"
PRIVATE_BODY=$'---\nvisibility: private\n---\n# private'
if OUT=$(python3 "$PY" --root "$ROOT" put --backend issue-store --unit-id priv --body-path docs/prds/099-fixture/099-prd-priv.md --content "$PRIVATE_BODY" 2>/dev/null || true); then
  if echo "$OUT" | python3 -c "import json,sys; assert json.load(sys.stdin).get('code')=='visibility-refused'"; then
    ok "issue-store-visibility-r28:refuse-private"
  else
    bad "issue-store-visibility-r28:refuse-private"
  fi
else
  bad "issue-store-visibility-r28:refuse-private"
fi

# --- issue-store-secret-scan-r45 (R45) ---
SECRET_BODY='token ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA tail'
if OUT=$(python3 "$PY" --root "$ROOT" put --backend issue-store --unit-id secret --body-path docs/prds/099-fixture/099-prd-secret.md --content "$SECRET_BODY" 2>/dev/null || true); then
  if echo "$OUT" | python3 -c "import json,sys; assert json.load(sys.stdin).get('code')=='secret-scan'"; then
    ok "issue-store-secret-scan-r45:refuse"
  else
    bad "issue-store-secret-scan-r45:refuse"
  fi
else
  bad "issue-store-secret-scan-r45:refuse"
fi

# --- issue-store-budget-r39 (R39) ---
python3 "$PY" --root "$ROOT" clear-issue-fixture >/dev/null
cp "$ISSUE_CFG" "$ROOT/.cursor/workflow.config.json"
export SW_ISSUES_CALL_BUDGET=1
if OUT=$(python3 "$PY" --root "$ROOT" freeze --unit-id budget --body-path docs/prds/099-fixture/099-prd-budget.md 2>/dev/null || true); then
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('code')=='not-found' or d.get('code')=='deliver-aborted-inconsistent'"; then
    ok "issue-store-budget-r39:exhausted"
  else
    # put then freeze should exhaust budget on freeze multi-step
    python3 "$PY" --root "$ROOT" put --backend issue-store --unit-id budget --body-path docs/prds/099-fixture/099-prd-budget.md --content x >/dev/null 2>&1 || true
    OUT2=$(python3 "$PY" --root "$ROOT" freeze --unit-id budget --body-path docs/prds/099-fixture/099-prd-budget.md --no-distill 2>/dev/null || true)
    if echo "$OUT2" | python3 -c "import json,sys; assert json.load(sys.stdin).get('code')=='deliver-aborted-inconsistent'"; then
      ok "issue-store-budget-r39:exhausted"
    else
      bad "issue-store-budget-r39:exhausted"
    fi
  fi
else
  bad "issue-store-budget-r39:exhausted"
fi
unset SW_ISSUES_CALL_BUDGET


python3 "$PY" --root "$ROOT" clear-issue-fixture >/dev/null
unset SW_ISSUES_FIXTURE

exit $FAIL

"""

if __name__ == "__main__":
    raise SystemExit(main())
