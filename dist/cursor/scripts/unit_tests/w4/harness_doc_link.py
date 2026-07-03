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
# Fixtures for brainstorm↔PRD frontmatter traceability (PRD 009 phase 9 — R52–R55).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CHECK="$ROOT/scripts/doc-link-check.py"
DOC_LINK="$ROOT/scripts/doc_link.py"
LAYOUT="$ROOT/.sw/layout.md"
SW_PRD="$(find "$ROOT/core" -path '*/commands/sw-prd.md' | head -1)"
SW_FREEZE="$(find "$ROOT/core" -path '*/commands/sw-freeze.md' | head -1)"
FAIL=0

ok()  { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

FIX=$(mktemp -d)
trap 'rm -rf "$FIX"' EXIT
mkdir -p "$FIX/docs/brainstorms" "$FIX/docs/prds/099-fixture"

BS="$FIX/docs/brainstorms/2026-06-25-fixture-requirements.md"
PRD="$FIX/docs/prds/099-fixture/099-prd-fixture.md"
cat > "$BS" <<'EOF'
---
date: 2026-06-25
topic: fixture
---
# Fixture brainstorm
EOF

cat > "$PRD" <<'EOF'
---
date: 2026-06-25
topic: fixture
---
# Fixture PRD
EOF

# --- prd-brainstorm-backref-written (R52) ---
python3 "$DOC_LINK" write-backref --root "$FIX" --brainstorm "$BS" --prd "$PRD" >/dev/null
if grep -q '^brainstorm: docs/brainstorms/2026-06-25-fixture-requirements.md' "$PRD"; then
  ok "prd-brainstorm-backref-written: brainstorm back-reference on PRD"
else
  bad "prd-brainstorm-backref-written: missing brainstorm: on PRD"
fi

# --- brainstorm-prd-forwardref-written (R53) ---
python3 "$DOC_LINK" write-forwardref --root "$FIX" --brainstorm "$BS" --prd "$PRD" >/dev/null
if grep -q '^prd: docs/prds/099-fixture/099-prd-fixture.md' "$BS"; then
  ok "brainstorm-prd-forwardref-written: forward prd: on writable brainstorm"
else
  bad "brainstorm-prd-forwardref-written: missing prd: on brainstorm"
fi

# frozen brainstorm untouched
cat > "$BS" <<'EOF'
---
date: 2026-06-25
topic: fixture
frozen: true
frozen_at: 2026-06-25
---
# Frozen brainstorm
EOF
OUT=$(python3 "$DOC_LINK" write-forwardref --root "$FIX" --brainstorm "$BS" --prd "$PRD" 2>/dev/null || true)
if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get('skipped') else 1)"; then
  ok "brainstorm-prd-forwardref-written: frozen brainstorm skipped"
else
  bad "brainstorm-prd-forwardref-written: should skip frozen brainstorm"
fi

# --- doc-link-traceability-gate (R54) ---
bash "$CHECK" --root "$FIX" --path "docs/prds/099-fixture/099-prd-fixture.md" --tier full >/dev/null 2>&1 && \
  ok "doc-link-traceability-gate: linked Full-tier PRD passes" || \
  bad "doc-link-traceability-gate: linked PRD should pass"

cat > "$PRD" <<'EOF'
---
date: 2026-06-25
topic: fixture
---
# Missing link
EOF
set +e
bash "$CHECK" --root "$FIX" --path "docs/prds/099-fixture/099-prd-fixture.md" --tier full >/dev/null 2>&1
EC=$?
set -e
if [[ "$EC" -eq 20 ]]; then
  ok "doc-link-traceability-gate: missing brainstorm fails closed"
else
  bad "doc-link-traceability-gate: expected exit 20 got $EC"
fi

if grep -q 'brainstorm:' "$LAYOUT" && grep -q 'prd:' "$LAYOUT"; then
  ok "doc-link-traceability-gate: layout documents fields"
else
  bad "doc-link-traceability-gate: layout missing brainstorm/prd fields"
fi

# --- freeze-verifies-doc-linkage (R55) ---
if grep -q 'doc-link-check.py' "$SW_FREEZE" && grep -q '\-\-tier full' "$SW_FREEZE"; then
  ok "freeze-verifies-doc-linkage: sw-freeze documents doc-link-check"
else
  bad "freeze-verifies-doc-linkage: sw-freeze missing doc-link-check"
fi

if grep -q 'write-backref' "$SW_PRD" && grep -q 'brainstorm:' "$SW_PRD"; then
  ok "freeze-verifies-doc-linkage: sw-prd documents brainstorm backref"
else
  bad "freeze-verifies-doc-linkage: sw-prd missing backref procedure"
fi

# legacy source_brainstorm alias accepted
cat > "$PRD" <<'EOF'
---
date: 2026-06-25
topic: fixture
source_brainstorm: docs/brainstorms/2026-06-25-fixture-requirements.md
---
# Legacy alias
EOF
bash "$CHECK" --root "$FIX" --path "docs/prds/099-fixture/099-prd-fixture.md" --tier full >/dev/null 2>&1 && \
  ok "doc-link-traceability-gate: source_brainstorm legacy alias resolves" || \
  bad "doc-link-traceability-gate: legacy alias should pass"

if [[ "$FAIL" -ne 0 ]]; then
  echo "doc-link fixtures: FAIL"
  exit 1
fi
echo "doc-link fixtures: PASS"

"""

if __name__ == "__main__":
    raise SystemExit(main())
