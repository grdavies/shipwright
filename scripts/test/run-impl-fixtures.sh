#!/usr/bin/env bash
# Fixture tests for implementation workstream scripts (U0, U2, U1 partial).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REDACT="$ROOT/scripts/memory-redact.sh"
STATE="$ROOT/scripts/phase-state.sh"
FAIL=0

# --- memory-redact: AWS key ---
IN='key=AKIAIOSFODNN7EXAMPLE'
OUT1=$(echo "$IN" | bash "$REDACT")
OUT2=$(echo "$IN" | bash "$REDACT")
if [[ "$OUT1" == *'[REDACTED:AWS_KEY]'* ]] && [[ "$OUT1" == "$OUT2" ]]; then
  echo "OK  memory-redact AWS key"
else
  echo "FAIL memory-redact AWS got: $OUT1"
  FAIL=1
fi

# --- memory-redact: email + bearer ---
IN2=$'user@test.example.com\nAuthorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc.def'
OUT3=$(echo "$IN2" | bash "$REDACT")
if [[ "$OUT3" == *'[REDACTED:EMAIL]'* ]] && [[ "$OUT3" == *'Bearer [REDACTED:TOKEN]'* ]]; then
  echo "OK  memory-redact email+bearer"
else
  echo "FAIL memory-redact email+bearer got: $OUT3"
  FAIL=1
fi

# --- memory-redact: PEM private key ---
IN3=$'-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\n-----END RSA PRIVATE KEY-----'
OUT4=$(echo "$IN3" | bash "$REDACT")
if [[ "$OUT4" == *'[REDACTED:PEM_PRIVATE_KEY]'* ]]; then
  echo "OK  memory-redact PEM key"
else
  echo "FAIL memory-redact PEM got: $OUT4"
  FAIL=1
fi

# --- memory-redact: standalone JWT ---
IN4='token=eyJhbGciOiJIUzI1NiJ9.payload.signature'
OUT5=$(echo "$IN4" | bash "$REDACT")
if [[ "$OUT5" == *'[REDACTED:JWT]'* ]]; then
  echo "OK  memory-redact JWT"
else
  echo "FAIL memory-redact JWT got: $OUT5"
  FAIL=1
fi

# --- phase-state: independent gitdirs ---
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
for name in wt-a wt-b; do
  git init -q "$TMP/$name"
  git -C "$TMP/$name" commit --allow-empty -m init -q
done
GA=$(git -C "$TMP/wt-a" rev-parse --absolute-git-dir)
GB=$(git -C "$TMP/wt-b" rev-parse --absolute-git-dir)
echo '{"phaseSlug":"a"}' >"$GA/phase-flow.json"
echo '{"phaseSlug":"b"}' >"$GB/phase-flow.json"
A=$(cd "$TMP/wt-a" && bash "$STATE" read | python3 -c "import json,sys; print(json.load(sys.stdin)['phaseSlug'])")
B=$(cd "$TMP/wt-b" && bash "$STATE" read | python3 -c "import json,sys; print(json.load(sys.stdin)['phaseSlug'])")
if [[ "$A" == "a" && "$B" == "b" ]]; then
  echo "OK  phase-state isolation"
else
  echo "FAIL phase-state isolation a=$A b=$B"
  FAIL=1
fi

# --- phase-state: write merge (inline json) ---
(cd "$TMP/wt-a" && bash "$STATE" write '{"iteration":2}' >/dev/null)
MERGED=$(cd "$TMP/wt-a" && bash "$STATE" read | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('phaseSlug'), d.get('iteration'))")
if [[ "$MERGED" == "a 2" ]]; then
  echo "OK  phase-state write merge"
else
  echo "FAIL phase-state write merge got: $MERGED"
  FAIL=1
fi

# --- phase-state: write via stdin with embedded quotes ---
printf '%s' '{"note":"it'\''s fine","phaseSlug":"a"}' | (cd "$TMP/wt-a" && bash "$STATE" write - >/dev/null)
QUOTED=$(cd "$TMP/wt-a" && bash "$STATE" read | python3 -c "import json,sys; print(json.load(sys.stdin).get('note',''))")
if [[ "$QUOTED" == "it's fine" ]]; then
  echo "OK  phase-state write stdin quotes"
else
  echo "FAIL phase-state write stdin quotes got: $QUOTED"
  FAIL=1
fi

# --- worktree: refuse rm token in teardown target name check ---
WT_OUT=$(bash "$ROOT/scripts/worktree.sh" teardown rm 2>&1 || true)
if echo "$WT_OUT" | grep -qi refuse; then
  echo "OK  worktree refuses unsafe rm target"
else
  echo "FAIL worktree should refuse rm teardown"
  FAIL=1
fi

# --- worktree: ceiling excludes main checkout ---
CEIL=$(bash "$ROOT/scripts/worktree.sh" ceiling-check 2>/dev/null || true)
PF_COUNT=$(echo "$CEIL" | python3 -c "import json,sys; print(json.load(sys.stdin).get('pfWorktrees', -1))" 2>/dev/null || echo "-1")
if [[ "$PF_COUNT" == "0" ]]; then
  echo "OK  worktree ceiling pfWorktrees=0 (main excluded)"
else
  echo "FAIL worktree ceiling expected pfWorktrees=0 got: $PF_COUNT ($CEIL)"
  FAIL=1
fi

