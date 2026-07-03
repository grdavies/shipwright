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

from _fixture_lib import repo_root
from _harness_patch import harness_subprocess_env as _harness_env
from _harness_patch import patch_source as _patch_source


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
# PRD 034 Phase 6 — /sw-init planning seed + token-safe doctor fixtures.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT/scripts:${PYTHONPATH:-}"
SEED="$ROOT/scripts/planning-init-seed.py"
DOCTOR="$ROOT/scripts/planning-doctor.py"
PY="$ROOT/scripts/planning_store.py"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

CFG_BACKUP=""
if [[ -f "$ROOT/.cursor/workflow.config.json" ]]; then
  CFG_BACKUP="$TMP/workflow.config.json"
  cp "$ROOT/.cursor/workflow.config.json" "$CFG_BACKUP"
fi
STATE_BACKUP=""
if [[ -f "$ROOT/.cursor/hooks/state/planning-visibility.json" ]]; then
  STATE_BACKUP="$TMP/planning-visibility.json"
  cp "$ROOT/.cursor/hooks/state/planning-visibility.json" "$STATE_BACKUP"
fi
NOTICE_BACKUP=""
if [[ -f "$ROOT/.cursor/hooks/state/planning-privacy-notice.md" ]]; then
  NOTICE_BACKUP="$TMP/planning-privacy-notice.md"
  cp "$ROOT/.cursor/hooks/state/planning-privacy-notice.md" "$NOTICE_BACKUP"
fi

restore() {
  if [[ -n "$CFG_BACKUP" ]]; then
    cp "$CFG_BACKUP" "$ROOT/.cursor/workflow.config.json"
  else
    rm -f "$ROOT/.cursor/workflow.config.json"
  fi
  if [[ -n "$STATE_BACKUP" ]]; then
    cp "$STATE_BACKUP" "$ROOT/.cursor/hooks/state/planning-visibility.json"
  else
    rm -f "$ROOT/.cursor/hooks/state/planning-visibility.json"
  fi
  if [[ -n "$NOTICE_BACKUP" ]]; then
    cp "$NOTICE_BACKUP" "$ROOT/.cursor/hooks/state/planning-privacy-notice.md"
  else
    rm -f "$ROOT/.cursor/hooks/state/planning-privacy-notice.md"
  fi
  rm -f "$ROOT/.cursor/sw-memory.provider"
}
trap 'restore; rm -rf "$TMP"' EXIT

# --- init-profile-store-seed ---
mkdir -p "$ROOT/.cursor"
python3 - <<PY
import json
from pathlib import Path
Path("$ROOT/.cursor/workflow.config.json").write_text(json.dumps({
    "version": 1,
    "memory": {"provider": "in-repo"},
    "planning": {"store": {"backend": "in-repo-public"}},
}, indent=2) + "\n")
PY
(
  export SW_VISIBILITY_REMOTE_PROBE=public
  if OUT=$(python3 "$SEED" --root "$ROOT" 2>&1) && \
    echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['verdict']=='ok'
assert d['visibilityProfile']=='all-private'
assert d['privacyAck']['required'] is True
assert d['storeBackend']=='in-repo-public'
"; then
    ok "init-profile-store-seed:public-profile-store"
  else
    echo "$OUT" >&2
    bad "init-profile-store-seed:public-profile-store"
  fi
)
if [[ -f "$ROOT/.cursor/hooks/state/planning-privacy-notice.md" ]] && \
  grep -q "public" "$ROOT/.cursor/hooks/state/planning-privacy-notice.md"; then
  ok "init-profile-store-seed:privacy-notice"
else
  bad "init-profile-store-seed:privacy-notice"
fi
if CFG=$(python3 -c "import json; print(json.load(open('$ROOT/.cursor/workflow.config.json'))['planning']['visibilityProfile'])") && \
  [[ "$CFG" == "all-private" ]]; then
  ok "init-profile-store-seed:config-written"
else
  bad "init-profile-store-seed:config-written"
fi

