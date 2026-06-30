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
# Fixtures for PRD 011 orchestrator UX and doc polish (R5–R16).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/test/fixture-lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/fixture-lib.sh"

SW_DOC="$(content_path commands/sw-doc.md)"
SW_CLEANUP="$(content_path commands/sw-cleanup.md)"
LINK_CHECK="$ROOT/scripts/docs-link-check.sh"
DOC_AFTER="$ROOT/scripts/test/fixtures"
FAIL=0

ok()  { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

# --- cleanup-agent-confirm-flow (R8, R10) ---
if grep -q 'Agent-driven confirm' "$SW_CLEANUP" && \
   grep -q 'asks the user to confirm' "$SW_CLEANUP" && \
   grep -q 'python3 scripts/cleanup.py --confirm --yes' "$SW_CLEANUP" && \
   grep -q 'SW_CLEANUP_CONFIRM=1' "$SW_CLEANUP" && \
   grep -q 'Manual escape hatch' "$SW_CLEANUP"; then
  ok "cleanup-agent-confirm-flow: agent prompt → apply on ack + escape hatch"
else
  bad "cleanup-agent-confirm-flow: sw-cleanup.md missing agent-driven confirm contract"
fi

if grep -q 'Declined, silent, or ambiguous' "$SW_CLEANUP"; then
  ok "cleanup-agent-confirm-flow: declined/silent/ambiguous → no apply"
else
  bad "cleanup-agent-confirm-flow: missing no-apply on non-ack"
fi

# --- cleanup-protections-preserved (R9) ---
for term in \
  'current branch' \
  'default branch' \
  'unmerged' \
  'in-flight deliver' \
  'indeterminate' \
  'never `rm -rf`' \
  'wouldRemove'; do
  if grep -qi "$term" "$SW_CLEANUP"; then
    ok "cleanup-protections-preserved: documents '$term'"
  else
    bad "cleanup-protections-preserved: missing '$term' in sw-cleanup.md"
  fi
done

if grep -q 'git worktree remove' "$SW_CLEANUP" && grep -q 'never `rm -rf`' "$SW_CLEANUP"; then
  ok "cleanup-protections-preserved: worktree remove documented; rm -rf prohibited"
else
  bad "cleanup-protections-preserved: worktree teardown contract"
fi

# --- confirm-checkpoint-prominent (R5) ---
if grep -q '## Implementation checkpoint' "$SW_DOC" && \
   grep -q 'paused.*awaiting your acknowledgement\|paused\*\* awaiting' "$SW_DOC" && \
   grep -qE 'Reply with \*\*proceed\*\* or \*\*yes\*\*|proceed.*yes.*continue' "$SW_DOC"; then
  ok "confirm-checkpoint-prominent: dedicated heading + question + paused-state line"
else
  bad "confirm-checkpoint-prominent: sw-doc.md missing prominent checkpoint block"
fi

if grep -q 'not buried' "$SW_DOC" || grep -q 'not buried in closing prose' "$SW_DOC"; then
  ok "confirm-checkpoint-prominent: checkpoint not buried in closing prose"
else
  bad "confirm-checkpoint-prominent: missing anti-burial guidance"
fi

# --- confirm-reemit-on-unacked-return (R6) ---
if grep -q 'Re-emit rule' "$SW_DOC" && \
   grep -q 're-emit the Implementation checkpoint block' "$SW_DOC" && \
   grep -q 'unrelated message' "$SW_DOC"; then
  ok "confirm-reemit-on-unacked-return: un-acked return re-emits checkpoint"
else
  bad "confirm-reemit-on-unacked-return: missing re-emit rule in sw-doc.md"
fi

# --- confirm-ack-grammar-unchanged (R7) ---
if grep -qE '\*\*`proceed`\*\*|\*\*proceed\*\*' "$SW_DOC" && \
   grep -qE '\*\*`yes`\*\*|\*\*yes\*\*' "$SW_DOC" && \
   grep -q '`Go`' "$SW_DOC" && \
   grep -qi 'silence' "$SW_DOC" && \
   grep -qi 'ambiguous' "$SW_DOC"; then
  ok "confirm-ack-grammar-unchanged: proceed/yes only; Go/silence/ambiguous → stop"
else
  bad "confirm-ack-grammar-unchanged: ack grammar table incomplete"
fi

# --- doc-afterTasks deliver-run surface (R1–R4) — extend existing fixtures ---
for fx in \
  doc-afterTasks-stop-deliver \
  doc-afterTasks-confirm-deliver \
  doc-afterTasks-auto-deliver \
  doc-afterTasks-guides-deliver; do
  bash "$DOC_AFTER/${fx}.sh" || FAIL=1
done

# --- docs-link-check-pass (R11) ---
set +e
OUT_PASS=$(bash "$LINK_CHECK" --root "$ROOT" 2>/dev/null)
EC_PASS=$?
set -e
if [[ "$EC_PASS" -eq 0 ]] && echo "$OUT_PASS" | python3 -c "
import json,sys
d=json.load(sys.stdin)
sys.exit(0 if d.get('verdict')=='pass' else 1)
"; then
  ok "docs-link-check-pass: clean repo → verdict pass"
else
  bad "docs-link-check-pass: expected pass on repo root (ec=$EC_PASS)"
  echo "$OUT_PASS" | head -5
fi

# --- docs-link-check-broken (R11) ---
FIX=$(mktemp -d)
trap 'rm -rf "$FIX"' EXIT
mkdir -p "$FIX/docs/guides"
cat > "$FIX/README.md" <<'EOF'
# Fixture
See [broken](docs/guides/missing.md).
EOF
set +e
OUT_BROKEN=$(bash "$LINK_CHECK" --root "$FIX" 2>/dev/null)
EC_BROKEN=$?
set -e
if echo "$OUT_BROKEN" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('verdict')=='broken-links'
assert any('missing.md' in f.get('link','') or 'missing.md' in f.get('file','') for f in d.get('findings',[]))
"; then
  ok "docs-link-check-broken: missing file → broken-links with reason"
else
  bad "docs-link-check-broken: expected broken-links verdict"
  echo "$OUT_BROKEN"
fi

# --- docs-link-check-advisory-default (R12) ---
if [[ "$EC_BROKEN" -eq 0 ]]; then
  ok "docs-link-check-advisory-default: advisory mode exits 0 with findings"
else
  bad "docs-link-check-advisory-default: advisory should exit 0 (ec=$EC_BROKEN)"
fi

set +e
bash "$LINK_CHECK" --root "$FIX" --strict >/dev/null 2>&1
EC_STRICT=$?
set -e
if [[ "$EC_STRICT" -eq 20 ]]; then
  ok "docs-link-check-advisory-default: --strict exits 20 on broken links"
else
  bad "docs-link-check-advisory-default: --strict expected exit 20 got $EC_STRICT"
fi

# --- docs-link-check-offline (R13) ---
mkdir -p "$FIX/docs/guides"
cat > "$FIX/docs/guides/offline.md" <<'EOF'
# Offline
[external](https://example.com/docs)
[local](../README.md)
EOF
if grep -qE 'SKIP_SCHEMES|https?://' "$ROOT/scripts/docs_link_check.py"; then
  ok "docs-link-check-offline: checker skips http/https schemes in source"
else
  bad "docs-link-check-offline: missing scheme skip in docs_link_check.py"
fi

set +e
OUT_OFFLINE=$(bash "$LINK_CHECK" --root "$FIX" 2>/dev/null)
EC_OFFLINE=$?
set -e
if [[ "$EC_OFFLINE" -eq 0 ]] && echo "$OUT_OFFLINE" | python3 -c "
import json,sys
d=json.load(sys.stdin)
# external link must not appear in findings (skipped)
links=[f.get('link','') for f in d.get('findings',[])]
assert not any(l.startswith('http') for l in links)
"; then
  ok "docs-link-check-offline: external links skipped; no network findings"
else
  bad "docs-link-check-offline: external link should be skipped"
fi

# --- ux-polish-emitter-freshness (R14) ---
if [[ -d "$ROOT/dist/cursor" ]] && [[ -d "$ROOT/dist/claude-code" ]]; then
  set +e
  python3 -m sw generate --all >/dev/null 2>&1
  GEN_EC=$?
  set -e
  if [[ "$GEN_EC" -eq 0 ]] && git -C "$ROOT" diff --exit-code -- dist/cursor dist/claude-code >/dev/null 2>&1; then
    ok "ux-polish-emitter-freshness: dist/ matches generate(core/)"
  else
    bad "ux-polish-emitter-freshness: dist/ drift from generate(core/)"
    git -C "$ROOT" diff --stat -- dist/cursor dist/claude-code 2>/dev/null || true
  fi
else
  bad "ux-polish-emitter-freshness: dist/cursor or dist/claude-code missing"
fi

# --- ux-polish-guides-aligned (R16) ---
check_guide_aligned() {
  local label="$1" path="$2"
  if [[ ! -f "$path" ]]; then
    bad "ux-polish-guides-aligned: missing $label at $path"
    return
  fi
  local body
  body="$(cat "$path")"
  local pass=1
  if ! echo "$body" | grep -q '/sw-deliver run'; then
    bad "ux-polish-guides-aligned: $label missing /sw-deliver run"
    pass=0
  fi
  if ! echo "$body" | grep -qiE 'Implementation checkpoint|confirm checkpoint|prominent.*confirm|doc\.afterTasks.*confirm'; then
    bad "ux-polish-guides-aligned: $label missing prominent confirm checkpoint"
    pass=0
  fi
  if ! echo "$body" | grep -qiE 'agent-driven|agent asks|agent presents.*confirm|/sw-cleanup.*confirm'; then
    bad "ux-polish-guides-aligned: $label missing agent-driven /sw-cleanup confirm"
    pass=0
  fi
  if [[ "$pass" -eq 1 ]]; then
    ok "ux-polish-guides-aligned: $label documents deliver run, confirm checkpoint, cleanup confirm"
  fi
}

check_guide_aligned getting-started "$ROOT/docs/guides/getting-started.md"
check_guide_aligned configuration "$ROOT/docs/guides/configuration.md"
check_guide_aligned workflows "$ROOT/docs/guides/workflows.md"

# Optional documentation/ mirror when present
if [[ -f "$ROOT/documentation/getting-started.md" ]]; then
  check_guide_aligned documentation-getting-started "$ROOT/documentation/getting-started.md"
fi
if [[ -f "$ROOT/documentation/commands.md" ]]; then
  local_body="$(cat "$ROOT/documentation/commands.md")"
  if echo "$local_body" | grep -q '/sw-deliver run' && \
     echo "$local_body" | grep -qi 'Implementation checkpoint\|confirm checkpoint\|doc\.afterTasks'; then
    ok "ux-polish-guides-aligned: documentation/commands.md documents deliver + confirm"
  else
    bad "ux-polish-guides-aligned: documentation/commands.md missing UX polish topics"
  fi
  if echo "$local_body" | grep -qiE 'agent.*confirm|agent-driven|/sw-cleanup.*confirm'; then
    ok "ux-polish-guides-aligned: documentation/commands.md documents agent cleanup confirm"
  else
    bad "ux-polish-guides-aligned: documentation/commands.md missing agent cleanup confirm"
  fi
fi

# --- verify.test registration ---
WF="$ROOT/.cursor/workflow.config.json"
EXAMPLE="$ROOT/.sw/workflow.config.example.json"
MANIFEST="$ROOT/core/sw-reference/pr-test-plan.manifest.json"
if { grep -qE 'run[-_]pr[-_]test[-_]plan[-_]manifest|_runner\.py verify|pr-test-plan\.manifest\.json' "$WF"; } 2>/dev/null && \
   [[ -f "$MANIFEST" ]] && grep -qE 'run[-_]ux[-_]polish[-_]fixtures' "$MANIFEST"; then
  ok "verify.test registers ux-polish via pr-test-plan manifest in workflow.config.json"
elif grep -qE 'run[-_]ux[-_]polish[-_]fixtures' "$WF" 2>/dev/null; then
  ok "verify.test registers ux-polish runner in workflow.config.json"
else
  bad "verify.test missing ux-polish (direct or via pr-test-plan manifest) in .cursor/workflow.config.json"
fi

if grep -q 'verify-require-configuration.py' "$EXAMPLE" 2>/dev/null; then
  ok "verify.test uses neutral sentinel in workflow.config.example.json"
elif grep -qE 'run[-_]ux[-_]polish[-_]fixtures' "$EXAMPLE" 2>/dev/null; then
  ok "verify.test registers ux-polish runner in workflow.config.example.json"
else
  bad "verify.test missing neutral sentinel or ux-polish runner in workflow.config.example.json"
fi

if [[ "$FAIL" -ne 0 ]]; then
  echo "ux-polish fixtures: FAIL"
  exit 1
fi
echo "ux-polish fixtures: PASS"

"""

if __name__ == "__main__":
    raise SystemExit(main())