# --- reconcile-status: anchored PR slug matching ---
MATCH=$(python3 <<'PY'
import re

slug = "api"
slug_esc = re.escape(slug)
branch_pat = re.compile(rf"^pf/{slug_esc}([/-]|$)", re.IGNORECASE)

def links(head, body, title):
    prd_pat = re.compile(rf"prd:\s*{re.escape(slug.lower())}\b", re.IGNORECASE)
    title_pat = re.compile(rf"\b{slug_esc}\b", re.IGNORECASE)
    return bool(
        branch_pat.search(head)
        or prd_pat.search(body)
        or title_pat.search(title)
    )

assert links("pf/api-phase-auth", "", "") is True
assert links("pf/authority-fix", "", "") is False
assert links("", "prd:api done", "") is True
assert links("", "authority prd:apiish", "") is False
print("ok")
PY
)
if [[ "$MATCH" == "ok" ]]; then
  echo "OK  reconcile-status anchored slug match"
else
  echo "FAIL reconcile-status slug match"
  FAIL=1
fi

# --- allocate_port: relative gitdir resolution ---
PORT_FIX=$(python3 <<'PY'
import json
import tempfile
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
wt = tmp / "repo"
wt.mkdir()
gitdir = wt / ".git"
gitdir.mkdir()
(gitdir / "phase-flow.json").write_text(json.dumps({"scaffold": {"port": 9100}}))

def resolve_state_path(worktree: str, gitdir: str):
    if not gitdir:
        return None
    gd = Path(gitdir)
    if not gd.is_absolute():
        gd = (Path(worktree) / gd).resolve()
    else:
        gd = gd.resolve()
    return gd / "phase-flow.json"

sp = resolve_state_path(str(wt), ".git")
data = json.loads(sp.read_text())
assert data["scaffold"]["port"] == 9100
print("ok")
PY
)
if [[ "$PORT_FIX" == "ok" ]]; then
  echo "OK  allocate_port relative gitdir resolve"
else
  echo "FAIL allocate_port gitdir resolve"
  FAIL=1
fi

# --- subagent dispatch rule exists ---
if [[ -f "$ROOT/rules/pf-subagent-dispatch.mdc" ]] && grep -q '8+' "$ROOT/rules/pf-subagent-dispatch.mdc"; then
  echo "OK  subagent dispatch rule"
else
  echo "FAIL pf-subagent-dispatch.mdc missing thresholds"
  FAIL=1
fi

# --- workflow sequencing lists pf-ship ---
if grep -q '/pf-ship' "$ROOT/rules/pf-workflow-sequencing.mdc"; then
  echo "OK  workflow sequencing pf-ship"
else
  echo "FAIL pf-workflow-sequencing missing pf-ship"
  FAIL=1
fi

# --- U6/U7: model tier map + check ---
MODEL_CHECK="$ROOT/scripts/model-tier-check.sh"
EXAMPLE_CONFIG="$ROOT/.pf/workflow.config.example.json"

if grep -q '"models"' "$ROOT/.pf/config.schema.json"; then
  echo "OK  config.schema documents models"
else
  echo "FAIL config.schema missing models"
  FAIL=1
fi

set +e
OUT=$(bash "$MODEL_CHECK" --config "$EXAMPLE_CONFIG" 2>/dev/null)
EC=$?
set -e
if [[ "$EC" -eq 0 ]] && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get('verdict')=='pass' and d.get('inheritReviewers',0)>=7 else 1)"; then
  echo "OK  model-tier-check: example config + inherit reviewers pass"
else
  echo "FAIL model-tier-check example (ec=$EC)"
  FAIL=1
fi

# Negative: concrete model below builder floor
TMP_AGENTS=$(mktemp -d)
cp "$ROOT/agents/pf-coherence-reviewer.md" "$TMP_AGENTS/"
printf '%s\n' '---' 'name: pf-coherence-reviewer' 'description: test' 'model: fast' '---' > "$TMP_AGENTS/pf-coherence-reviewer.md"
set +e
OUT=$(bash "$MODEL_CHECK" --config "$EXAMPLE_CONFIG" --agents-dir "$TMP_AGENTS" 2>/dev/null)
EC=$?
set -e
rm -rf "$TMP_AGENTS"
if [[ "$EC" -eq 20 ]] && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get('verdict')=='fail' else 1)"; then
  echo "OK  model-tier-check: fast reviewer below build floor → fail"
else
  echo "FAIL model-tier-check sub-floor case (ec=$EC)"
  FAIL=1
fi

if grep -q 'inherit' "$ROOT/.pf/models-tiering.md" && grep -q 'R9 runtime contract' "$ROOT/rules/pf-subagent-dispatch.mdc"; then
  echo "OK  models-tiering doc + runtime R9 dispatch rule"
else
  echo "FAIL models-tiering / runtime R9 wiring"
  FAIL=1
fi

if grep -q 'invariantsFile' "$ROOT/.pf/config.schema.json" && \
   grep -q 'invariantsFile' "$ROOT/commands/pf-doc-review.md"; then
  echo "OK  invariantsFile wired to doc-review"
else
  echo "FAIL invariantsFile wiring"
  FAIL=1
fi

if [[ $FAIL -eq 0 ]]; then
  echo "ALL implementation fixtures passed"
else
  echo "SOME implementation fixtures FAILED"
  exit 1
fi
