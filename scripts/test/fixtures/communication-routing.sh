#!/usr/bin/env bash
# Communication routing fixtures (PRD 006 R11).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
FAIL=0

SESSION_CTX="$ROOT/core/hooks/session-context.md"
if grep -qE '`/caveman`' "$SESSION_CTX" || \
   grep -qiE 'stop caveman|/caveman (lite|full|ultra)|as if the user sent.*/caveman' "$SESSION_CTX"; then
  echo "FAIL session-context still references phantom /caveman"
  FAIL=1
else
  echo "OK  communication-no-phantom-slash"
fi

RESOLVE="$ROOT/scripts/communication-resolve.sh"
for pair in "sw-prd:lite" "sw-triage:ultra" "sw-doc-review:normal"; do
  cmd="${pair%%:*}"
  want="${pair##*:}"
  got=$(bash "$RESOLVE" "$cmd" | python3 -c "import json,sys; print(json.load(sys.stdin)['intensity'])")
  if [[ "$got" == "$want" ]]; then
    echo "OK  communication-resolve $cmd -> $want"
  else
    echo "FAIL communication-resolve $cmd expected $want got $got"
    FAIL=1
  fi
done

DEFAULTS="$ROOT/core/sw-reference/communication-routing.defaults.json"
CMD_COUNT=$(python3 -c "import json; print(len(json.load(open('$DEFAULTS'))['routing']['commands']))")
if [[ "$CMD_COUNT" -ge 34 ]]; then
  echo "OK  communication-routing-defaults-complete ($CMD_COUNT commands)"
else
  echo "FAIL communication-routing-defaults expected >=34 commands got $CMD_COUNT"
  FAIL=1
fi

if python3 -c "
import json
from pathlib import Path
schema = json.loads(Path('$ROOT/.sw/config.schema.json').read_text())
enum = schema['properties']['communication']['properties']['defaultIntensity']['enum']
assert 'wenyan-full' not in enum
assert set(enum) == {'normal', 'lite', 'full', 'ultra'}
"; then
  echo "OK  communication-schema-rejects-wenyan"
else
  echo "FAIL schema enum should be four values only"
  FAIL=1
fi

CORE="$ROOT/core/communication/caveman-core.md"
LINES=$(wc -l < "$CORE" | tr -d ' ')
if [[ "$LINES" -le 35 ]]; then
  echo "OK  communication-caveman-core-line-count ($LINES)"
else
  echo "FAIL caveman-core exceeds 35 lines ($LINES)"
  FAIL=1
fi

if grep -rq 'wenyan' "$ROOT/core/communication" "$ROOT/core/sw-reference/communication-routing.defaults.json" 2>/dev/null; then
  echo "FAIL wenyan referenced in bundled communication files"
  FAIL=1
else
  echo "OK  communication-no-wenyan"
fi

MISSING=0
for f in "$ROOT"/core/commands/sw-*.md; do
  if ! grep -qF 'Communication intensity:' "$f"; then
    echo "FAIL missing Communication intensity in $(basename "$f")"
    MISSING=1
  fi
done
if [[ "$MISSING" -eq 0 ]]; then
  echo "OK  communication-command-intensity-lines"
fi
FAIL=$((FAIL + MISSING))

if [[ -f "$ROOT/core/commands/sw-caveman.md" ]]; then
  echo "OK  communication-sw-caveman-registered"
else
  echo "FAIL sw-caveman.md missing"
  FAIL=1
fi

exit $FAIL
