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
# Planning INDEX generator + region-integrity fixtures (PRD 031 phase 5 — R5/R9/R24).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$ROOT/scripts/planning_index_gen.py"
GUARD="$ROOT/scripts/index-region-guard.py"
FIX_SRC="$ROOT/scripts/test/fixtures/planning-index"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

[[ -f "$PY" ]] || { bad "planning_index_gen.py missing"; exit 1; }
[[ -f "$GUARD" ]] || { bad "index-region-guard.py missing"; exit 1; }

inject_region() {
  local file="$1" region="$2" body="$3"
  python3 - "$file" "$region" "$body" <<'PY'
import sys
from pathlib import Path
idx = Path(sys.argv[1])
region = sys.argv[2]
body = sys.argv[3]
text = idx.read_text()
start = f"<!-- planning-index:{region} begin -->"
end = f"<!-- planning-index:{region} end -->"
text = text.split(start, 1)[0] + start + "\n" + body + end + text.split(end, 1)[1]
idx.write_text(text)
PY
}

region_bytes() {
  local repo="$1" file="$2" region="$3"
  python3 - "$ROOT/scripts" "$repo/$file" "$region" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import planning_index_gen as pig
text = Path(sys.argv[2]).read_text()
r = pig.parse_regions(text)
print(getattr(r, sys.argv[3]), end="")
PY
}

# --- single-unified-index-from-frontmatter (R5) ---
TMP=$(mktemp -d)
trap 'rm -rf "$TMP" "$TMP2" "$TMP3" "$GIT_FIX"' EXIT
(
  cd "$TMP"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  mkdir -p docs/planning
  cp -R "$FIX_SRC/units/"* docs/planning/
  python3 "$PY" "$TMP" generate --writer generator >/dev/null
  OUT=$(python3 "$PY" "$TMP" parse)
  echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
s=d['regions']['structural']
assert 'gap-045-parser-parity' in s
assert 'prd-031-planning-unit-model' in s
assert 'Parser parity gap' in s
"
) && ok "single-unified-index-from-frontmatter" || bad "single-unified-index-from-frontmatter"

# --- region-preserve-byte-for-byte (R9) ---
TMP2=$(mktemp -d)
(
  cd "$TMP2"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  mkdir -p docs/planning
  cp -R "$FIX_SRC/units/"* docs/planning/
  python3 "$PY" "$TMP2" generate >/dev/null
  INDEX=docs/planning/INDEX.md
  inject_region "$INDEX" derived $'prd-031-planning-unit-model: in-progress\n'
  inject_region "$INDEX" inFlight $'run-id: deliver-abc\nbranch: feat/sample\nepoch: 1\n'
  BEFORE_D=$(region_bytes "$TMP2" "$INDEX" derived)
  BEFORE_I=$(region_bytes "$TMP2" "$INDEX" inFlight)
  SW_INDEX_REGION_WRITER=generator python3 "$PY" "$TMP2" generate >/dev/null
  AFTER_D=$(region_bytes "$TMP2" "$INDEX" derived)
  AFTER_I=$(region_bytes "$TMP2" "$INDEX" inFlight)
  [[ "$BEFORE_D" == "$AFTER_D" && "$BEFORE_I" == "$AFTER_I" ]]
) && ok "region-preserve-byte-for-byte" || bad "region-preserve-byte-for-byte"

# --- status-precedence-resolves (R9) ---
TMP3=$(mktemp -d)
(
  cd "$TMP3"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  mkdir -p docs/planning
  cp -R "$FIX_SRC/units/"* docs/planning/
  python3 "$PY" "$TMP3" generate >/dev/null
  INDEX=docs/planning/INDEX.md
  inject_region "$INDEX" derived $'prd-031-planning-unit-model: in-progress\n'
  OUT=$(python3 "$PY" "$TMP3" resolve-status --unit prd-031-planning-unit-model)
  echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['consumerStatus']=='in-progress', d
assert d['structuralStatus']=='proposed', d
"
  OUT2=$(python3 "$PY" "$TMP3" resolve-status --unit gap-045-parser-parity)
  echo "$OUT2" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['consumerStatus']=='open', d
assert d['type']=='gap', d
"
) && ok "status-precedence-resolves" || bad "status-precedence-resolves"

# --- region-hook-rejects-cross-writer (R24) ---
GIT_FIX=$(mktemp -d)
(
  cd "$GIT_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  mkdir -p docs/planning
  cp -R "$FIX_SRC/units/"* docs/planning/
  python3 "$PY" "$GIT_FIX" generate >/dev/null
  git add docs/planning
  git commit -q -m "seed index"
  INDEX=docs/planning/INDEX.md
  inject_region "$INDEX" derived $'prd-031-planning-unit-model: complete\n'
  git add "$INDEX"
  set +e
  OUT=$(python3 "$GUARD" --staged --repo-root "$GIT_FIX" 2>&1)
  EC=$?
  set -e
  [[ "$EC" -ne 0 ]] && echo "$OUT" | grep -q 'derived'
) && ok "region-hook-rejects-cross-writer" || bad "region-hook-rejects-cross-writer"

# --- empty-inflight-with-runstate-fails (R24) ---
(
  cd "$GIT_FIX"
  mkdir -p docs/planning/gap/gap-999-inflight-guard
  cp docs/planning/gap/gap-045-parser-parity/gap-045-parser-parity.md \
    docs/planning/gap/gap-999-inflight-guard/gap-999-inflight-guard.md
  python3 -c "from pathlib import Path; p=Path('docs/planning/gap/gap-999-inflight-guard/gap-999-inflight-guard.md'); t=p.read_text(); p.write_text(t.replace('gap-045-parser-parity','gap-999-inflight-guard').replace('Parser parity gap','Inflight guard'))"
  mkdir -p .cursor
  echo '{"verdict":"running","phases":{"1":{"slug":"alpha","status":"in-flight"}},"target":{"branch":"feat/x"}}' \
    > .cursor/sw-deliver-state.x.json
  SW_INDEX_REGION_WRITER=generator python3 "$PY" "$GIT_FIX" generate >/dev/null
  git add docs/planning
  set +e
  OUT=$(python3 "$GUARD" --staged --repo-root "$GIT_FIX" 2>&1)
  EC=$?
  set -e
  [[ "$EC" -ne 0 ]] && echo "$OUT" | grep -qi 'inflight'
) && ok "empty-inflight-with-runstate-fails" || bad "empty-inflight-with-runstate-fails"

# --- living-doc lock wiring ---
if python3 -c "
import sys
sys.path.insert(0,'$ROOT/scripts')
from pathlib import Path
src = Path('$ROOT/scripts/wave_living_docs.py').read_text()
assert 'cmd_regenerate_index' in src
assert 'planning-index-generator' in src
"; then
  ok "living-doc-index-generator-wired"
else
  bad "living-doc-index-generator-wired"
fi

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
