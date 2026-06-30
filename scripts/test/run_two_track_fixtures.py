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
# PRD 035 phase 3 — two-track edit driver fixtures (R10–R14, R18, R24).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT/scripts:$ROOT/core/scripts"
PY="$ROOT/scripts/two_track_lib.py"
ROUTE="$ROOT/scripts/docs-edit-route.py"
MERGE="$ROOT/scripts/docs-merge.py"
HOST="$ROOT/scripts/host_lib.py"
INDEX_PY="$ROOT/scripts/planning_index_gen.py"
FIX_UNITS="$ROOT/scripts/test/fixtures/planning-index/units"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

seed_repo() {
  local dir="$1"
  (
    cd "$dir"
    git init -q
    git config user.email test@test.com
    git config user.name Test
    mkdir -p docs/planning docs/prds .cursor
    if [[ -d "$FIX_UNITS" ]]; then
      cp -R "$FIX_UNITS/"* docs/planning/ 2>/dev/null || true
    fi
    python3 "$INDEX_PY" "$dir" generate >/dev/null 2>&1 || true
    touch docs/prds/SUPERSEDED.md docs/prds/GAP-BACKLOG.md
    echo '{"review":{"provider":"none"},"checks":{"treatNeutralAsPass":true}}' > .cursor/workflow.config.json
    git add -A
    git commit -q -m "seed" 2>/dev/null || git commit -q -m "seed" --allow-empty
  )
}

# --- mechanical-allowlist-derived-only ---
TMP=$(mktemp -d)
seed_repo "$TMP"
if OUT=$(python3 "$PY" "$TMP" classify --paths docs/planning/INDEX.md --index-region derived 2>/dev/null) && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['track']=='mechanical', d"; then
  ok "mechanical-allowlist-derived-only"
else
  bad "mechanical-allowlist-derived-only"
fi
rm -rf "$TMP"

# --- inflight-never-mechanical ---
TMP=$(mktemp -d)
seed_repo "$TMP"
if OUT=$(python3 "$PY" "$TMP" classify --paths docs/planning/INDEX.md --index-region inFlight 2>/dev/null) && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['track']=='substantive', d"; then
  ok "inflight-never-mechanical"
else
  bad "inflight-never-mechanical"
fi
rm -rf "$TMP"

# --- planning-path-forced-substantive ---
TMP=$(mktemp -d)
seed_repo "$TMP"
if OUT=$(python3 "$PY" "$TMP" classify --paths docs/planning/gap/gap-045-parser-parity/gap-045-parser-parity.md 2>/dev/null) && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['track']=='substantive', d"; then
  ok "planning-path-forced-substantive"
else
  bad "planning-path-forced-substantive"
fi
rm -rf "$TMP"

# --- frontmatter-edit-substantive-regression ---
TMP=$(mktemp -d)
seed_repo "$TMP"
if OUT=$(python3 "$PY" "$TMP" classify --paths docs/planning/prd/prd-031-planning-unit-model/prd-031-planning-unit-model.md 2>/dev/null) && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['track']=='substantive', d"; then
  ok "frontmatter-edit-substantive-regression"
else
  bad "frontmatter-edit-substantive-regression"
fi
rm -rf "$TMP"

# --- two-track-driver-classify-route ---
TMP=$(mktemp -d)
seed_repo "$TMP"
if OUT=$(bash "$ROUTE" route --path docs/prds/SUPERSEDED.md --dry-run 2>/dev/null) && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['track']=='mechanical', d"; then
  ok "two-track-driver-classify-route:mechanical"
else
  bad "two-track-driver-classify-route:mechanical"
fi
if OUT=$(bash "$ROUTE" route --path docs/planning/gap/gap-045-parser-parity/gap-045-parser-parity.md --topic gap-edit --dry-run 2>/dev/null) && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['track']=='substantive' and d['worktree']['dry_run']==True, d"; then
  ok "two-track-driver-classify-route:substantive"
else
  bad "two-track-driver-classify-route:substantive"
fi
rm -rf "$TMP"

# --- mechanical-batched-auto-merge ---
TMP=$(mktemp -d)
seed_repo "$TMP"
if OUT=$(bash "$MERGE" open --dry-run 2>/dev/null) && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('dry_run') and d.get('hash'), d"; then
  ok "mechanical-batched-auto-merge"
else
  bad "mechanical-batched-auto-merge"
fi
rm -rf "$TMP"

