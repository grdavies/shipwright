#!/usr/bin/env python3
"""PRD 044 Phase 1 — issue-store migration fixtures (SC4, SC4a, SC4b)."""
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
    completed = subprocess.run(
        ["bash", "-c", src],
        cwd=str(root),
        env=env,
        shell=False,
    )
    return completed.returncode


_SOURCE = r"""
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT/scripts:${PYTHONPATH:-}"
PY_MIG="$ROOT/scripts/planning_migrate.py"
PY_STORE="$ROOT/scripts/planning_store.py"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

seed_repo() {
  local dest="$1"
  rm -rf "$dest"
  mkdir -p "$dest/.cursor" "$dest/docs/prds/099-fixture-migrate"
  cat >"$dest/docs/prds/099-fixture-migrate/099-prd-migrate-roundtrip.md" <<'EOF'
---
id: migrate-roundtrip
visibility: public
title: Migrate roundtrip fixture
---
# GOLDEN_MIGRATE_ROUNDTRIP_BODY
EOF
  python3 - <<PY
import json
from pathlib import Path
cfg = {
  "version": 1,
  "planning": {
    "store": {
      "backend": "issue-store",
      "issuesProvider": "github-issues",
      "projectKey": "fixture-migrate",
    }
  },
}
Path("$dest/.cursor/workflow.config.json").write_text(json.dumps(cfg, indent=2) + "\\n", encoding="utf-8")
PY
  (
    cd "$dest"
    git init -q
    git config user.email "fixture@test"
    git config user.name "Fixture"
    git add -A
    git commit -q -m "seed migrate fixture"
  )
}

export SW_ISSUES_FIXTURE=1
REPO="$TMP/migrate-repo"
seed_repo "$REPO"
FIXTURE="$REPO/.cursor/hooks/state/issue-store-fixture.json"
JOURNAL="$REPO/.cursor/hooks/state/issue-store-migration-journal.json"
ARTIFACT="$REPO/docs/prds/099-fixture-migrate/099-prd-migrate-roundtrip.md"

python3 "$PY_STORE" --root "$REPO" clear-issue-fixture >/dev/null || true
FIXTURE_BEFORE=""
if [[ -f "$FIXTURE" ]]; then
  FIXTURE_BEFORE="$(cat "$FIXTURE")"
fi
HASH_BEFORE="$(python3 -c "from pathlib import Path; import sys; sys.path.insert(0, '$ROOT/scripts'); from planning_store import content_hash; from planning_canonical import normalize_body; p=Path('$ARTIFACT'); print(content_hash(normalize_body(p.read_text(encoding='utf-8'))))")"

# --- SC4b: dry-run mutates nothing ---
if OUT=$(python3 "$PY_MIG" "$REPO" store-files-to-issues 2>/dev/null); then
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('mode')=='dry-run'"; then
  if [[ ! -f "$JOURNAL" ]]; then
    if [[ -z "$FIXTURE_BEFORE" ]]; then
      [[ ! -f "$FIXTURE" ]] && ok "SC4b:dry-run-no-journal-fixture" || bad "SC4b:dry-run-no-journal-fixture"
    else
      [[ "$(cat "$FIXTURE")" == "$FIXTURE_BEFORE" ]] && ok "SC4b:dry-run-no-journal-fixture" || bad "SC4b:dry-run-no-journal-fixture"
    fi
  else
    bad "SC4b:journal-created-on-dry-run"
  fi
  else
    bad "SC4b:dry-run-mode"
  fi
else
  bad "SC4b:dry-run-invoke"
fi

# --- SC4: round-trip hash equality ---
python3 "$PY_STORE" --root "$REPO" clear-issue-fixture >/dev/null
rm -f "$JOURNAL"
python3 "$PY_MIG" "$REPO" store-files-to-issues --apply >/dev/null
if [[ -f "$ARTIFACT" ]]; then
  bad "SC4:source-not-removed"
else
  ok "SC4:files-to-issues"
fi
python3 "$PY_MIG" "$REPO" store-issues-to-files --apply >/dev/null
if [[ -f "$ARTIFACT" ]]; then
  HASH_AFTER="$(python3 -c "from pathlib import Path; import sys; sys.path.insert(0, '$ROOT/scripts'); from planning_store import content_hash; from planning_canonical import normalize_body; p=Path('$ARTIFACT'); print(content_hash(normalize_body(p.read_text(encoding='utf-8'))))")"
  if [[ "$HASH_BEFORE" == "$HASH_AFTER" ]]; then
    ok "SC4:round-trip-hash"
  else
    bad "SC4:round-trip-hash"
  fi
else
  bad "SC4:file-not-restored"
fi

# --- SC4a: partial failure resume ---
seed_repo "$REPO"
python3 "$PY_STORE" --root "$REPO" clear-issue-fixture >/dev/null
rm -f "$JOURNAL"
export SW_MIGRATE_INJECT_FAIL_AFTER=created
set +e
python3 "$PY_MIG" "$REPO" store-files-to-issues --apply >/dev/null 2>&1
RC=$?
set -e
if [[ "$RC" -eq 0 ]]; then
  bad "SC4a:inject-should-fail"
elif [[ ! -f "$ARTIFACT" ]]; then
  bad "SC4a:source-removed-before-verify"
elif [[ ! -f "$JOURNAL" ]]; then
  bad "SC4a:journal-missing"
else
  ok "SC4a:inject-halts-before-delete"
fi
unset SW_MIGRATE_INJECT_FAIL_AFTER
python3 "$PY_MIG" "$REPO" store-files-to-issues --apply >/dev/null
if [[ -f "$ARTIFACT" ]]; then
  bad "SC4a:resume-incomplete"
else
  ok "SC4a:resume-completes"
fi

exit $FAIL
"""

if __name__ == "__main__":
    raise SystemExit(main())
