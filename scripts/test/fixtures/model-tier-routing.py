#!/usr/bin/env python3
"""Ported fixture helper (R27)."""
from __future__ import annotations
import os, re, subprocess, sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent.parent))
from _fixture_lib import repo_root

from _harness_patch import patch_source as _patch_source

def main() -> int:
    root = repo_root(__file__)
    env = os.environ.copy(); env['ROOT']=str(root)
    env['PYTHONPATH']=str(root/'scripts')+os.pathsep+env.get('PYTHONPATH','')
    return subprocess.run(['bash','-c',_patch_source(_SOURCE,root)],cwd=str(root),env=env,shell=False).returncode
_SOURCE = r"""
#!/usr/bin/env bash
# Model tier routing fixtures (PRD 008 R12, R19, R23).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
FAIL=0

EXAMPLE="$ROOT/core/sw-reference/workflow.config.example.json"
DEFAULTS="$ROOT/core/sw-reference/model-routing.defaults.json"
RESOLVE="$ROOT/scripts/resolve-model-tier.sh"
MODEL_CHECK="$ROOT/scripts/model-tier-check.sh"
ROUTING_CHECK="$ROOT/scripts/model-routing-check.sh"

# --- four-tier example passes tier-check ---
set +e
OUT=$(bash "$MODEL_CHECK" --config "$EXAMPLE" 2>/dev/null)
EC=$?
set -e
if [[ "$EC" -eq 0 ]] && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get('verdict')=='pass' else 1)"; then
  echo "OK  model-tier-check four-tier example"
else
  echo "FAIL model-tier-check four-tier example (ec=$EC)"
  FAIL=1
fi

# --- model-routing-check coverage ---
set +e
ROUT_OUT=$(bash "$ROUTING_CHECK" --config "$EXAMPLE" 2>/dev/null)
ROUT_EC=$?
set -e
if [[ "$ROUT_EC" -eq 0 ]] && echo "$ROUT_OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get('verdict')=='pass' else 1)"; then
  echo "OK  model-routing-check coverage"
else
  echo "FAIL model-routing-check (ec=$ROUT_EC)"
  FAIL=1
fi

# --- representative resolution paths ---
resolve_pair() {
  local label="$1"
  shift
  local want_tier="$1"
  local want_model="$2"
  shift 2
  local got
  got=$(bash "$RESOLVE" "$@" --config "$EXAMPLE" 2>/dev/null) || true
  if echo "$got" | python3 -c "
import json,sys
d=json.load(sys.stdin)
tier, mid = d.get('tier'), d.get('modelId')
want_t, want_m = sys.argv[1], sys.argv[2]
if tier != want_t or mid != want_m:
    print(f'tier={tier} modelId={mid}', file=sys.stderr)
    sys.exit(1)
" "$want_tier" "$want_model"; then
    echo "OK  resolve $label -> $want_tier -> $want_model"
  else
    echo "FAIL resolve $label expected $want_tier/$want_model got: $got"
    FAIL=1
  fi
}

resolve_pair "sw-prd" deep claude-opus-4-8-thinking-high --command sw-prd
resolve_pair "sw-triage" cheap composer-2.5-fast --command sw-triage
resolve_pair "sw-execute" build composer-2.5 --command sw-execute
resolve_pair "sw-gaps" mid gpt-5.5-medium --command sw-gaps
resolve_pair "sw-doc delegate sw-prd" deep claude-opus-4-8-thinking-high --command sw-doc --delegate sw-prd

# --- inherit sentinel ---
INH=$(bash "$RESOLVE" --command sw-ship --config "$EXAMPLE" 2>/dev/null)
if echo "$INH" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get('tier')=='inherit' and d.get('modelId') is None else 1)"; then
  echo "OK  resolve inherit sentinel sw-ship"
else
  echo "FAIL resolve inherit sentinel got: $INH"
  FAIL=1
fi

# --- defaults completeness ---
CMD_COUNT=$(python3 -c "import json; print(len(json.load(open('$DEFAULTS'))['routing']['commands']))")
SKILL_COUNT=$(python3 -c "import json; print(len(json.load(open('$DEFAULTS'))['routing']['skills']))")
if [[ "$CMD_COUNT" -ge 36 && "$SKILL_COUNT" -ge 25 ]]; then
  echo "OK  model-routing-defaults-complete ($CMD_COUNT commands, $SKILL_COUNT skills)"
else
  echo "FAIL model-routing-defaults expected >=36 commands and >=25 skills got $CMD_COUNT/$SKILL_COUNT"
  FAIL=1
fi

# --- models-tiering four-tier doc ---
TIERING="$ROOT/.sw/models-tiering.md"
if grep -q '`mid`' "$TIERING" && grep -q 'Claude mid collapse' "$TIERING" && grep -q 'resolve-model-tier.sh' "$TIERING"; then
  echo "OK  models-tiering four-tier doc"
else
  echo "FAIL models-tiering missing four-tier / resolver / Claude mid collapse"
  FAIL=1
fi

# --- configuration guide Models section ---
if grep -q 'models.tiers' "$ROOT/docs/guides/configuration.md" && grep -q 'Model tier routing' "$ROOT/docs/guides/configuration.md"; then
  echo "OK  configuration guide models section"
else
  echo "FAIL configuration guide models section"
  FAIL=1
fi

# --- command Model tier lines match defaults (R19) ---
if python3 - "$ROOT" <<'PY'
import json
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
defaults = json.loads((root / "core/sw-reference/model-routing.defaults.json").read_text())
cmd_map = defaults["routing"]["commands"]
pat = re.compile(r"\*\*Model tier:\*\*\s+(\S+)")
missing = mismatch = 0
for path in sorted((root / "core/commands").glob("sw-*.md")):
    text = path.read_text(encoding="utf-8")
    slug = path.stem
    m = pat.search(text)
    if not m:
        print(f"FAIL missing Model tier in {path.name}")
        missing += 1
        continue
    stamped = m.group(1)
    want = cmd_map.get(slug)
    if want is None:
        print(f"FAIL {slug} not in defaults")
        mismatch += 1
        continue
    if stamped != want:
        print(f"FAIL {slug} stamped {stamped!r} defaults {want!r}")
        mismatch += 1
if missing == 0 and mismatch == 0:
    print(f"OK  command Model tier lines ({len(cmd_map)} commands)")
    sys.exit(0)
sys.exit(1)
PY
then
  :
else
  FAIL=1
fi

# --- subagent-dispatch mid/deep refs (R9) ---
DISPATCH="$ROOT/core/rules/sw-subagent-dispatch.mdc"
if grep -q 'models.tiers.mid' "$DISPATCH" && grep -q 'models.routing' "$DISPATCH"; then
  echo "OK  subagent-dispatch mid/deep routing refs"
else
  echo "FAIL subagent-dispatch missing mid/routing refs"
  FAIL=1
fi

exit $FAIL

"""
if __name__=="__main__": raise SystemExit(main())
