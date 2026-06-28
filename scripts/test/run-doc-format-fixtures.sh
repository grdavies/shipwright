#!/usr/bin/env bash
# PRD 031 phase 1 — doc-format tokenizer engine fixtures (R11, R22, R31).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DOC_FORMAT="$ROOT/scripts/doc_format.py"
NORMALIZE="$ROOT/scripts/doc-format-normalize.sh"
MAP="$ROOT/docs/prds/031-planning-unit-model-and-migration/call-site-map.md"
FIX="$ROOT/scripts/test/fixtures/doc-format"
FAIL=0

ok()  { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

mkdir -p "$FIX"
chmod +x "$NORMALIZE" 2>/dev/null || true

SAMPLE="$FIX/grammar-sample.md"
cat >"$SAMPLE" <<'EOF'
---
date: 2026-06-27
topic: sample
absorbs:
  - GAP-045
supersedes: [R2]
retracts: [R1]
frozen: true
---

# Sample PRD

## Overview

Body text.

## Requirements

- **R11** Tokenizer defines canonical grammar.
- **D1** Decision bullet for union tests.

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |

### 1. Shared doc-format tokenizer engine — L

- [ ] 1.1 Module
  - **File:** `scripts/doc_format.py`, `scripts/doc-format-normalize.sh`
  - **Expected:** tokenize/emit API.

### 2. Adoption — L

- [ ] 2.1 Check modes
  - **File:** `scripts/doc_format.py`

## Traceability

| R-ID | Task | Test scenario |
|------|------|---------------|
| R11 | 1.1 | doc-format-grammar-tokenizes |
| R22 | 1.2 | call-site-map-exhaustion |
EOF

# --- doc-format-grammar-tokenizes ---
if OUT=$(python3 "$DOC_FORMAT" tokenize "$SAMPLE" --json 2>&1) &&    echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
kinds = {t['kind'] for t in d['tokens']}
required = {
    'frontmatter', 'frontmatter_scalar', 'frontmatter_directive_list',
    'section_heading', 'rd_id_bullet', 'phase_heading', 'phase_dependencies_row',
    'file_reference', 'traceability_row',
}
missing = required - kinds
assert not missing, f'missing kinds: {missing}'
absorbs = [t for t in d['tokens'] if t['kind']=='frontmatter_directive_list' and t['data'].get('key')=='absorbs']
assert absorbs and 'GAP-045' in absorbs[0]['data'].get('ids', [])
"; then
  ok "doc-format-grammar-tokenizes"
else
  bad "doc-format-grammar-tokenizes"
  echo "$OUT"
fi

# --- call-site-map-exhaustion ---
if python3 "$DOC_FORMAT" lint-callsites --map "$MAP" >/dev/null 2>&1 &&    bash "$NORMALIZE" lint-callsites --map "$MAP" >/dev/null 2>&1; then
  ok "call-site-map-exhaustion"
else
  bad "call-site-map-exhaustion"
  python3 "$DOC_FORMAT" lint-callsites --map "$MAP" 2>&1 || true
fi

# --- tokenizer-deterministic-offline ---
if python3 - "$DOC_FORMAT" "$SAMPLE" <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).resolve().parent))
import doc_format

mod = Path(sys.argv[1])
assert doc_format.OFFLINE_GUARANTEE is True
assert not doc_format.assert_offline_module(mod)

text = Path(sys.argv[2]).read_text(encoding="utf-8")
a = doc_format.tokenize(text)
b = doc_format.tokenize(text)
ja = json.dumps(a.to_dict(), sort_keys=True)
jb = json.dumps(b.to_dict(), sort_keys=True)
assert ja == jb, "tokenize not deterministic"
ea = doc_format.emit(a)
eb = doc_format.emit(b)
assert ea == eb == text, "emit round-trip failed"
PY
then
  ok "tokenizer-deterministic-offline"
else
  bad "tokenizer-deterministic-offline"
fi

if [ "$FAIL" -eq 0 ]; then
  echo "ALL doc-format phase-1 fixtures passed"
else
  echo "SOME doc-format phase-1 fixtures FAILED"
  exit 1
fi