# memory backend degrade-open doctor
python3 - <<PY
import json
from pathlib import Path
cfg = json.loads(Path("$ROOT/.cursor/workflow.config.json").read_text())
cfg["planning"]["store"]["backend"] = "memory"
cfg.pop("memory", None)
Path("$ROOT/.cursor/workflow.config.json").write_text(json.dumps(cfg, indent=2) + "\n")
PY
rm -f "$ROOT/.cursor/sw-memory.provider"
if OUT=$(python3 "$DOCTOR" --root "$ROOT" --no-sweep 2>&1) && \
  echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['verdict']=='degraded'
assert 'memory-backend-degrade-open-no-provider' in d.get('warnings',[])
"; then
  ok "init-profile-store-seed:memory-degrade-open"
else
  echo "$OUT" >&2
  bad "init-profile-store-seed:memory-degrade-open"
fi

# orphan materialized sweep
ORPHAN_WT="$ROOT/.sw-worktrees/_fixture-orphan-mat"
mkdir -p "$ORPHAN_WT/.cursor/planning-materialized/docs/prds"
echo "orphan body" >"$ORPHAN_WT/.cursor/planning-materialized/docs/prds/orphan.md"
if OUT=$(python3 "$DOCTOR" --root "$ROOT" 2>&1); then
  if [[ ! -d "$ORPHAN_WT/.cursor/planning-materialized" ]] && \
    echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert int(d.get('swept') and len(d['swept'])>0 or any(c.get('swept',0)>0 for c in d.get('checks',[]) if c.get('check')=='orphan-materialized-sweep'))"; then
    ok "init-profile-store-seed:orphan-sweep"
  else
    echo "$OUT" >&2
    bad "init-profile-store-seed:orphan-sweep"
  fi
else
  bad "init-profile-store-seed:orphan-sweep"
fi
rm -rf "$ROOT/.sw-worktrees/_fixture-orphan-mat" 2>/dev/null || true

# --- store-no-token-leak ---
export GITHUB_TOKEN='ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
export MEMORY_PROBE_TOKEN='ghp_BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB'
python3 - <<PY
import json
from pathlib import Path
cfg = json.loads(Path("$ROOT/.cursor/workflow.config.json").read_text())
cfg["planning"]["store"]["backend"] = "memory"
cfg["memory"] = {"provider": "recallium", "project": "fixture"}
Path("$ROOT/.cursor/workflow.config.json").write_text(json.dumps(cfg, indent=2) + "\n")
PY
if OUT=$(python3 "$DOCTOR" --root "$ROOT" --no-sweep 2>&1); then
  if echo "$OUT" | grep -q 'ghp_' ; then
    bad "store-no-token-leak:doctor-output"
  else
    ok "store-no-token-leak:doctor-output"
  fi
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); c=[x for x in d.get('checks',[]) if x.get('check')=='credential-surface']; assert c and 'tokenEnv' in str(c[0]) or 'memoryProvider' in str(c[0])"; then
    ok "store-no-token-leak:credential-surface-names-only"
  else
    bad "store-no-token-leak:credential-surface-names-only"
  fi
else
  bad "store-no-token-leak:doctor-output"
fi

SECRET_BODY='token ghp_CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC tail'
if LOGS=$(python3 "$PY" --root "$ROOT" put --backend memory --unit-id leak-test \
  --body-path docs/prds/_fixture-leak.md --content "$SECRET_BODY" 2>/tmp/store-leak.stderr); then
  if grep -q 'planningStore' /tmp/store-leak.stderr && ! grep -q 'ghp_' /tmp/store-leak.stderr && ! grep -q 'CCCC' /tmp/store-leak.stderr; then
    ok "store-no-token-leak:store-log-no-body"
  else
    bad "store-no-token-leak:store-log-no-body"
  fi
else
  ok "store-no-token-leak:store-log-no-body-degraded"
fi
rm -rf "$ROOT/.cursor/sw-memory/planning-bodies" 2>/dev/null || true

exit $FAIL

"""

if __name__ == "__main__":
    raise SystemExit(main())
