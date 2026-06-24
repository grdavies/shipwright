#!/usr/bin/env bash
# Fixture tests for conditional review-persona selection (plan 2026-06-23-004).
set -euo pipefail

bash -n "${BASH_SOURCE[0]}" || {
  echo "FAIL fixture runner bash syntax"
  exit 1
}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TRIAGE="$ROOT/skills/triage/SKILL.md"
DOC_REVIEW="$ROOT/skills/doc-review/SKILL.md"
PF_DOC_REVIEW="$ROOT/commands/pf-doc-review.md"
CODE_REVIEW_RULES="$ROOT/rules/code-review-automation.mdc"
FIXTURES="$ROOT/scripts/test/fixtures/persona-selection"
WORKFLOW_CONFIG="$ROOT/.cursor/workflow.config.json"
FAIL=0

# --- U1: doc-review signal-driven model (no tier scaling / Full=all seven) ---
if grep -qi 'Tier no longer selects personas' "$DOC_REVIEW" && \
   grep -qi 'always-on core' "$DOC_REVIEW" && \
   grep -q 'pf-coherence-reviewer' "$DOC_REVIEW" && \
   grep -q 'pf-feasibility-reviewer' "$DOC_REVIEW" && \
   grep -q 'pf-scope-guardian-reviewer' "$DOC_REVIEW" && \
   grep -q 'pf-product-reviewer' "$DOC_REVIEW" && \
   grep -q 'pf-adversarial-reviewer' "$DOC_REVIEW" && \
   grep -q 'pf-security-reviewer' "$DOC_REVIEW" && \
   grep -q 'pf-design-reviewer' "$DOC_REVIEW" && \
   grep -qi 'activation record' "$DOC_REVIEW" && \
   grep -q '\-\-personas' "$DOC_REVIEW" && \
   grep -q '\-\-all' "$DOC_REVIEW" && \
   ! grep -qE '^\| Full \|' "$DOC_REVIEW"; then
  echo "OK  doc-review: five-persona core + gated security/design + activation + override"
else
  echo "FAIL doc-review signal-driven model"
  FAIL=1
fi

if grep -qi 'polysemous' "$DOC_REVIEW" && \
   grep -qi 'wireframe' "$DOC_REVIEW" && \
   grep -qi 'Screens' "$DOC_REVIEW" && \
   grep -qi 'Figma' "$DOC_REVIEW"; then
  echo "OK  doc-review: design precision (unambiguous terms + structural signals)"
else
  echo "FAIL doc-review design precision"
  FAIL=1
fi

# --- U2: pf-doc-review command matches signal-driven model ---
if grep -qi 'signal-driven' "$PF_DOC_REVIEW" && \
   grep -qi 'activation record' "$PF_DOC_REVIEW" && \
   grep -qi 'five-persona always-on core' "$PF_DOC_REVIEW" && \
   grep -q '\-\-personas' "$PF_DOC_REVIEW" && \
   grep -q '\-\-all' "$PF_DOC_REVIEW" && \
   ! grep -qi 'seven personas in parallel' "$PF_DOC_REVIEW" && \
   ! grep -qi 'coherence \+ scope-guardian minimum' "$PF_DOC_REVIEW"; then
  echo "OK  pf-doc-review: core + signal-gated model (no tier persona counts)"
else
  echo "FAIL pf-doc-review command wording"
  FAIL=1
fi

# --- U4: native panel binding rule recorded ---
if grep -qi 'Native code-review panel' "$CODE_REVIEW_RULES" && \
   grep -qi 'always-on core' "$CODE_REVIEW_RULES" && \
   grep -qi 'signal-gated' "$CODE_REVIEW_RULES" && \
   grep -qi 'ce-code-review' "$CODE_REVIEW_RULES" && \
   grep -qi 'no change' "$CODE_REVIEW_RULES"; then
  echo "OK  code-review-automation: native panel binding standard"
else
  echo "FAIL code-review-automation native panel rule"
  FAIL=1
fi

# --- U3: triage tagged risk triggers ---
if grep -q '| Category |' "$TRIAGE" && \
   grep -q '| security |' "$TRIAGE" && \
   grep -q '| data-migration |' "$TRIAGE" && \
   grep -q '| billing-routing |' "$TRIAGE" && \
   grep -q '`PII`' "$TRIAGE" && \
   grep -q '`credentials`' "$TRIAGE" && \
   grep -q '`authn`' "$TRIAGE" && \
   grep -q '`authz`' "$TRIAGE"; then
  echo "OK  triage: tagged risk triggers with security extensions"
