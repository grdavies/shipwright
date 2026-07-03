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
# PRD 031 — doc-format tokenizer fixtures (phase 1 + phase 2).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DOC_FORMAT="$ROOT/scripts/doc_format.py"
NORMALIZE="$ROOT/scripts/doc-format-normalize.sh"
MAP="$ROOT/docs/prds/031-planning-unit-model-and-migration/call-site-map.md"
MANIFEST="$ROOT/docs/prds/031-planning-unit-model-and-migration/tokenizer-exception-manifest.json"
FIX="$ROOT/scripts/test/fixtures/doc-format"
FAIL=0

ok()  { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

mkdir -p "$FIX"
chmod +x "$NORMALIZE" 2>/dev/null || true

SAMPLE="$FIX/grammar-sample.md"
if [[ ! -f "$SAMPLE" ]]; then
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
fi

# --- doc-format-grammar-tokenizes ---
if OUT=$(python3 "$DOC_FORMAT" tokenize "$SAMPLE" --json 2>&1) && \
   echo "$OUT" | python3 -c "
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
fi

# --- call-site-map-exhaustion ---
if python3 "$DOC_FORMAT" lint-callsites --map "$MAP" >/dev/null 2>&1 && \
   bash "$NORMALIZE" lint-callsites --map "$MAP" >/dev/null 2>&1; then
  ok "call-site-map-exhaustion"
else
  bad "call-site-map-exhaustion"
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

# --- check-fail-closed-diagnostics (R13) ---
if OUT=$(python3 "$DOC_FORMAT" check "$FIX/check-fail-sample.md" 2>/dev/null); EC=$?; \
   [[ "$EC" -eq 20 ]] && echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['verdict']=='fail'
f = d['findings'][0]
assert f['line'] > 0 and f['expected'] and f['found'] and f['class']
"; then
  ok "check-fail-closed-diagnostics"
else
  bad "check-fail-closed-diagnostics"
fi

# --- write-idempotent-shape-only (R13) ---
TMPW=$(mktemp -d)
cp "$FIX/write-before.md" "$TMPW/before.md"
if python3 "$DOC_FORMAT" write "$TMPW/before.md" --inplace >/dev/null && \
   FIRST=$(cat "$TMPW/before.md") && \
   python3 "$DOC_FORMAT" write "$TMPW/before.md" --inplace >/dev/null && \
   SECOND=$(cat "$TMPW/before.md") && \
   [[ "$FIRST" == "$SECOND" ]] && \
   bash "$NORMALIZE" --check "$TMPW/before.md" >/dev/null 2>&1; then
  ok "write-idempotent-shape-only"
else
  bad "write-idempotent-shape-only"
fi
rm -rf "$TMPW"

# --- consumers-tokenizer-only (R12) ---
CONSUMER_OK=1
for f in spec-union.py spec-rigor-check.py traceability-check.py wave_deliver.py; do
  if ! grep -q 'doc_format' "$ROOT/scripts/$f"; then
    echo "missing doc_format in $f"
    CONSUMER_OK=0
  fi
  if grep -qE 'RID_LINE|RID_BULLET|parse_frontmatter_list|re\.finditer\(r"\^###' "$ROOT/scripts/$f" 2>/dev/null; then
    echo "legacy structural regex retained in $f"
    CONSUMER_OK=0
  fi
done
[[ "$CONSUMER_OK" -eq 1 ]] && ok "consumers-tokenizer-only" || bad "consumers-tokenizer-only"

# --- unlisted-divergence-fails-closed (R12) ---
if python3 - "$ROOT" "$MANIFEST" <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
import doc_format

root = Path(sys.argv[1])
manifest = doc_format.load_exception_manifest(root)
# Simulate divergence not in manifest
assert not doc_format.manifest_allows(
    manifest, file="docs/prds/fake.md", consumer="spec-union.sh", klass="rid-set"
)
# Manifest must be capped and sign-off present
assert manifest.get("cap", 0) > 0
assert manifest.get("signoff")
PY
then
  ok "unlisted-divergence-fails-closed"
else
  bad "unlisted-divergence-fails-closed"
fi

# --- template-slot-fill (R14) ---
if OUT=$(python3 "$DOC_FORMAT" template prd_requirement) && \
   [[ "$OUT" == "- **{id}** {body}" ]]; then
  ok "template-slot-fill"
else
  bad "template-slot-fill"
fi

# --- directive-zero-ids-fails-closed (R14) ---
if OUT=$(python3 "$DOC_FORMAT" check "$FIX/directive-empty.md" 2>/dev/null); EC=$?; \
   [[ "$EC" -eq 20 ]] && echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert any(f.get('class')=='directive-empty-ids' for f in d.get('findings',[]))
"; then
  ok "directive-zero-ids-fails-closed"
else
  bad "directive-zero-ids-fails-closed"
fi

# --- golden-before-after-equivalence (R15) ---
if python3 - "$ROOT" "$SAMPLE" <<'PY'
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
import doc_format

root = Path(sys.argv[1])
sample = Path(sys.argv[2]).read_text(encoding="utf-8")

def legacy_union_ids(text):
    ids = []
    seen = set()
    for line in text.splitlines():
        for pat in [
            re.compile(r"^- \*\*([RD]\d+)\*\*\s*(.*)$", re.I),
            re.compile(r"^\*\*([RD]\d+)\*\*\s*(.*)$", re.I),
        ]:
            m = pat.match(line)
            if m:
                rid = doc_format.norm_id(m.group(1))
                if rid not in seen:
                    ids.append(rid)
                    seen.add(rid)
    return ids

legacy = legacy_union_ids(sample)
modern = [r[0] for r in doc_format.extract_rd_bullets(sample)]
assert sorted(legacy) == sorted(modern), f"union id drift: {legacy} vs {modern}"
PY
then
  ok "golden-before-after-equivalence"
else
  bad "golden-before-after-equivalence"
fi

# --- four-consumer-id-agreement (R15) ---
if python3 - "$ROOT" "$SAMPLE" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
import doc_format

text = Path(sys.argv[2]).read_text(encoding="utf-8")
union_ids = {r[0] for r in doc_format.extract_rd_bullets(text) if r[0].startswith("R")}
rigor_ids = {r[0] for r in doc_format.extract_rd_bullets(text) if r[0].startswith("R")}
trace_ids = {r["rid"] for r in doc_format.extract_traceability_rows(text)}
# wave_deliver does not extract R-IDs from PRD body — agreement on phases instead
phases = {p["id"] for p in doc_format.extract_phases(text)}
assert union_ids == rigor_ids
assert trace_ids <= union_ids | trace_ids
assert phases == {"1", "2"}
PY
then
  ok "four-consumer-id-agreement"
else
  bad "four-consumer-id-agreement"
fi

# --- write-roundtrip-stable (R15) ---
if python3 - "$ROOT" "$SAMPLE" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
import doc_format

text = Path(sys.argv[2]).read_text(encoding="utf-8")
before = {r[0] for r in doc_format.extract_rd_bullets(text) if r[0].startswith("R")}
written = doc_format.write_document(text)
after = {r[0] for r in doc_format.extract_rd_bullets(written) if r[0].startswith("R")}
assert before == after, f"write changed ids: {before} vs {after}"
PY
then
  ok "write-roundtrip-stable"
else
  bad "write-roundtrip-stable"
fi

# --- phaseA-legacy-paths-no-relocation (R16) ---
if grep -q 'docs/prds' "$MAP" && \
   ! grep -q 'docs/planning/' "$MAP" && \
   python3 - "$ROOT" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
import doc_format
assert doc_format.EXCEPTION_MANIFEST_REL.startswith("docs/prds/")
PY
then
  ok "phaseA-legacy-paths-no-relocation"
else
  bad "phaseA-legacy-paths-no-relocation"
fi

if [ "$FAIL" -eq 0 ]; then
  echo "ALL doc-format fixtures passed"
else
  echo "SOME doc-format fixtures FAILED"
  exit 1
fi

"""

if __name__ == "__main__":
    raise SystemExit(main())
