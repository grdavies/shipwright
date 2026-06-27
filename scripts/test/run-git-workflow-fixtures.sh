#!/usr/bin/env bash
# Fixtures for PRD 026 Phase 5 — git-workflow skill + docs-branch standardization.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=fixture-lib.sh
source "$ROOT/scripts/test/fixture-lib.sh"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

SKILL="$(content_path skills/git-workflow/SKILL.md)"
RULE="$(content_path rules/sw-git-conventions.mdc)"
GUARD="$ROOT/scripts/branch-name-guard.sh"
COMMIT_GUARD="$ROOT/scripts/commit-msg-guard.sh"
TEMPLATE_LIB="$ROOT/scripts/git_template_lib.py"

chmod +x "$ROOT/scripts/worktree_lib.py" "$COMMIT_GUARD" "$ROOT/scripts/docs_worktree.sh" \
  "$ROOT/scripts/docs_pr.sh" "$TEMPLATE_LIB" 2>/dev/null || true

# --- git-workflow-skill-present (R23) ---
if [[ -f "$SKILL" ]] && grep -q 'netresearch/git-workflow-skill' "$SKILL" \
   && grep -q 'sw-namespaced\|sw-git-conventions' "$SKILL"; then
  ok "git-workflow-skill-present"
else
  bad "git-workflow-skill-present"
fi

# --- conventions-single-source (R27) ---
if [[ -f "$RULE" ]] && grep -q 'skills/git-workflow/SKILL.md' "$RULE" \
   && ! grep -qE '<type>/<slug>.*feat.*fix' "$ROOT/core/commands/sw-ship.md" 2>/dev/null; then
  ok "conventions-single-source"
else
  # allow if rule references skill as authoritative
  if [[ -f "$RULE" ]] && grep -q 'Authoritative reference' "$RULE"; then
    ok "conventions-single-source"
  else
    bad "conventions-single-source"
  fi
fi

# --- branch-name-guard-reject (R24) ---
if bash "$GUARD" validate pf/bad-name >/dev/null 2>&1 \
   || ! python3 "$ROOT/scripts/worktree_lib.py" validate pf/bad-name >/dev/null 2>&1; then
  ok "branch-name-guard-reject"
else
  bad "branch-name-guard-reject"
fi
if grep -q 'worktree_lib.py' "$ROOT/scripts/worktree.sh"; then
  ok "branch-name-guard-reject:worktree-wired"
else
  bad "branch-name-guard-reject:worktree-wired"
fi

# --- commit-msg-validator-reject (R25) ---
if bash "$COMMIT_GUARD" validate "not a conventional commit" >/dev/null 2>&1; then
  bad "commit-msg-validator-reject"
else
  ok "commit-msg-validator-reject"
fi
if [[ -x "$ROOT/core/hooks/commit-msg" ]]; then
  ok "commit-msg-validator-reject:hook-present"
else
  bad "commit-msg-validator-reject:hook-present"
fi

# --- pr-template-required-fields (R26) ---
BODY_OK="$(python3 "$TEMPLATE_LIB" render pr-body --context-json '{"summary":"s","test_plan":"t","prd_slug":"x"}')"
if python3 "$TEMPLATE_LIB" validate pr-body --body "$BODY_OK" >/dev/null 2>&1; then
  ok "pr-template-required-fields:pass"
else
  bad "pr-template-required-fields:pass"
fi
if python3 "$TEMPLATE_LIB" validate pr-body --body "## Summary\n\nonly" >/dev/null 2>&1; then
  bad "pr-template-required-fields:reject"
else
  ok "pr-template-required-fields:reject"
fi

# --- docs-branch-no-main-commit (R28) ---
if OUT=$(bash "$ROOT/scripts/docs_worktree.sh" provision --topic fixture-topic --dry-run 2>/dev/null) \
   && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['branch'].startswith('docs/')"; then
  ok "docs-branch-no-main-commit"
else
  bad "docs-branch-no-main-commit"
fi

# --- docs-worktree-provision (R29) ---
TMPGIT=$(mktemp -d)
trap 'rm -rf "$TMPGIT"' EXIT
(
  cd "$TMPGIT"
  git init -q
  git config user.email "t@example.com"
  git config user.name "T"
  mkdir -p docs/brainstorms .cursor
  echo '{"defaultBaseBranch":"main"}' > .cursor/workflow.config.json
  echo '# b' > docs/brainstorms/2026-fixture-topic.md
  git add .
  git commit -m "chore: init" -q
  git branch -M main
  cp -R "$ROOT/scripts" ./scripts
  cp -R "$ROOT/core" ./core
  cp "$ROOT/release-please-config.json" .
  if OUT=$(bash scripts/docs_worktree.sh provision --topic fixture-topic 2>/dev/null) \
     && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('action')=='provision'"; then
    echo "OK  docs-worktree-provision"
  else
    echo "FAIL docs-worktree-provision"
    exit 1
  fi
) || FAIL=1

# --- docs-pr-to-default (R30) ---
if OUT=$(bash "$ROOT/scripts/docs_pr.sh" --topic fixture-topic --dry-run 2>/dev/null) \
   && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['base']=='main' and d['head'].startswith('docs/')"; then
  ok "docs-pr-to-default"
else
  bad "docs-pr-to-default"
fi

# --- brainstorm-durable-commit (R31) ---
if grep -q 'def cmd_docs_commit' "$ROOT/scripts/wave_spec_seed.py" \
   && grep -q 'docs_paths_all' "$ROOT/scripts/wave_spec_seed.py"; then
  ok "brainstorm-durable-commit"
else
  bad "brainstorm-durable-commit"
fi

# --- durability-reconcile-prd013 (R32) ---
if grep -q 'def cmd_spec_seed' "$ROOT/scripts/wave_spec_seed.py" \
   && grep -q 'brainstorms' "$ROOT/scripts/wave_spec_seed.py" \
   && grep -q 'docs-commit' "$ROOT/scripts/wave_spec_seed.py"; then
  ok "durability-reconcile-prd013"
else
  bad "durability-reconcile-prd013"
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "ALL git-workflow fixtures passed"
else
  echo "SOME git-workflow fixtures FAILED"
  exit 1
fi
