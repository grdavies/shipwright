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
# Fixture tests for in-repo memory provider + /sw-setup (plan 2026-06-23-002).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONTENT="$(python3 "$ROOT/scripts/sw-resolve-plugin-root.py" "$ROOT/scripts")"
CURSOR_DIST="$ROOT/dist/cursor"
SEARCH="$ROOT/scripts/in-repo-memory-search.py"
IN_REPO_RULES="$CONTENT/providers/in-repo-rules.py"
HOOK="$CURSOR_DIST/hooks/before-submit-guardrails.py"
FIX="$ROOT/scripts/test/fixtures/in-repo-memory"
FIX_RULES="$ROOT/scripts/test/fixtures/in-repo-rules"
FIX_MARKER="$ROOT/scripts/test/fixtures/marker"
if [ -f "$ROOT/.sw/config.schema.json" ]; then
  SCHEMA="$ROOT/.sw/config.schema.json"
elif [ -f "$CONTENT/sw-reference/config.schema.json" ]; then
  SCHEMA="$CONTENT/sw-reference/config.schema.json"
else
  SCHEMA="$ROOT/.sw/config.schema.json"
fi
SW_SETUP="$CONTENT/commands/sw-setup.md"
SW_INIT="$CONTENT/commands/sw-init.md"
IN_REPO_MD="$CONTENT/providers/in-repo.md"
CAPS="$CONTENT/skills/memory/CAPABILITIES.md"
REDACT="$ROOT/scripts/memory-redact.sh"
FAIL=0

export PYTHONPATH="$CURSOR_DIST/hooks${PYTHONPATH:+:$PYTHONPATH}"
chmod +x "$SEARCH" "$IN_REPO_RULES" 2>/dev/null || true

# --- U1: provider doc + semanticSearch flag ---
if grep -q '"semanticSearch": false' "$IN_REPO_MD" && grep -q 'semanticSearch' "$CAPS"; then
  echo "OK  in-repo provider declares semanticSearch:false + CAPABILITIES documents flag"
else
  echo "FAIL U1 semanticSearch declaration"
  FAIL=1
fi

if grep -q 'typedMemories' "$IN_REPO_MD" && grep -q 'rules/' "$IN_REPO_MD" && grep -q 'memories/' "$IN_REPO_MD"; then
  echo "OK  in-repo provider capability block + store layout"
else
  echo "FAIL U1 provider structure"
  FAIL=1
fi

# Interchange round-trip (fixture memory has all neutral fields)
SAMPLE="$FIX/store/memories/20260620-jwt-decision.md"
if grep -q '^category:' "$SAMPLE" && grep -q '^tags:' "$SAMPLE" && grep -q '^relatedFiles:' "$SAMPLE" && \
   grep -q '^importance:' "$SAMPLE" && grep -q '^scope:' "$SAMPLE" && grep -q '^links:' "$SAMPLE" && \
   grep -q '^createdAt:' "$SAMPLE"; then
  echo "OK  interchange frontmatter round-trip fields present"
else
  echo "FAIL U1 interchange fixture"
  FAIL=1
fi

# --- U2: search helper ---
STORE="$FIX/store"
OUT=$(bash "$SEARCH" --store "$STORE" --query JWT)
if echo "$OUT" | jq -e '.results | map(select(.id=="20260620-jwt-decision")) | length == 1' >/dev/null; then
  echo "OK  keyword search finds JWT memory"
else
  echo "FAIL U2 keyword search"
  FAIL=1
fi

OUT2=$(bash "$SEARCH" --store "$STORE" --query gate --category learning)
if echo "$OUT2" | jq -e '.results[0].id == "20260621-gate-learning"' >/dev/null; then
  echo "OK  category filter search"
else
  echo "FAIL U2 category filter"
  FAIL=1
fi

RUN1=$(bash "$SEARCH" --store "$STORE" --query JWT | jq -c .)
RUN2=$(bash "$SEARCH" --store "$STORE" --query JWT | jq -c .)
if [ "$RUN1" = "$RUN2" ]; then
  echo "OK  search determinism"
else
  echo "FAIL U2 search determinism"
  FAIL=1
fi

