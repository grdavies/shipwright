#!/usr/bin/env python3
"""Ported fixture suite (R27) — embedded harness executed without on-disk shell files."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))

from _fixture_lib import repo_root
from _harness_patch import patch_source as _patch_source


def main() -> int:
    root = repo_root(__file__)
    env = os.environ.copy()
    env["ROOT"] = str(root)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(root / "scripts" / "test"), str(root / "scripts"), env.get("PYTHONPATH", "")) if p
    )
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
# PRD 035 Phase 1 — related-units scanner + pull-in proposal fixtures.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT/scripts:${PYTHONPATH:-}"
REL_SH="$ROOT/scripts/planning-related.sh"
PY="$ROOT/scripts/planning_related.py"
FIX_SRC="$ROOT/scripts/test/fixtures/planning-related/corpus"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

[[ -x "$REL_SH" ]] || chmod +x "$REL_SH"
[[ -f "$PY" ]] || { bad "planning_related.py missing"; exit 1; }

mk_repo() {
  local dest="$1"
  mkdir -p "$dest"
  (
    cd "$dest"
    git init -q
    git config user.email test@test.com
    git config user.name Test
    cp -R "$FIX_SRC/"* .
    mkdir -p .cursor/hooks/state
  )
}

scan_json() {
  local repo="$1" path="$2" mode="${3:-creation}"
  shift 2
  [[ $# -gt 0 ]] && shift || true
  (cd "$repo" && bash "$REL_SH" scan --path "$path" --mode "$mode")
}

confirm_json() {
  local repo="$1" path="$2" accept="$3"
  shift 3
  (cd "$repo" && bash "$REL_SH" confirm --path "$path" --accept "$accept")
}

# --- scanner-confirm-list-not-autoabsorb (R17) ---
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mk_repo "$TMP"
OUT=$(scan_json "$TMP" docs/planning/prd/prd-035-scan-target/prd-035-scan-target.md)
if echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('autoAbsorb') is False
assert d.get('appliedEdges') == []
assert d.get('verdict')=='ok'
assert len(d.get('proposals',[]))>0
"; then
  ok "scanner-confirm-list-not-autoabsorb"
else
  bad "scanner-confirm-list-not-autoabsorb"
fi

# --- related-deterministic-rank-threshold (R5) ---
if echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert all(p['score'] >= d['rankThreshold'] for p in d['proposals'])
assert any('shared-tags' in ';'.join(p['reasons']) for p in d['proposals'])
"; then
  ok "related-deterministic-rank-threshold"
else
  bad "related-deterministic-rank-threshold"
fi

# --- semantic-optin-flag-gated (R5) ---
BASE=$(echo "$OUT" | python3 -c "import json,sys; print(len(json.load(sys.stdin)['proposals']))")
SEM=$(SW_PULLIN_SEMANTIC=1 scan_json "$TMP" docs/planning/prd/prd-035-scan-target/prd-035-scan-target.md)
if echo "$SEM" | python3 -c "
import json,sys,os
d=json.load(sys.stdin)
assert d['semanticMatching'] is True
"; then
  ok "semantic-optin-flag-gated"
else
  bad "semantic-optin-flag-gated"
fi

# --- min-recall-gap-043-044-046 (R5) ---
if echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
ids={p['id'] for p in d['proposals']}
need={'gap-043-backlog-status','gap-044-stable-ids','gap-046-absorption-flip'}
assert need <= ids, ids
"; then
  ok "min-recall-gap-043-044-046"
else
  bad "min-recall-gap-043-044-046"
fi

# --- private-metadata-only-proposal (R4) ---
if echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
priv=[p for p in d['proposals'] if p['id']=='gap-private-body']
assert priv, 'missing private gap proposal'
blob=json.dumps(priv[0])
assert 'sk_live' not in blob
assert 'SECRET_PRIVATE_BODY' not in blob
assert priv[0]['title']
"; then
  ok "private-metadata-only-proposal"
else
  bad "private-metadata-only-proposal"
fi

# --- related-repeat-suppression (R5) ---
OUT2=$(scan_json "$TMP" docs/planning/prd/prd-035-scan-target/prd-035-scan-target.md)
if echo "$OUT2" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert isinstance(d.get('suppressedRepeat'), list)
"; then
  ok "related-repeat-suppression"
else
  bad "related-repeat-suppression"
fi

# --- frozen-pull-in-routes-amendment (R7) ---
FROZ=$(scan_json "$TMP" docs/planning/prd/prd-frozen-target/prd-frozen-target.md)
CF=$(confirm_json "$TMP" docs/planning/prd/prd-frozen-target/prd-frozen-target.md gap-043-backlog-status)
if echo "$CF" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['appliedEdges']==[]
assert all(r.get('route')=='amendment' for r in d['routes'])
"; then
  ok "frozen-pull-in-routes-amendment"
else
  bad "frozen-pull-in-routes-amendment"
fi

# --- prd-pull-in-proposal-confirm (R1) ---
PRD_CF=$(confirm_json "$TMP" docs/planning/prd/prd-035-scan-target/prd-035-scan-target.md gap-043-backlog-status)
if echo "$PRD_CF" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['humanGated'] is True
assert len(d['appliedEdges'])>=1
"; then
  ok "prd-pull-in-proposal-confirm"
else
  bad "prd-pull-in-proposal-confirm"
fi

# --- tasks-rescan-amendment-proposal (R2) ---
TASKS=$(scan_json "$TMP" docs/prds/035-fixture/035-prd-fixture.md tasks-rescan)
if echo "$TASKS" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['mode']=='tasks-rescan'
assert any(p.get('route')=='amendment' for p in d['proposals'] if p['type']=='gap')
"; then
  ok "tasks-rescan-amendment-proposal"
else
  bad "tasks-rescan-amendment-proposal"
fi

# --- absorption-edge-autonomous-choices-gated (R3) ---
TMP3=$(mktemp -d)
mk_repo "$TMP3"
ABS_CF=$(confirm_json "$TMP3" docs/planning/prd/prd-035-scan-target/prd-035-scan-target.md gap-044-stable-ids)
if echo "$ABS_CF" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['autoAbsorb'] is False
assert d['humanGated'] is True
assert len(d.get('appliedEdges',[]))>=1
assert d.get('reconciler') is not None
"; then
  ok "absorption-edge-autonomous-choices-gated"
else
  bad "absorption-edge-autonomous-choices-gated"
fi
rm -rf "$TMP3"

# --- proposal-payload-redaction (R22) ---
if echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
cl=d.get('confirmList','')
assert 'untrusted' in cl and cl.strip().startswith('##')
assert 'sk_live' not in cl
"; then
  ok "proposal-payload-redaction"
else
  bad "proposal-payload-redaction"
fi

# --- emission point registry ---
if OUTE=$(bash "$REL_SH" list-emission-points) && echo "$OUTE" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert 'pull-in-confirm' in d['points']
"; then
  ok "pull-in-emission-point-registered"
else
  bad "pull-in-emission-point-registered"
fi

[[ -f "$ROOT/core/skills/visibility/references/emission-points.md" ]] && grep -q 'pull-in-confirm' "$ROOT/core/skills/visibility/references/emission-points.md" && ok "emission-points-doc" || bad "emission-points-doc"

grep -q 'planning-related.sh scan' "$ROOT/core/commands/sw-prd.md" && ok "sw-prd-pull-in-wired" || bad "sw-prd-pull-in-wired"
grep -q 'planning-related.sh scan' "$ROOT/core/commands/sw-tasks.md" && ok "sw-tasks-rescan-wired" || bad "sw-tasks-rescan-wired"

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
