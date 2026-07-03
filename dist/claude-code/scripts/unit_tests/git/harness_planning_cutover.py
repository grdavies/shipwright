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
# Planning cutover fixtures (PRD 031 phase 7 — R10/R18/R27/R28/R33).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$ROOT/scripts/planning_migrate.py"
PRIV="$ROOT/scripts/planning-privacy-guard.py"
PROJ="$ROOT/scripts/planning_legacy_projection.py"
RELIEF="$ROOT/scripts/relief-acceptance-check.py"
IDX="$ROOT/scripts/planning_index_gen.py"
CORPUS="$ROOT/scripts/test/fixtures/planning-cutover/corpus"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

seed_repo() {
  local dest="$1"
  rm -rf "$dest"
  mkdir -p "$dest"
  cp -R "$CORPUS/." "$dest/"
  (
    cd "$dest"
    git init -q
    git config user.email test@test.com
    git config user.name Test
    git add -A
    git commit -q -m "seed cutover corpus"
  )
}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP" "$TMP2"' EXIT
seed_repo "$TMP/repo"

# cancelled-prd-supersession-edges (R10)
(
  cd "$TMP/repo"
  python3 "$PY" "$TMP/repo" lock-acquire >/dev/null
  python3 "$PY" "$TMP/repo" write --skip-commit >/dev/null
  SS=$(python3 -c "import json; d=json.load(open('.cursor/planning-migration-supersession-map.json')); print(d['edges'][0]['cancelled'])")
  [[ "$SS" == prd-029-doc-format-parser-robustness ]]
  BODY=$(python3 -c "from pathlib import Path; import re; t=Path('docs/planning/prd/prd-029-doc-format-parser-robustness/prd-029-doc-format-parser-robustness-prd-doc-format-parser-robustness.md').read_text(); m=re.search(r'^status: (.+)$', t, re.M); print(m.group(1) if m else '')")
  [[ "$BODY" == superseded ]]
  ABS=$(python3 -c "from pathlib import Path; import re; t=Path('docs/planning/prd/prd-031-planning-unit-model-and-migration/prd-031-planning-unit-model-and-migration-prd-planning-unit-model-and-migration.md').read_text(); print('prd-029-doc-format-parser-robustness' in t)")
  [[ "$ABS" == True ]]
) && ok "cancelled-prd-supersession-edges" || bad "cancelled-prd-supersession-edges"

# privacy-backfill-legacy-token (R18)
(
  cd "$TMP/repo"
  TAG=$(python3 -c "from pathlib import Path; import re; t=Path('docs/planning/brainstorm/brainstorm-2026-01-01-cutover-private-topic-requirements/brainstorm-2026-01-01-cutover-private-topic-requirements.md').read_text(); m=re.search(r'^tags: (.+)$', t, re.M); print(m.group(1) if m else '')")
  [[ "$TAG" == *legacy-pre-034* ]]
  python3 "$PRIV" --repo-root "$TMP/repo" --scan-private >/dev/null
) && ok "privacy-backfill-legacy-token" || bad "privacy-backfill-legacy-token"

# formerly-ignored-body-tracked-fails (R18)
TMP2=$(mktemp -d)
seed_repo "$TMP2/repo2"
(
  cd "$TMP2/repo2"
  python3 "$PY" "$TMP2/repo2" lock-acquire >/dev/null
  python3 "$PY" "$TMP2/repo2" write --skip-commit >/dev/null
  python3 -c "from pathlib import Path; p=Path('.gitignore'); p.write_text('\n'.join(l for l in p.read_text().splitlines() if 'docs/planning/brainstorm' not in l))"
  set +e
  OUT=$(python3 "$PRIV" --repo-root "$TMP2/repo2" --scan-private 2>&1)
  EC=$?
  set -e
  [[ "$EC" -ne 0 ]]
) && ok "formerly-ignored-body-tracked-fails" || bad "formerly-ignored-body-tracked-fails"

# private-index-row-provisional (R33)
(
  cd "$TMP/repo"
  python3 "$IDX" "$TMP/repo" generate >/dev/null
  OUT=$(python3 "$IDX" "$TMP/repo" parse)
  echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert 'private' in d['regions']['structural']"
  grep -q 'planning_visibility (PRD 034 R4)' docs/planning/INDEX.md
) && ok "private-index-row-provisional" || bad "private-index-row-provisional"

# legacy-projection-gapbacklog-index (R27)
(
  cd "$TMP/repo"
  OUT=$(python3 "$PROJ" "$TMP/repo" project)
  echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='pass'"
  grep -q 'GAP-029' docs/prds/GAP-BACKLOG.md
  grep -q '029' docs/prds/INDEX.md
) && ok "legacy-projection-gapbacklog-index" || bad "legacy-projection-gapbacklog-index"

# no-half-migrated-merge (R27)
(
  cd "$TMP/repo"
  python3 "$PROJ" "$TMP/repo" check-half-migrated >/dev/null
) && ok "no-half-migrated-merge" || bad "no-half-migrated-merge"

# relief-acceptance-gates-cutover + kill-criteria-fallback-documented (R28)
(
  cd "$TMP/repo"
  mkdir -p .cursor
  echo '{"phases":{"1":{"slug":"planning-unit-model-and-migration","status":"green-merged"}}}' > .cursor/sw-deliver-state.json
  python3 - "$TMP/repo" "$ROOT/scripts" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
import planning_index_gen as pig
root = Path(sys.argv[1])
path = root / pig.index_rel(root)
path.parent.mkdir(parents=True, exist_ok=True)
content = pig.generate_index(root)
derived = "prd-031-planning-unit-model-and-migration: complete\n"
text = pig.replace_region_inner(content, "derived", derived)
path.write_text(text)
PY
  python3 "$RELIEF" --repo-root "$TMP/repo" --state .cursor/sw-deliver-state.json >/dev/null
  grep -q 'Kill-criteria' "$ROOT/core/sw-reference/layout.md"
  grep -q 'reversible' "$ROOT/core/sw-reference/layout.md"
) && ok "relief-acceptance-gates-cutover" || bad "relief-acceptance-gates-cutover"
ok "kill-criteria-fallback-documented"

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