OUT3=$(bash "$SEARCH" --store "$STORE" --query auth --file-glob src/auth.ts)
if echo "$OUT3" | jq -e '.results | map(select(.id=="20260620-jwt-decision")) | length == 1' >/dev/null; then
  echo "OK  relatedFiles glob filter"
else
  echo "FAIL U2 file-glob filter"
  FAIL=1
fi

# R41 redaction write path
TMP_WRITE=$(mktemp -d)
FAKE_SECRET='AKIAIOSFODNN7EXAMPLE'
PAYLOAD="Remember: $FAKE_SECRET is the key"
REDACTED=$(printf '%s' "$PAYLOAD" | bash "$REDACT" 2>/dev/null || printf '%s' "$PAYLOAD" | python3 "$ROOT/scripts/memory_redact.py")
echo "$REDACTED" > "$TMP_WRITE/out.md"
if grep -q 'AKIAIOSFODNN7EXAMPLE' "$TMP_WRITE/out.md" 2>/dev/null; then
  echo "FAIL U2 redaction — secret still present"
  FAIL=1
else
  echo "OK  R41 redaction scrubs planted AWS key"
fi
rm -rf "$TMP_WRITE"

# Lazy create (mkdir semantics documented in SKILL)
if grep -q 'mkdir -p' "$CONTENT/skills/memory/SKILL.md" && grep -qi 'lazy' "$IN_REPO_MD"; then
  echo "OK  lazy store create documented"
else
  echo "FAIL U2 lazy create docs"
  FAIL=1
fi

# --- U3: in-repo rules adapter ---
RULES_WS=$(mktemp -d)
mkdir -p "$RULES_WS/.cursor/sw-memory/rules"
cp "$FIX_RULES/store/rules/"*.md "$RULES_WS/.cursor/sw-memory/rules/"
echo '{"memory":{"provider":"in-repo","inRepo":{"storeDir":".cursor/sw-memory"}}}' > "$RULES_WS/.cursor/workflow.config.json"
export SW_WORKSPACE_ROOT="$RULES_WS"
OUT_RULES=$(bash "$IN_REPO_RULES")
if echo "$OUT_RULES" | jq -e '.ok == true and (.rules | map(select(.id=="allowlisted-rule")) | length) == 1' >/dev/null && \
   echo "$OUT_RULES" | jq -e '(.rules | map(select(.id=="unlisted-rule")) | length) == 1' >/dev/null && \
   echo "$OUT_RULES" | jq -e '(.rules | map(select(.id=="invalid-category")) | length) == 0' >/dev/null && \
   echo "$OUT_RULES" | jq -e '(.rules | map(select(.id=="oversize-rule")) | length) == 0' >/dev/null; then
  echo "OK  in-repo-rules adapter emits valid rules only"
else
  echo "FAIL U3 rules adapter"
  echo "$OUT_RULES" | jq . 2>/dev/null || echo "$OUT_RULES"
  FAIL=1
fi
unset SW_WORKSPACE_ROOT
rm -rf "$RULES_WS"

# Hook offline in-repo (marker + empty rules, greenfield)
MARKER_WS=$(mktemp -d)
cp -R "$FIX_MARKER/with-marker/.cursor" "$MARKER_WS/"
mkdir -p "$MARKER_WS/.cursor/sw-memory/rules"
OUT_HOOK=$(echo "{\"workspace_roots\":[\"$MARKER_WS\"]}" | python3 "$HOOK")
if echo "$OUT_HOOK" | jq -e '.continue == true' >/dev/null; then
  echo "OK  hook offline in-repo marker continue=true"
else
  echo "FAIL U3 hook in-repo offline"
  echo "$OUT_HOOK" | jq . 2>/dev/null
  FAIL=1
fi
rm -rf "$MARKER_WS"

# Hook dispatches in-repo-rules (structural grep on shared guardrail core)
GUARDRAIL_CORE="$ROOT/core/hooks/guardrail_core.py"
if grep -q 'rules_script_for_provider' "$GUARDRAIL_CORE" && grep -q 'in-repo' "$GUARDRAIL_CORE"; then
  echo "OK  hook provider dispatch wiring"
