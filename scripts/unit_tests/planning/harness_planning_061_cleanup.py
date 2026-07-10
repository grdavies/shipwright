#!/usr/bin/env python3
"""PRD 061 task 1.4 — R3a cleanup command with legacy vs newly-written classification."""
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
# PRD 061 task 1.4 — cleanup-idempotent (R3a): legacy vs newly-written classification.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT/scripts:${PYTHONPATH:-}"
export SW_ISSUES_FIXTURE=1
PY_STORE="$ROOT/scripts/planning_store.py"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

init_sep_repo() {
  local dest="$1"
  mkdir -p "$dest/.cursor"
  git -C "$dest" init -q
  git -C "$dest" config user.email t@t.com
  git -C "$dest" config user.name T
  python3 - <<PY
import json
from pathlib import Path
cfg = {
  "version": 1,
  "host": {"provider": "github"},
  "planning": {
    "store": {
      "backend": "issue-store",
      "issuesProvider": "github-issues",
      "projectKey": "fixture-061-cleanup",
      "storeLocation": {"mode": "separate-project", "owner": "grdavies", "repo": "planning"},
    }
  },
}
Path("$dest/.cursor/workflow.config.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
PY
  git -C "$dest" add .cursor/workflow.config.json
  git -C "$dest" commit -q -m init
}

REPO=$(mktemp -d)
init_sep_repo "$REPO"
LEGACY_REL="docs/prds/_fixture-cleanup/legacy-prd.md"
mkdir -p "$REPO/docs/prds/_fixture-cleanup"
printf '%s\n' '# legacy tracked' >"$REPO/$LEGACY_REL"
git -C "$REPO" add "$LEGACY_REL"
git -C "$REPO" commit -q -m "legacy tracked body"

# --- cleanup-idempotent (R3a): doctor passes on legacy clean tree ---
if OUT=$(python3 "$PY_STORE" --root "$REPO" doctor 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('verdict') == 'pass', d
"; then
  ok "cleanup-idempotent:doctor-legacy-clean-pass"
else
  bad "cleanup-idempotent:doctor-legacy-clean-pass"
fi

# --- cleanup dry-run reports legacy classification ---
if OUT=$(python3 "$PY_STORE" --root "$REPO" cleanup 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('verdict') == 'ok', d
assert d.get('action') == 'cleanup', d
assert d.get('dryRun') is True, d
counts = d.get('counts', {})
assert counts.get('legacy-tracked-pending-cleanup', 0) >= 1, d
assert '$LEGACY_REL' in d.get('legacy', []), d
"; then
  ok "cleanup-idempotent:dry-run-legacy-count"
else
  bad "cleanup-idempotent:dry-run-legacy-count"
fi

# --- apply untracks legacy paths ---
if OUT=$(python3 "$PY_STORE" --root "$REPO" cleanup --apply 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('verdict') == 'ok', d
assert d.get('dryRun') is False, d
counts = d.get('counts', {})
assert counts.get('legacy-tracked-pending-cleanup', 0) >= 1, d
applied = d.get('applied', [])
assert '$LEGACY_REL' in applied, d
"; then
  ok "cleanup-idempotent:apply-untracks-legacy"
else
  bad "cleanup-idempotent:apply-untracks-legacy"
fi

# --- second apply is idempotent (zero legacy actions) ---
if OUT=$(python3 "$PY_STORE" --root "$REPO" cleanup --apply 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('verdict') == 'ok', d
counts = d.get('counts', {})
assert counts.get('legacy-tracked-pending-cleanup', 0) == 0, d
assert d.get('applied', []) == [], d
"; then
  ok "cleanup-idempotent:second-apply-noop"
else
  bad "cleanup-idempotent:second-apply-noop"
fi

# --- newly-written staged add fails doctor ---
NEW_REPO=$(mktemp -d)
init_sep_repo "$NEW_REPO"
NEW_STRAY="docs/prds/_fixture-cleanup/new-write.md"
mkdir -p "$NEW_REPO/docs/prds/_fixture-cleanup"
printf '%s\n' '# newly written' >"$NEW_REPO/$NEW_STRAY"
git -C "$NEW_REPO" add "$NEW_STRAY"
set +e
NEW_OUT=$(python3 "$PY_STORE" --root "$NEW_REPO" doctor 2>/dev/null)
NEW_RC=$?
set -e
if [[ "$NEW_RC" -eq 20 ]] && echo "$NEW_OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('verdict') == 'fail', d
assert '$NEW_STRAY' in d.get('paths', []) or any('$NEW_STRAY' in p for p in d.get('paths', [])), d
"; then
  ok "cleanup-idempotent:newly-written-doctor-fail"
else
  bad "cleanup-idempotent:newly-written-doctor-fail"
fi

if OUT=$(python3 "$PY_STORE" --root "$NEW_REPO" cleanup 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('verdict') == 'ok', d
counts = d.get('counts', {})
assert counts.get('newly-written', 0) >= 1, d
assert '$NEW_STRAY' in d.get('newlyWritten', []), d
"; then
  ok "cleanup-idempotent:newly-written-classified"
else
  bad "cleanup-idempotent:newly-written-classified"
fi

# --- file-store skipped ---
FILE_REPO=$(mktemp -d)
init_sep_repo "$FILE_REPO"
python3 - <<PY
import json
from pathlib import Path
p = Path("$FILE_REPO/.cursor/workflow.config.json")
cfg = json.loads(p.read_text(encoding="utf-8"))
cfg["planning"]["store"] = {"backend": "in-repo-public"}
p.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
PY
if OUT=$(python3 "$PY_STORE" --root "$FILE_REPO" cleanup 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('verdict') == 'ok', d
assert d.get('skipped') is True, d
"; then
  ok "cleanup-idempotent:file-store-skipped"
else
  bad "cleanup-idempotent:file-store-skipped"
fi

rm -rf "$REPO" "$NEW_REPO" "$FILE_REPO"
exit $FAIL
"""

if __name__ == "__main__":
    raise SystemExit(main())
