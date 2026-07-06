#!/usr/bin/env python3
"""PRD 044 Phase 1+2 — issue-store migration fixtures (SC4, SC4a, SC4b, SC17a–SC17d)."""
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

write_migrate_cfg() {
  local dest="$1"
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
}

commit_repo() {
  local dest="$1"
  local msg="$2"
  (
    cd "$dest"
    git add -A
    git commit -q -m "$msg"
  )
}

seed_repo() {
  local dest="$1"
  rm -rf "$dest"
  mkdir -p "$dest/.cursor" "$dest/docs/prds/099-fixture-migrate"
  write_migrate_cfg "$dest"
  cat >"$dest/docs/prds/099-fixture-migrate/099-prd-migrate-roundtrip.md" <<'EOF'
---
id: migrate-roundtrip
visibility: public
title: Migrate roundtrip fixture
---
# GOLDEN_MIGRATE_ROUNDTRIP_BODY
EOF
  (
    cd "$dest"
    git init -q
    git config user.email "fixture@test"
    git config user.name "Fixture"
  )
  commit_repo "$dest" "seed migrate fixture"
}

fixture_has_label() {
  local fixture="$1"
  local unit_id="$2"
  local label="$3"
  python3 -c "
import json, sys
from pathlib import Path
data = json.loads(Path('$fixture').read_text(encoding='utf-8'))
for rec in data.get('issues', {}).values():
    if rec.get('unit_id') == '$unit_id':
        sys.exit(0 if '$label' in rec.get('labels', []) else 1)
sys.exit(1)
"
}

file_has_frontmatter() {
  local path="$1"
  local key="$2"
  local value="$3"
  python3 -c "
import sys
from pathlib import Path
sys.path.insert(0, '$ROOT/scripts')
from planning_migrate_issue_store import parse_frontmatter_fields
raw = Path('$path').read_text(encoding='utf-8')
fm = parse_frontmatter_fields(raw)
sys.exit(0 if fm.get('$key', '').lower() == '$value'.lower() else 1)
"
}