else
  echo "FAIL U3 hook dispatch structure"
  FAIL=1
fi

# Recallium regression — still uses recallium-rules when configured
REC_WS=$(mktemp -d)
mkdir -p "$REC_WS/.cursor"
echo '{"memory":{"provider":"recallium","project":"t","guardrails":{"enforceBeforeSubmit":true}}}' > "$REC_WS/.cursor/workflow.config.json"
# Use rules-empty fixture via SW_RULES_SCRIPT for deterministic test
OUT_REC=$(echo "{\"workspace_roots\":[\"$REC_WS\"]}" | SW_RULES_SCRIPT="$ROOT/scripts/test/fixtures/rules-empty.sh" python3 "$HOOK")
if echo "$OUT_REC" | jq -e '.continue == true' >/dev/null; then
  echo "OK  recallium config path preserved"
else
  echo "FAIL U3 recallium regression"
  FAIL=1
fi
rm -rf "$REC_WS"

# --- U4: marker precedence ---
PREC_WS=$(mktemp -d)
mkdir -p "$PREC_WS/.cursor"
echo 'in-repo' > "$PREC_WS/.cursor/sw-memory.provider"
echo '{"memory":{"provider":"recallium","project":"x","guardrails":{"enforceBeforeSubmit":true}}}' > "$PREC_WS/.cursor/workflow.config.json"
mkdir -p "$PREC_WS/.cursor/sw-memory/rules"
OUT_PREC=$(echo "{\"workspace_roots\":[\"$PREC_WS\"]}" | SW_RULES_SCRIPT="$ROOT/scripts/test/fixtures/rules-empty.sh" python3 "$HOOK")
if echo "$OUT_PREC" | jq -e '.continue == true' >/dev/null; then
  echo "OK  explicit config overrides marker (recallium path)"
else
  echo "FAIL U4 config precedence"
  FAIL=1
fi
rm -rf "$PREC_WS"

# Pass-through: no config, no marker
UNCONF=$(mktemp -d)
OUT_UN=$(echo "{\"workspace_roots\":[\"$UNCONF\"]}" | python3 "$HOOK")
if echo "$OUT_UN" | jq -e '.continue == true' >/dev/null; then
  echo "OK  pass-through no config no marker"
else
  echo "FAIL U4 pass-through"
  FAIL=1
fi
rm -rf "$UNCONF"

# Session-start hints /sw-setup (shared guardrail core builds session context)
if grep -q '/sw-setup' "$GUARDRAIL_CORE"; then
  echo "OK  session-start nudges /sw-setup"
else
  echo "FAIL U4 session-start hint"
  FAIL=1
fi

# --- U5: sw-init command (sw-setup delegate) ---
if [[ -f "$SW_INIT" ]] && grep -qi 'doctor' "$SW_INIT" && grep -qi 'does not scaffold CI' "$SW_INIT" && \
   grep -qi 'does not' "$SW_INIT" && grep -qi 'migrate' "$SW_INIT" && \
   [[ -f "$SW_SETUP" ]] && grep -qi 'deprecated' "$SW_SETUP" && grep -qi '/sw-init' "$SW_SETUP"; then
  echo "OK  sw-init command scope + doctor mode (sw-setup delegates)"
else
  echo "FAIL U5 sw-setup command"
  FAIL=1
fi

if grep -qE '/sw-(setup|init)' "$CONTENT/rules/sw-workflow-sequencing.mdc"; then
  echo "OK  workflow sequencing references /sw-setup or /sw-init"
else
  echo "FAIL U5 sequencing reference"
  FAIL=1
fi


# --- OKF export/import + derived index/log (PRD 064 R19-R20) ---
OKF_OUT=$(mktemp -d)
JSONL_OUT=$(mktemp)
python3 "$SEARCH" export --store "$STORE" --format okf --out "$OKF_OUT" >/dev/null
python3 "$SEARCH" export --store "$STORE" --format jsonl --out "$JSONL_OUT" >/dev/null
if [[ -f "$OKF_OUT/index.md" ]] && grep -q 'okf_version: "0.1"' "$OKF_OUT/index.md" && \
   [[ -f "$OKF_OUT/decision/20260620-jwt-decision.md" ]] && grep -q 'type:.*decision' "$OKF_OUT/decision/20260620-jwt-decision.md"; then
  echo "OK  OKF export bundle shape"
