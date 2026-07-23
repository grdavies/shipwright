---
name: gap-check
description: Compare phase plan (spec union + task checklist) against git diff with bounded closers. Use when /sw-ship needs in-scope gap detection before commit. Default-on; does not author new scope.
---
# gap-check

Catches planned vs actual before commit.


**Model tier:** mid — resolve via `python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --skill gap-check`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## Inputs

- **Plan:** task checklist for `phaseSlug` in `tasksDir` + spec union (`scripts/spec-union.py <prd>`).
- **Backlog:** open rows from `python3 scripts/feedback-backlog.py list --open-only` (`skills/feedback-closure/SKILL.md`) — map against diff when PR-linked.
- **Native panel advisory (R75):** when present, read `$runDir/sw-local-review-run-report.json` (resolved via
  `python3 scripts/sw_bootstrap.py sw-tmp.py -- resolve` or `shipwright-state` `runDir`) and consume `scope_fidelity_advisory` **advisory
  only** — defer / stub / omission hints from phase-1 `scope-fidelity`. This input MUST NOT alter gap-check's
  binding verdict; gap-check remains the sole requirements-completeness authority (R12/R50).
- **Actual:** diff against per-worktree `parentBranch`:

```bash
PARENT=$(python3 scripts/shipwright-state.py read | Python json -r .parentBranch)
git diff --stat "$PARENT"...HEAD
git diff "$PARENT"...HEAD
```

## Procedure

1. Load config + plan + diff + open backlog items.
2. Read-only subagent maps each checklist item → `done` | `partial` | `missing` + unplanned hunks.
3. Gap report table.
4. In-scope gaps → bounded closer subagents (one gap each); re-verify.
5. Ambiguous/out-of-scope → escalate (toward feedback workstream `005`); never absorb silently.
6. Re-map once; escalate residuals.

## Closer dispatch binding (R14)

Before each bounded closer Task spawn (one in-scope gap each):

```bash
PARENT_MODEL="<concrete platform model id of the dispatching agent session>"
AGENT="generalPurpose"   # or a scoped closer agent when declared
DISPATCH_ID="<unique-id-per-closer>"
PROMPT_PATH=".cursor/sw-gap-check-runs/${DISPATCH_ID}-prompt.md"

python3 scripts/wave.py dispatch preflight --dispatch-id "$DISPATCH_ID" --agent "$AGENT" \
  --command sw-gaps --skill gap-check

INTENSITY_JSON=$(python3 scripts/resolve-intensity.py --agent "$AGENT" --command sw-gaps --skill gap-check)
INTENSITY=$(echo "$INTENSITY_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['intensity'])")
INTENSITY_SOURCE=$(echo "$INTENSITY_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['source'])")
# After redacting gap context into TASK_BODY:
printf '%s' "$TASK_BODY" > "${PROMPT_PATH}.body"
python3 scripts/dispatch_prompt.py build \
  --intensity "$INTENSITY" \
  --intensity-source "$INTENSITY_SOURCE" \
  --body-file "${PROMPT_PATH}.body" \
  --context-json "${CONTEXT_BLOCKS_JSON:-[]}" \
  --out "$PROMPT_PATH"

python3 scripts/dispatch-check.py --agent "$AGENT" --command sw-gaps --skill gap-check \
  --parent-model "$PARENT_MODEL" --dispatch-id "$DISPATCH_ID" --prompt "$PROMPT_PATH"
# Task spawn MUST use tool_input.prompt = contents of $PROMPT_PATH
```

Halt on preflight or `dispatch-check` exit 20; do not spawn without a validated leading directive.


## Status discovery (PRD 059 R5–R6)

On the deliver merge path, `scripts/gap-check-gate.py` discovers
`.cursor/sw-deliver-runs/{phaseSlug}/gap-check.status.json` via the shared phase-status discovery chain
(canonical → worktree-local → glob) — worktree-only writes are visible without manual sync. Writes include a
`head` field (same contract as phase `status.json`). Among multiple candidates, **binding halt** verdicts
block merge regardless of HEAD-match tiebreak.

## Deliver binding (PRD 055 R13, R25)

On the **deliver merge path** (`merge-enqueue` / `merge_ready_in_flight_phases`), gap-check is **mechanical**
via `scripts/gap-check-gate.py`:

- Emits/consumes `.cursor/sw-deliver-runs/{phaseSlug}/gap-check.status.json` with binding `pass|halt`.
- `ship-phase-status.py` refuses `merge-ready-green` when the durable verdict is `halt`.
- **`--fast` is prohibited** for deliver merge decisions (`--deliver-merge --fast` fails closed with
  `deliver-gap-check-no-fast-skip`). Standalone `/sw-ship` may still use `--fast` per ship skill contract.


## Near-duplicate scan (PRD 064 R24/R25)

After loading plan + diff and before closers, run the stdlib semantic near-duplicate scan for any
**new or changed in-scope scope titles/summaries** surfaced by the gap report (never auto-suppress per KD5):

```bash
python3 scripts/gap_similarity.py corpus --out "$RUN_DIR/gap-similarity-corpus.json"
python3 scripts/gap_similarity.py scan   --candidate "$CANDIDATE_TITLE_SUMMARY"   --corpus "$RUN_DIR/gap-similarity-corpus.json"   --out "$RUN_DIR/gap-similarity-scan.json"   --handoff-out "$RUN_DIR/gap-similarity-handoff.md"
```

Two tiers (config `gapCheck.nearDuplicate.{highThreshold,softThreshold}`):

- **high-terminal** — similarity ≥ high threshold vs `resolved`/`superseded` units (likely already addressed).
- **soft-open** — similarity ≥ soft threshold vs any open/scheduled unit (possible duplicate gap).

When `verdict` is `flag-for-review`, surface `$RUN_DIR/gap-similarity-handoff.md` in the gap-check
handoff summary for **human confirm** — never block merge, never auto-suppress capture, and never skip
the binding gap-check verdict on similarity alone.


## Rule verifier sweep (PRD 064 R8, opt-in)

When `gapCheck.ruleVerifierSweep.enabled` is true, after the gap report and before closers, fan out one cheap
`sw-rule-verifier` Task per active guardrail rule (repeat-violation check):

```bash
python3 scripts/rule_verifier_sweep.py plan --rules "$RUN_DIR/guardrail-rules.json" > "$RUN_DIR/rule-sweep-plan.json"
python3 scripts/rule_verifier_sweep.py synthesize --results "$RUN_DIR/rule-sweep-results.json" --out "$RUN_DIR/rule-sweep.status.json"
```

Feed sweep `halt` verdicts into `/sw-gaps` remediation or `/sw-stabilize` when repeat violations are found.
Default **off** — standalone `/sw-gaps` may opt in per run.


## Modes

- **Default (`/sw-ship`):** after execute; `--fast` skips.
- **Standalone (`/sw-gaps`):** same; `--report-only` never mutates.

## Guardrails

- Mapping before closers.
- Closers bounded — no scope expansion.
- Spec union is the requirement source, not bare parent PRD.