# --- substantive-auto-driven-pr ---
TMP=$(mktemp -d)
seed_repo "$TMP"
if OUT=$(bash "$ROUTE" route-substantive --topic my-doc-topic --dry-run 2>/dev/null) && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['track']=='substantive' and d['pr']['dry_run']==True, d"; then
  ok "substantive-auto-driven-pr"
else
  bad "substantive-auto-driven-pr"
fi
rm -rf "$TMP"

# --- branch-protection-defaults-pr-path ---
TMP=$(mktemp -d)
seed_repo "$TMP"
unset GITHUB_TOKEN GH_TOKEN 2>/dev/null || true
if OUT=$(python3 "$HOST" --root "$TMP" branch-protection-probe --no-cache 2>/dev/null) && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('route')=='pr', d"; then
  ok "branch-protection-defaults-pr-path"
else
  bad "branch-protection-defaults-pr-path"
fi
rm -rf "$TMP"

# --- both-region-content-hash-abort ---
TMP=$(mktemp -d)
seed_repo "$TMP"
OPEN_HASH=$(python3 "$PY" "$TMP" content-hash | python3 -c "import json,sys; print(json.load(sys.stdin)['hash'])")
PYTHONPATH="$ROOT/scripts" python3 - "$TMP" <<'PY'
import sys
from pathlib import Path
import planning_index_gen as pig
tmp = Path(sys.argv[1])
idx = pig.index_path(tmp)
text = idx.read_text(encoding="utf-8")
start, end = pig.REGION_MARKERS["inFlight"]
body = "gap-045-parser-parity:\nrun-id: x\nbranch: feat/x\nepoch: 2\n"
text = text.split(start, 1)[0] + start + "\n" + body + end + text.split(end, 1)[1]
idx.write_text(text)
PY
EC=0
bash "$MERGE" merge-if-ready --hash "$OPEN_HASH" >/dev/null 2>&1 || EC=$?
if [[ "$EC" -ne 0 ]]; then
  ok "both-region-content-hash-abort"
else
  bad "both-region-content-hash-abort"
fi
rm -rf "$TMP"

# --- mechanical-premerge-secret-scan ---
TMP=$(mktemp -d)
seed_repo "$TMP"
DIFF_FILE=$(mktemp)
cat >"$DIFF_FILE" <<'DIFF'
diff --git a/docs/planning/gap/gap-045-parser-parity/gap-045-parser-parity.md b/docs/planning/gap/gap-045-parser-parity/gap-045-parser-parity.md
--- a/docs/planning/gap/gap-045-parser-parity/gap-045-parser-parity.md
+++ b/docs/planning/gap/gap-045-parser-parity/gap-045-parser-parity.md
@@ -1 +1,2 @@
 body
+leak
DIFF
if EC=$(python3 "$PY" "$TMP" validate-mechanical-diff --diff-file "$DIFF_FILE" 2>/dev/null); then
  bad "mechanical-premerge-secret-scan:unit-path"
else
  ok "mechanical-premerge-secret-scan:unit-path"
fi
rm -f "$DIFF_FILE"
GOOD_DIFF=$(mktemp)
cat >"$GOOD_DIFF" <<'DIFF'
diff --git a/docs/prds/SUPERSEDED.md b/docs/prds/SUPERSEDED.md
--- a/docs/prds/SUPERSEDED.md
+++ b/docs/prds/SUPERSEDED.md
@@ -0,0 +1,1 @@
+# superseded
DIFF
if python3 "$PY" "$TMP" validate-mechanical-diff --diff-file "$GOOD_DIFF" >/dev/null 2>&1; then
  ok "mechanical-premerge-secret-scan:allowlist-diff"
else
  bad "mechanical-premerge-secret-scan:allowlist-diff"
fi
SECRET_DIFF=$(mktemp)
cat >"$SECRET_DIFF" <<'DIFF'
diff --git a/docs/prds/GAP-BACKLOG.md b/docs/prds/GAP-BACKLOG.md
--- a/docs/prds/GAP-BACKLOG.md
+++ b/docs/prds/GAP-BACKLOG.md
@@ -1 +1,2 @@
 gap
+token=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DIFF
if bash "$ROOT/scripts/secret-scan.sh" stdin <"$SECRET_DIFF" >/dev/null 2>&1; then
  bad "mechanical-premerge-secret-scan:secret-deny"
else
  ok "mechanical-premerge-secret-scan:secret-deny"
fi
rm -f "$GOOD_DIFF" "$SECRET_DIFF"
rm -rf "$TMP"

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