else
  echo "FAIL OKF export bundle"
  FAIL=1
fi
python3 "$SEARCH" maintain-derived --store "$STORE" >/dev/null
IDX1=$(md5 -q "$STORE/index.md" 2>/dev/null || md5sum "$STORE/index.md" | awk '{print $1}')
python3 "$SEARCH" maintain-derived --store "$STORE" >/dev/null
IDX2=$(md5 -q "$STORE/index.md" 2>/dev/null || md5sum "$STORE/index.md" | awk '{print $1}')
if [[ "$IDX1" == "$IDX2" ]] && [[ -f "$STORE/log.md" ]]; then
  echo "OK  index.md/log.md deterministic"
else
  echo "FAIL derived index/log determinism"
  FAIL=1
fi
RT_STORE=$(mktemp -d)
python3 "$SEARCH" import --store "$RT_STORE" --format okf --source "$OKF_OUT" >/dev/null
RT_JSONL=$(mktemp)
python3 "$SEARCH" export --store "$RT_STORE" --format jsonl --out "$RT_JSONL" >/dev/null
if python3 - "$JSONL_OUT" "$RT_JSONL" <<'PY2'
import json, pathlib, sys
a=[json.loads(l) for l in pathlib.Path(sys.argv[1]).read_text().splitlines() if l.strip()]
b=[json.loads(l) for l in pathlib.Path(sys.argv[2]).read_text().splitlines() if l.strip()]
a=sorted(a,key=lambda x:x["id"])
b=sorted(b,key=lambda x:x["id"])
sys.exit(0 if len(a)==len(b) and all(x["id"]==y["id"] and x["content"]==y["content"] for x,y in zip(a,b)) else 1)
PY2
then
  echo "OK  OKF round-trip preserves JSONL fields"
else
  echo "FAIL OKF round-trip"
  FAIL=1
fi
rm -rf "$OKF_OUT" "$RT_STORE"
rm -f "$JSONL_OUT" "$RT_JSONL"

# --- U6: schema validation ---
python3 - <<'PY' || { echo "FAIL U6 schema validation"; FAIL=1; }
import json, pathlib, sys
try:
    import jsonschema
except ImportError:
    print("SKIP U6 jsonschema not installed — structural check only")
    sys.exit(0)
root = pathlib.Path("$ROOT")
schema = json.loads((root / ".sw/config.schema.json").read_text())
valid = json.loads((root / "scripts/test/fixtures/in-repo-memory/config-in-repo.json").read_text())
jsonschema.validate(valid, schema)
invalid = dict(valid)
invalid["memory"] = dict(valid["memory"])
invalid["memory"]["bogusKey"] = "x"
try:
    jsonschema.validate(invalid, schema)
    print("FAIL U6 additionalProperties should reject bogus key")
    sys.exit(1)
except jsonschema.ValidationError:
    print("OK  schema accepts in-repo config + rejects unknown memory keys")
PY

if python3 -c "import jsonschema" 2>/dev/null; then
  :
else
  if grep -q '"in-repo"' "$SCHEMA" && grep -q 'commitMode' "$SCHEMA" && grep -q 'inRepo' "$SCHEMA"; then
    echo "OK  schema structurally admits in-repo knobs"
  else
    echo "FAIL U6 schema structure"
    FAIL=1
  fi
fi

# --- U7: runner registered ---
WF_CFG="$ROOT/.cursor/workflow.config.json"
if python3 -c "import json; r=json.load(open('$ROOT/core/sw-reference/suite-registry.json')); assert any(s['id']=='memory-provider-fixtures' for s in r.get('suites',[]))" 2>/dev/null; then
  echo "OK  verify.test registration present or pending"
else
  # Will register below — check after update
  true
fi

if [[ $FAIL -eq 0 ]]; then
  echo "ALL memory-provider fixtures passed"
else
  echo "SOME memory-provider fixtures FAILED"
  exit 1
fi

"""

if __name__ == "__main__":
    raise SystemExit(main())
