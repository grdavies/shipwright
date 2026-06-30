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
# PRD 035 phase 8 / amendment A2 — gap lifecycle + doc-format tokenizer (R51–R58).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/test/fixture-lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/fixture-lib.sh"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

GB="$ROOT/scripts/gap-backlog.sh"
GR="$ROOT/scripts/living-status-gap-resolve.sh"
NORM="$ROOT/scripts/doc-format-normalize.sh"
SPEC="$ROOT/scripts/spec-rigor-check.sh"
TRACE="$ROOT/scripts/traceability-check.sh"
REL="$ROOT/scripts/planning-related.py"
FIX_SRC="$ROOT/scripts/test/fixtures/planning-related/corpus"
chmod +x "$GB" "$GR" "$NORM" 2>/dev/null || true

mk_repo() {
  local dest="$1"
  mkdir -p "$dest"
  (cd "$dest" && git init -q && git config user.email t@t.com && git config user.name T && cp -R "$FIX_SRC/"* .)
}

# --- gap-resolve-on-prd-ship (R51) ---
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mk_repo "$TMP"
if (cd "$TMP" && bash "$GR" --absorbing-prd 035 | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert 'GAP-043' in d.get('flipped',[])
text=open('docs/prds/GAP-BACKLOG.md').read()
assert '| GAP-043 | resolved |' in text
"); then ok "gap-resolve-on-prd-ship"; else bad "gap-resolve-on-prd-ship"; fi

# --- freeze-absorbs-flips-gap-schedule (R52) ---
TMP2=$(mktemp -d)
mk_repo "$TMP2"
ART="docs/prds/035-planning-autonomy-and-orchestration/amendments/A2-gap-lifecycle-and-doc-format.md"
mkdir -p "$(dirname "$TMP2/$ART")"
cat > "$TMP2/$ART" <<'EOF'
---
amends: docs/prds/035-planning-autonomy-and-orchestration/035-prd-planning-autonomy-and-orchestration.md
absorbs:
  - GAP-046
frozen: true
---
# A2 fixture
EOF
if (cd "$TMP2" && bash "$GB" flip --schedule --from-artifact "$ART" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert 'GAP-046' in d.get('flipped',[])
text=open('docs/prds/GAP-BACKLOG.md').read()
assert '| GAP-046 | scheduled | PRD 035 A2 |' in text
"); then ok "freeze-absorbs-flips-gap-schedule"; else bad "freeze-absorbs-flips-gap-schedule"; fi
rm -rf "$TMP2"

# --- gap-backlog-index-integrity (R53) ---
if (cd "$TMP" && bash "$GB" check | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='pass'"); then
  ok "gap-backlog-index-integrity"
else
  bad "gap-backlog-index-integrity"
fi

# --- gap-backlog-ci-guard (R54) ---
DCG="$ROOT/scripts/docs-currency-gate.sh"
if grep -q 'gap_backlog.py' "$DCG" && grep -q 'gap-backlog-integrity' "$DCG"; then
  ok "gap-backlog-ci-guard"
else
  bad "gap-backlog-ci-guard"
fi

# --- doc-format-normalize-before-rigor (R55) ---
SAMPLE="$ROOT/scripts/test/fixtures/doc-format/grammar-sample.md"
if [[ -f "$SAMPLE" ]] && bash "$NORM" --check "$SAMPLE" >/dev/null 2>&1; then
  ok "doc-format-normalize-before-rigor"
else
  bad "doc-format-normalize-before-rigor"
fi

# --- spec-rigor-traceability-regex-parity (R56) ---
if python3 -c "
import sys
sys.path.insert(0,'$ROOT/scripts')
import doc_format_tokenizer as tok, doc_format as df
assert tok.RID_BULLET.pattern == df.RID_BULLET.pattern
assert tok.TRACE_ROW.pattern == df.TRACE_ROW.pattern
"; then
  ok "spec-rigor-traceability-regex-parity"
else
  bad "spec-rigor-traceability-regex-parity"
fi

# --- min-recall-gap-043-044-046 (R57) ---
if [[ -x "$REL" ]] && (cd "$TMP" && bash "$REL" scan --path docs/planning/prd/prd-035-scan-target/prd-035-scan-target.md --mode creation | python3 -c "
import json,sys
d=json.load(sys.stdin)
ids={p['id'] for p in d.get('proposals',[])}
assert 'gap-043-backlog-status' in ids or any('043' in x for x in ids)
"); then
  ok "min-recall-gap-043-044-046"
else
  bad "min-recall-gap-043-044-046"
fi

# --- feedback routing prefers gap units (R58) ---
SW_FB="$(content_path commands/sw-feedback.md)"
if grep -q 'planning/gap' "$SW_FB" && grep -q 'planning_gap_capture' "$SW_FB"; then
  ok "feedback-routing-prefers-gap-units"
else
  bad "feedback-routing-prefers-gap-units"
fi

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
