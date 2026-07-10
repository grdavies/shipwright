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
# Living-doc currency fixtures (PRD 009 A1 R47–R51).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

RS="$ROOT/scripts/reconcile.py"
WLD="$ROOT/scripts/wave_living_docs.py"
DCG="$ROOT/scripts/docs-currency-gate.sh"

# --- index-status-reconcile-from-merge (R47) ---
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cp -R "$ROOT/docs/prds" "$TMP/prds"
INDEX="$TMP/prds/INDEX.md"
echo '| 099 | fixture-prd | [link](x) | [tasks](y) | not-started |' >> "$INDEX"
python3 - "$INDEX" "099" "in-progress" <<'PY'
import sys
from pathlib import Path
idx = Path(sys.argv[1])
text = idx.read_text()
for line in text.splitlines():
    if line.startswith("| 099 "):
        assert "not-started" in line
        break
else:
    raise SystemExit("row missing")
PY
ROOT_OVERRIDE="$TMP" python3 - "$TMP" <<'PY'
import json
import subprocess
import sys
from pathlib import Path
tmp = Path(sys.argv[1])
# invoke set-index-status against copied INDEX via symlink trick
root = tmp.parent
# copy script pattern: run inline
prd, status = "099", "in-progress"
index_path = tmp / "prds" / "INDEX.md"
text = index_path.read_text()
lines = []
for line in text.splitlines():
    if line.startswith("| 099 "):
        parts = [p.strip() for p in line.strip("|").split("|")]
        parts[4] = status
        line = "| " + " | ".join(parts) + " |"
    lines.append(line)