else
  echo "FAIL triage tagged risk triggers"
  FAIL=1
fi

# --- U5: fixture cases exist ---
REQUIRED_FIXTURES=(
  minimal-standard.md
  auth-signal.md
  pii-credentials.md
  migration-only.md
  billing-routing-only.md
  design-unambiguous.md
  design-polysemous-only.md
  design-structural.md
  override-personas.md
  override-all.md
  quick-tier.md
)
for f in "${REQUIRED_FIXTURES[@]}"; do
  if [[ -f "$FIXTURES/$f" ]]; then
    echo "OK  fixture exists: $f"
  else
    echo "FAIL missing fixture: $f"
    FAIL=1
  fi
done

# Fixture expected-outcome markers
if grep -q 'expected-personas: core-only' "$FIXTURES/minimal-standard.md" && \
   grep -q 'expected-personas: core + security' "$FIXTURES/auth-signal.md" && \
   grep -q 'expected-personas: core-only' "$FIXTURES/migration-only.md" && \
   grep -q 'expected-personas: core-only' "$FIXTURES/billing-routing-only.md" && \
   grep -q 'expected-personas: core-only' "$FIXTURES/design-polysemous-only.md" && \
   grep -q 'expected-personas: core + design' "$FIXTURES/design-structural.md" && \
   grep -q 'expected-personas: none' "$FIXTURES/quick-tier.md"; then
  echo "OK  fixture expected-outcome markers"
else
  echo "FAIL fixture expected-outcome markers"
  FAIL=1
fi

# --- U3/U5: security gate subset sync (triage security tags ↔ doc-review enumeration) ---
SECURITY_KEYWORDS=(
  auth authn authz authentication authorization login session oauth jwt
  payment payments billing PII credentials token encryption
  "public api" "public endpoint" "external api" webhook
)
for kw in "${SECURITY_KEYWORDS[@]}"; do
  if ! grep -qi "$kw" "$TRIAGE" || ! grep -qi "$kw" "$DOC_REVIEW"; then
    echo "FAIL security keyword drift: $kw"
    FAIL=1
    continue
  fi
  if [[ "$kw" != *" "* ]]; then
    if ! grep -qE "\| \`${kw}\` \| security \|" "$TRIAGE"; then
      echo "FAIL triage security tag missing: $kw"
      FAIL=1
    fi
  else
    if ! grep -qF "| \`$kw\` | security |" "$TRIAGE"; then
      echo "FAIL triage security tag missing: $kw"
      FAIL=1
    fi
  fi
done
if [[ $FAIL -eq 0 ]]; then
  echo "OK  security gate subset in sync with triage tags"
fi

# Non-security tags must exist in triage but not in doc-review security enumeration prose as gate triggers
NON_SECURITY_TAGS=(migration backfill stripe paddle subscription)
for kw in "${NON_SECURITY_TAGS[@]}"; do
  if ! grep -qi "$kw" "$TRIAGE"; then
    echo "FAIL triage missing non-security tag keyword: $kw"
    FAIL=1
  fi
done

if grep -q 'billing-routing' "$DOC_REVIEW" && \
   grep -q 'data-migration' "$DOC_REVIEW" && \
   grep -qi 'do \*\*not\*\* fire security' "$DOC_REVIEW"; then
  echo "OK  doc-review excludes non-security triage tags from security gate"
else
  echo "FAIL doc-review non-security tag exclusion"
  FAIL=1
fi

# Amendment path retained
if grep -qi 'amendment' "$DOC_REVIEW" && \
   grep -q 'coherence' "$DOC_REVIEW" && \
   grep -q 'scope-guardian' "$DOC_REVIEW" && \
   grep -qi 'frozen parent' "$DOC_REVIEW" && \
   grep -qi 'skip the full selection' "$DOC_REVIEW"; then
  echo "OK  amendment review behavior retained"
else
  echo "FAIL amendment review behavior"
  FAIL=1
fi

# --- verify.test registration ---
if grep -q 'run-persona-selection-fixtures.sh' "$WORKFLOW_CONFIG"; then
  echo "OK  verify.test registers persona-selection runner"
else
  echo "FAIL verify.test missing persona-selection runner"
  FAIL=1
fi

if [[ $FAIL -eq 0 ]]; then
  echo "ALL persona-selection fixtures passed"
else
  echo "SOME persona-selection fixtures FAILED"
  exit 1
fi