file_has_sw_edges() {
  local path="$1"
  local rel="$2"
  local target="$3"
  python3 -c "
import sys
from pathlib import Path
sys.path.insert(0, '$ROOT/scripts')
from planning_canonical import parse_edges_block, normalize_body
raw = Path('$path').read_text(encoding='utf-8')
data = parse_edges_block(normalize_body(raw)) or {}
edges = data.get('edges') or []
ok = any(isinstance(e, dict) and e.get('rel') == '$rel' and e.get('target') == '$target' for e in edges)
sys.exit(0 if ok else 1)
"
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

# --- SC17a: frozen round-trip (sw:frozen label) ---
seed_repo "$REPO"
rm -f "$REPO/docs/prds/099-fixture-migrate/099-prd-migrate-roundtrip.md"
cat >"$REPO/docs/prds/099-fixture-migrate/099-prd-migrate-frozen.md" <<'EOF'
---
id: migrate-frozen
visibility: public
title: Frozen migrate fixture
frozen: true
frozen_at: 2026-06-30
---
# FROZEN_MIGRATE_BODY
EOF
commit_repo "$REPO" "sc17a seed"
FROZEN_ARTIFACT="$REPO/docs/prds/099-fixture-migrate/099-prd-migrate-frozen.md"
python3 "$PY_STORE" --root "$REPO" clear-issue-fixture >/dev/null
rm -f "$JOURNAL"
python3 "$PY_MIG" "$REPO" store-files-to-issues --apply >/dev/null
if fixture_has_label "$FIXTURE" "migrate-frozen" "sw:frozen"; then
  ok "SC17a:frozen-label-on-issue"
else
  bad "SC17a:frozen-label-on-issue"
fi
python3 "$PY_MIG" "$REPO" store-issues-to-files --apply >/dev/null
if [[ -f "$FROZEN_ARTIFACT" ]] && file_has_frontmatter "$FROZEN_ARTIFACT" "frozen" "true"; then
  ok "SC17a:frozen-round-trip-file"
else
  bad "SC17a:frozen-round-trip-file"
fi

# --- SC17b: sw-edges block round-trip ---
seed_repo "$REPO"
rm -f "$REPO/docs/prds/099-fixture-migrate/099-prd-migrate-roundtrip.md"
cat >"$REPO/docs/prds/099-fixture-migrate/099-prd-migrate-edges.md" <<'EOF'
---
id: migrate-edges
visibility: public
title: Edges migrate fixture
---
# EDGES_MIGRATE_BODY

```sw-edges
{
  "version": 1,
  "edges": [{"rel": "depends", "target": "other-unit"}],
  "native": []
}
```
EOF
commit_repo "$REPO" "sc17b seed"
EDGES_ARTIFACT="$REPO/docs/prds/099-fixture-migrate/099-prd-migrate-edges.md"
python3 "$PY_STORE" --root "$REPO" clear-issue-fixture >/dev/null
rm -f "$JOURNAL"
python3 "$PY_MIG" "$REPO" store-files-to-issues --apply >/dev/null
if python3 -c "
import json, sys
from pathlib import Path
sys.path.insert(0, '$ROOT/scripts')
from planning_canonical import parse_edges_block, normalize_body
data = json.loads(Path('$FIXTURE').read_text(encoding='utf-8'))
for rec in data.get('issues', {}).values():
    if rec.get('unit_id') != 'migrate-edges':
        continue
    edges = (parse_edges_block(normalize_body(rec.get('body', ''))) or {}).get('edges') or []
    ok = any(isinstance(e, dict) and e.get('rel') == 'depends' and e.get('target') == 'other-unit' for e in edges)
    sys.exit(0 if ok else 1)
sys.exit(1)
"; then
  ok "SC17b:edges-on-issue"
else
  bad "SC17b:edges-on-issue"
fi
python3 "$PY_MIG" "$REPO" store-issues-to-files --apply >/dev/null
if [[ -f "$EDGES_ARTIFACT" ]] && file_has_sw_edges "$EDGES_ARTIFACT" "depends" "other-unit"; then
  ok "SC17b:edges-round-trip-file"
else
  bad "SC17b:edges-round-trip-file"
fi

# --- SC17c: gap status resolved round-trip ---
seed_repo "$REPO"
rm -f "$REPO/docs/prds/099-fixture-migrate/099-prd-migrate-roundtrip.md"
mkdir -p "$REPO/docs/planning/gap/gap-resolved-fixture"
cat >"$REPO/docs/planning/gap/gap-resolved-fixture/gap-resolved-fixture.md" <<'EOF'
---
id: gap-resolved-fixture
type: gap
status: resolved
visibility: public
title: Resolved gap fixture
---
# GAP_RESOLVED_BODY
EOF
commit_repo "$REPO" "sc17c seed"
GAP_ARTIFACT="$REPO/docs/planning/gap/gap-resolved-fixture/gap-resolved-fixture.md"
python3 "$PY_STORE" --root "$REPO" clear-issue-fixture >/dev/null
rm -f "$JOURNAL"
python3 "$PY_MIG" "$REPO" store-files-to-issues --apply >/dev/null
if fixture_has_label "$FIXTURE" "gap-resolved-fixture" "sw:gap-resolved"; then
  ok "SC17c:gap-resolved-label-on-issue"
else
  bad "SC17c:gap-resolved-label-on-issue"
fi
python3 "$PY_MIG" "$REPO" store-issues-to-files --apply >/dev/null
if [[ -f "$GAP_ARTIFACT" ]] && file_has_frontmatter "$GAP_ARTIFACT" "status" "resolved"; then
  ok "SC17c:gap-status-round-trip-file"
else
  bad "SC17c:gap-status-round-trip-file"
fi

# --- SC17d: private artifact refused mid-batch ---
seed_repo "$REPO"
rm -f "$REPO/docs/prds/099-fixture-migrate/099-prd-migrate-roundtrip.md"
cat >"$REPO/docs/prds/099-fixture-migrate/099-prd-migrate-public.md" <<'EOF'
---
id: migrate-public
visibility: public
title: Public migrate fixture
---
# PUBLIC_MIGRATE_BODY
EOF
cat >"$REPO/docs/prds/099-fixture-migrate/099-prd-migrate-private.md" <<'EOF'
---
id: migrate-private
visibility: private
title: Private migrate fixture
---
# PRIVATE_MIGRATE_BODY
EOF
commit_repo "$REPO" "sc17d seed"
PUBLIC_ARTIFACT="$REPO/docs/prds/099-fixture-migrate/099-prd-migrate-public.md"
PRIVATE_ARTIFACT="$REPO/docs/prds/099-fixture-migrate/099-prd-migrate-private.md"
python3 "$PY_STORE" --root "$REPO" clear-issue-fixture >/dev/null
rm -f "$JOURNAL"
if OUT=$(python3 "$PY_MIG" "$REPO" store-files-to-issues --apply 2>/dev/null); then
  if echo "$OUT" | python3 -c "
import json, sys
raw = sys.stdin.read().strip()
dec = json.JSONDecoder()
idx = 0
matched = False
while idx < len(raw):
    chunk = raw[idx:].lstrip()
    if not chunk:
        break
    obj, end = dec.raw_decode(chunk)
    idx += len(raw[idx:]) - len(chunk) + end
    if isinstance(obj, dict) and obj.get('refusedCount') == 1:
        matched = True
        break
sys.exit(0 if matched else 1)
"; then
    ok "SC17d:refused-count"
  else
    bad "SC17d:refused-count"
  fi
  if [[ ! -f "$PUBLIC_ARTIFACT" ]] && [[ -f "$PRIVATE_ARTIFACT" ]]; then
    ok "SC17d:public-removed-private-kept"
  else
    bad "SC17d:public-removed-private-kept"
  fi
else
  bad "SC17d:migrate-invoke"
fi


# --- SC38a: doctor detects created-but-unverified ---
seed_repo "$REPO"
python3 "$PY_STORE" --root "$REPO" clear-issue-fixture >/dev/null
rm -f "$JOURNAL"
export SW_MIGRATE_INJECT_FAIL_AFTER=created
set +e
python3 "$PY_MIG" "$REPO" store-files-to-issues --apply >/dev/null 2>&1
set -e
unset SW_MIGRATE_INJECT_FAIL_AFTER
if OUT=$(python3 "$PY_MIG" "$REPO" store-doctor 2>/dev/null); then
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('action')=='store-doctor' and d.get('issueCount',0)>=1"; then
    ok "SC38a:doctor-detects"
  else
    bad "SC38a:doctor-detects"
  fi
else
  bad "SC38a:doctor-invoke"
fi
python3 "$PY_MIG" "$REPO" store-doctor --apply >/dev/null
python3 "$PY_MIG" "$REPO" store-files-to-issues --apply >/dev/null
if [[ ! -f "$ARTIFACT" ]]; then
  ok "SC38a:doctor-repair-resume"
else
  bad "SC38a:doctor-repair-resume"
fi

# --- SC38b: quiesce refuses active deliver run-state ---
seed_repo "$REPO"
mkdir -p "$REPO/.cursor/sw-deliver-runs/active-phase"
echo '{"verdict":"running"}' >"$REPO/.cursor/sw-deliver-runs/active-phase/status.json"
set +e
python3 "$PY_MIG" "$REPO" store-files-to-issues --apply >/dev/null 2>&1
RC=$?
set -e
if [[ "$RC" -ne 0 ]]; then
  ok "SC38b:quiesce-refuses-deliver"
else
  bad "SC38b:quiesce-refuses-deliver"
fi
rm -rf "$REPO/.cursor/sw-deliver-runs"

# --- SC38c: GAP-BACKLOG shim read-only during transition ---
seed_repo "$REPO"
mkdir -p "$REPO/docs/planning/gap/gap-shim-fixture"
cat >"$REPO/docs/planning/gap/gap-shim-fixture/gap-shim-fixture.md" <<'EOF'
---
id: gap-shim-fixture
type: gap
status: open
visibility: public
title: Shim fixture gap
---
# GAP_SHIM_BODY
EOF
commit_repo "$REPO" "sc38c seed"
python3 "$PY_STORE" --root "$REPO" clear-issue-fixture >/dev/null
rm -f "$JOURNAL"
export SW_MIGRATE_INJECT_FAIL_AFTER=created
set +e
python3 "$PY_MIG" "$REPO" store-files-to-issues --apply >/dev/null 2>&1
set -e
unset SW_MIGRATE_INJECT_FAIL_AFTER
GAP_BACKLOG="$REPO/docs/prds/GAP-BACKLOG.md"
if [[ -f "$GAP_BACKLOG" ]] && grep -q "issue-store-migration-gap-shim" "$GAP_BACKLOG"; then
  ok "SC38c:gap-shim-written"
else
  bad "SC38c:gap-shim-written"
fi
set +e
python3 "$ROOT/scripts/gap_backlog.py" --root "$REPO" flip --resolve --prd test 2>/dev/null
RC=$?
set -e
if [[ "$RC" -ne 0 ]]; then
  ok "SC38c:gap-shim-readonly"
else
  bad "SC38c:gap-shim-readonly"
fi

exit $FAIL
"""

if __name__ == "__main__":
    raise SystemExit(main())