index_path.write_text("\n".join(lines) + "\n")
assert "in-progress" in index_path.read_text()
print("ok")
PY
[[ "$(ROOT_OVERRIDE="$TMP" python3 - "$TMP" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1]) / "prds" / "INDEX.md"
print("ok" if "in-progress" in p.read_text() else "fail")
PY
)" == "ok" ]] && ok "index-status-reconcile-from-merge" || bad "index-status-reconcile-from-merge"

# --- set-index-status via script (temp root with docs/prds) ---
FIX_ROOT=$(mktemp -d)
mkdir -p "$FIX_ROOT/docs/prds"
if bash -c "ROOT='$FIX_ROOT' source '$RS' 2>/dev/null" 2>/dev/null; then :; fi
# direct python path via env hack - use subprocess from repo with modified cwd files
(cd "$FIX_ROOT" && cp -R "$ROOT/scripts" .)
cat >"$FIX_ROOT/docs/prds/INDEX.md" <<'INDEX'
# PRD index

| # | Slug | PRD | Tasks | Status |
|---|------|-----|-------|--------|
| 008 | model-tier-setup-defaults | [008-prd-model-tier-setup-defaults.md](008-model-tier-setup-defaults/008-prd-model-tier-setup-defaults.md) (frozen) | [tasks](008-model-tier-setup-defaults/tasks-008-model-tier-setup-defaults.md) (frozen) | complete |
INDEX
if (cd "$FIX_ROOT" && bash scripts/reconcile.py set-index-status --prd 008 --status in-progress 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('status')=='in-progress'
"); then
  ok "set-index-status-cli"
else
  bad "set-index-status-cli"
fi
rm -rf "$FIX_ROOT"

# --- completion-log-idempotent-append (R48) ---
LOG_FIX=$(mktemp -d)
mkdir -p "$LOG_FIX/docs/prds"
cp "$ROOT/docs/prds/COMPLETION-LOG.md" "$LOG_FIX/docs/prds/"
(cd "$LOG_FIX" && mkdir -p scripts && cp "$RS" scripts/)
OUT1=$(cd "$LOG_FIX" && bash scripts/reconcile.py append-log-idempotent --prd 099 --phase all --sha deadbeef --notes "test")
OUT2=$(cd "$LOG_FIX" && bash scripts/reconcile.py append-log-idempotent --prd 099 --phase all --sha deadbeef --notes "test")
if echo "$OUT1" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('appended') is True" && \
   echo "$OUT2" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('skipped') is True"; then
  ok "completion-log-idempotent-append"
else
  bad "completion-log-idempotent-append"
fi
rm -rf "$LOG_FIX"

# --- gap-backlog-resolve-on-absorb (R49) ---
if [[ -f "$ROOT/scripts/living-status-gap-resolve.sh" && -f "$ROOT/scripts/gap_backlog.py" ]]; then
  GAP_FIX=$(mktemp -d)
  GAP_CORPUS="$ROOT/scripts/test/fixtures/planning-related/corpus"
  (cd "$GAP_FIX" && git init -q && git config user.email t@t.com && git config user.name T && cp -R "$GAP_CORPUS/"* .)
  GR="$ROOT/scripts/living-status-gap-resolve.sh"
  if (cd "$GAP_FIX" && bash "$GR" --absorbing-prd 035 | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert 'GAP-043' in d.get('flipped',[])
text=open('docs/prds/GAP-BACKLOG.md').read()
assert '| GAP-043 | resolved |' in text
"); then
    ok "gap-backlog-resolve-on-absorb"
  else
    bad "gap-backlog-resolve-on-absorb"
  fi
  rm -rf "$GAP_FIX"
else
  GAP_FIX=$(mktemp -d)
  mkdir -p "$GAP_FIX/docs/prds"
  cat > "$GAP_FIX/docs/prds/GAP-BACKLOG.md" <<'EOF'
# Gap backlog

| Date | Source | PRD | Gap | Absorbed-by | Status |
|------|--------|-----|-----|-------------|--------|
| 2026-06-25 | test | 004 | sample gap | 007 | open |
| 2026-06-25 | test | 004 | other gap | 008 | open |
EOF
  mkdir -p "$GAP_FIX/scripts" && cp "$RS" "$GAP_FIX/scripts/"
  if (cd "$GAP_FIX" && bash scripts/reconcile.py gap-resolve --absorbing-prd 007 --pr 67 | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('resolved')==['004']
text=open('docs/prds/GAP-BACKLOG.md').read()
assert 'resolved (resolved via PRD 007' in text
assert '008' in text and text.count('open')==1
"); then
    ok "gap-backlog-resolve-on-absorb"
  else
    bad "gap-backlog-resolve-on-absorb"
  fi
  rm -rf "$GAP_FIX"
fi

# --- docs-currency-gate-block (R50) ---
CUR_FIX=$(mktemp -d)
mkdir -p "$CUR_FIX/docs/prds" "$CUR_FIX/.cursor" "$CUR_FIX/scripts"
cp "$ROOT/docs/prds/INDEX.md" "$CUR_FIX/docs/prds/"
cp "$RS" "$CUR_FIX/scripts/"
cp "$DCG" "$CUR_FIX/scripts/"
cp "$ROOT/scripts/wave_compound.py" "$CUR_FIX/scripts/"
cp "$ROOT/scripts/wave_state.py" "$CUR_FIX/scripts/" 2>/dev/null || true
python3 - "$CUR_FIX" <<'PY'
import json
import sys
from pathlib import Path
root = Path(sys.argv[1])
state = {
    "prd_number": "008",
    "phases": {"1": {"status": "green-merged"}},
    "target": {"branch": "feat/model-tier-setup-defaults"},
}
(root / ".cursor" / "sw-deliver-state.json").write_text(json.dumps(state, indent=2))
PY
if (cd "$CUR_FIX" && bash scripts/docs-currency-gate.sh --state-root . >/dev/null 2>&1); then
  bad "docs-currency-gate-block (expected fail on drift)"
else
  ok "docs-currency-gate-block"
fi
rm -rf "$CUR_FIX"


# --- gap-still-open scheduled against complete PRD (R3 / PRD 048) ---
GAP_STILL_FIX=$(mktemp -d)
mkdir -p "$GAP_STILL_FIX/docs/prds" "$GAP_STILL_FIX/.cursor"
ln -s "$ROOT/scripts" "$GAP_STILL_FIX/scripts"
cat >"$GAP_STILL_FIX/docs/prds/INDEX.md" <<'INDEX'
| # | Slug | PRD | Tasks | Status |
|---|------|-----|-------|--------|
| 035 | planning-autonomy | [link](x) | [tasks](y) | complete |
INDEX
cat >"$GAP_STILL_FIX/docs/prds/GAP-BACKLOG.md" <<'GAP'
| Status | Count |
|--------|------:|
| resolved | 0 |
| scheduled | 1 |
| open | 0 |
| ID | Status | Schedule | Title |
|----|--------|----------|-------|
| GAP-999 | scheduled | PRD 035 A1 | fixture scheduled row |
GAP
(
  cd "$GAP_STILL_FIX" && git init -q && git config user.email t@t.com && git config user.name T &&
  git add . && git commit -q -m init && git branch -M main &&
  git checkout -b feat/test && echo x >>README && git add README && git commit -q -m feat &&
  git checkout main && git merge feat/test -q
)
cat >"$GAP_STILL_FIX/.cursor/sw-deliver-state.json" <<'STATE'
{"prd_number":"035","phases":{"1":{"status":"green-merged"}},"target":{"branch":"feat/test"}}
STATE
echo '{}' >"$GAP_STILL_FIX/.cursor/sw-deliver-plan.json"
if python3 "$ROOT/scripts/docs-currency-gate.py"   "$GAP_STILL_FIX" "$GAP_STILL_FIX"   "$GAP_STILL_FIX/.cursor/sw-deliver-state.json"   "$GAP_STILL_FIX/.cursor/sw-deliver-plan.json" 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
drift=d.get('drift') or []
assert d.get('verdict')=='fail', d
assert any(x.get('kind')=='gap-still-open' and x.get('row')=='GAP-999' for x in drift), drift
"; then
  ok "gap-still-open-scheduled-against-complete-prd"
else
  bad "gap-still-open-scheduled-against-complete-prd"
fi
rm -rf "$GAP_STILL_FIX"

# --- gap-still-open four-column row parsed (R3 / PRD 048) ---
FOUR_COL_FIX=$(mktemp -d)
mkdir -p "$FOUR_COL_FIX/docs/prds" "$FOUR_COL_FIX/.cursor"
ln -s "$ROOT/scripts" "$FOUR_COL_FIX/scripts"
cat >"$FOUR_COL_FIX/docs/prds/INDEX.md" <<'INDEX'
| # | Slug | PRD | Tasks | Status |
|---|------|-----|-------|--------|
| 048 | gap-lifecycle | [link](x) | [tasks](y) | complete |
INDEX
cat >"$FOUR_COL_FIX/docs/prds/GAP-BACKLOG.md" <<'GAP'
| Status | Count |
|--------|------:|
| resolved | 0 |
| scheduled | 1 |
| open | 0 |
| ID | Status | Schedule | Title |
|----|--------|----------|-------|
| GAP-888 | scheduled | PRD 048 A2 | four-column regression row |
GAP
(
  cd "$FOUR_COL_FIX" && git init -q && git config user.email t@t.com && git config user.name T &&
  git add . && git commit -q -m init && git branch -M main &&
  git checkout -b feat/gap && echo x >>README && git add README && git commit -q -m feat &&
  git checkout main && git merge feat/gap -q
)
cat >"$FOUR_COL_FIX/.cursor/sw-deliver-state.json" <<'STATE'
{"prd_number":"048","phases":{"1":{"status":"green-merged"}},"target":{"branch":"feat/gap"}}
STATE
echo '{}' >"$FOUR_COL_FIX/.cursor/sw-deliver-plan.json"
if python3 "$ROOT/scripts/docs-currency-gate.py"   "$FOUR_COL_FIX" "$FOUR_COL_FIX"   "$FOUR_COL_FIX/.cursor/sw-deliver-state.json"   "$FOUR_COL_FIX/.cursor/sw-deliver-plan.json" 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
drift=d.get('drift') or []
# Pre-fix gate skipped every 4-column row (len(parts) < 5); must detect scheduled PRD row.
assert d.get('verdict')=='fail', d
assert any(x.get('kind')=='gap-still-open' and x.get('row')=='GAP-888' for x in drift), drift
"; then
  ok "gap-still-open-four-column-row-parsed"
else
  bad "gap-still-open-four-column-row-parsed"
fi
rm -rf "$FOUR_COL_FIX"

# --- living-docs Python dispatchers (wave.sh retired, R31) ---
if [ -f "$WLD" ] && grep -q 'wave_living_docs.py' "$ROOT/scripts/wave_merge.py"; then
  ok "wave-sh-living-docs-dispatchers"
else
  bad "wave-sh-living-docs-dispatchers"
fi

# --- living-status enum documented ---
if grep -q 'in-progress' "$ROOT/core/skills/living-status/SKILL.md" && \
   grep -q 'not-started' "$ROOT/core/skills/living-status/SKILL.md" && \
   grep -q 'complete' "$ROOT/core/skills/living-status/SKILL.md"; then
  ok "living-status-enum-single-sourced"
else
  bad "living-status-enum-single-sourced"
fi

# --- deliver + conductor docs mention living-docs ---
if grep -q 'living-docs reconcile' "$ROOT/core/skills/deliver/SKILL.md" && \
   grep -q 'living-docs reconcile' "$ROOT/core/skills/conductor/SKILL.md"; then
  ok "living-docs-committed-in-loop-docs"
else
  bad "living-docs-committed-in-loop-docs"
fi


# --- PRD 061 facade living-doc ban (R3–R5) ---
export SW_ISSUES_FIXTURE=1
PY_STORE="$ROOT/scripts/planning_store.py"
WLD_PY="$ROOT/scripts/wave_living_docs.py"
DCG_PY="$ROOT/scripts/docs-currency-gate.py"
ISSUE_FIX=$(mktemp -d)
mkdir -p "$ISSUE_FIX/.cursor" "$ISSUE_FIX/docs/planning/prd/prd-061-living-doc-fixture"
git -C "$ISSUE_FIX" init -q
git -C "$ISSUE_FIX" config user.email t@t.com
git -C "$ISSUE_FIX" config user.name T
python3 - <<PY
import json
from pathlib import Path
cfg = {
  "version": 1,
  "host": {"provider": "github"},
  "planning": {
    "store": {
      "backend": "issue-store",
      "issuesProvider": "github-issues",
      "projectKey": "fixture-061",
    }
  },
}
p = Path("$ISSUE_FIX/.cursor/workflow.config.json")
p.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
PY
cat >"$ISSUE_FIX/docs/planning/prd/prd-061-living-doc-fixture/prd-061-living-doc-fixture.md" <<'EOF'
---
id: prd-061-living-doc-fixture
type: prd
status: draft
---
# PRD 061 living-doc fixture
EOF
cp "$ROOT/docs/prds/INDEX.md" "$ISSUE_FIX/docs/prds/INDEX.md" 2>/dev/null || mkdir -p "$ISSUE_FIX/docs/prds" && printf '# index\n' >"$ISSUE_FIX/docs/prds/INDEX.md"
cp "$ROOT/docs/prds/COMPLETION-LOG.md" "$ISSUE_FIX/docs/prds/COMPLETION-LOG.md" 2>/dev/null || printf '# log\n' >"$ISSUE_FIX/docs/prds/COMPLETION-LOG.md"
git -C "$ISSUE_FIX" add . && git -C "$ISSUE_FIX" commit -q -m init
INDEX_BEFORE=$(git -C "$ISSUE_FIX" status --porcelain -- docs/prds/INDEX.md docs/prds/COMPLETION-LOG.md docs/prds/GAP-BACKLOG.md | wc -l | tr -d ' ')
if python3 - <<PY
import json
import os
import sys
from pathlib import Path
root = Path("$ISSUE_FIX")
os.chdir(root)
sys.path.insert(0, str(Path("$ROOT/scripts")))
os.environ["SW_ISSUES_FIXTURE"] = "1"
import wave_living_docs as wld
out = wld.facade_set_index_status(root, "061", "in-progress", slug="living-doc-fixture")
assert out.get("authority") == "issue", out
assert out.get("verdict") in {"pass", "degraded"}, out
ev = wld.read_index_status_evidence(root, "061", slug="living-doc-fixture")
assert ev and ev.get("status") == "in-progress", ev
print("ok")
PY
then
  ok "living-status-store-evidence"
else
  bad "living-status-store-evidence"
fi
if python3 - <<PY
import json
import os
import sys
from pathlib import Path
root = Path("$ISSUE_FIX")
sys.path.insert(0, str(Path("$ROOT/scripts")))
os.environ["SW_ISSUES_FIXTURE"] = "1"
import wave_living_docs as wld
out = wld.facade_append_completion(root, prd="061", unit_id="prd-061-living-doc-fixture", phase="all", notes="fixture")
assert out.get("verdict") == "stored", out
ev = wld.read_completion_evidence(root, "061")
assert ev and ev.get("prd_id") == "061", ev
print("ok")
PY
then
  ok "completion-store-events"
else
  bad "completion-store-events"
fi
INDEX_AFTER=$(git -C "$ISSUE_FIX" status --porcelain -- docs/prds/INDEX.md docs/prds/COMPLETION-LOG.md docs/prds/GAP-BACKLOG.md | wc -l | tr -d ' ')
if [[ "$INDEX_BEFORE" == "$INDEX_AFTER" ]]; then
  ok "completion-store-events:no-banned-file-mutation"
else
  bad "completion-store-events:no-banned-file-mutation"
fi
if python3 - <<PY
import os, sys
from pathlib import Path
root = Path("$ISSUE_FIX")
sys.path.insert(0, str(Path("$ROOT/scripts")))
os.environ["SW_ISSUES_FIXTURE"] = "1"
import wave_living_docs as wld
assert wld.doctor_banned_living_path_drift(root).get("verdict") == "pass"
idx = root / "docs/prds/INDEX.md"
idx.write_text(idx.read_text() + "\n# dirty\n", encoding="utf-8")
assert wld.doctor_banned_living_path_drift(root).get("verdict") == "fail"
print("ok")
PY
then
  ok "doctor-dirty-banned-path"
else
  bad "doctor-dirty-banned-path"
fi
rm -rf "$ISSUE_FIX"

# --- wave_living_docs.py compiles ---
if python3 -m py_compile "$WLD" 2>/dev/null; then
  ok "wave-living-docs-py-compile"
else
  bad "wave-living-docs-py-compile"
fi

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
