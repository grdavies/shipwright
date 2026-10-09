# Frozen runtime-expansion task currency

A frozen task body describes the approved parent refs and stays immutable. The
execute planner can expand a parent into synthetic child refs. A child's ordinary
`done: true` ledger entry alone does not prove that this extra ref belongs to the
specification or that its work was integrated.

After native integration succeeds, capture the exact plan and latest journal
entry with the existing ledger writer, **before removing the phase run directory**:

```text
python3 scripts/wave_state.py ROOT ledger record --task CHILD --phase PHASE_SLUG --done true --execute-run-dir PHASE_RUN_DIR
```

Pass the same target/task-list routing arguments used for the delivery when
needed. `ROOT` must resolve the authoritative delivery state and its Git
repository. `PHASE_RUN_DIR` contains the native `execute-step-plan.json` and
`integrate-journal.json`; relative paths resolve from `ROOT`. Native integration
callers must explicitly perform this capture for synthetic refs after successful
integration (and again after a retry). The writer does not infer a run directory
from ambient environment or search sibling worktrees.

The writer rejects the request before persisting state unless all of these agree:

- The state's frozen source task list, run ID, phase ID and phase slug.
- One synthetic child ref whose direct parent exists in that phase's frozen body.
- The ref's integrated status and the latest matching journal's pass verdict,
  branch, merge commit and empty conflict list.
- Git ancestry of that commit against the phase's recorded merge commit, or its
  current phase branch while the phase is still unmerged, in `ROOT`'s repository.

The ledger retains the bounded native receipt fields, frozen-body hash, and
original plan/journal SHA-256 witnesses. Currency checking validates this proof
against current state and Git; it does not need the old run directory after
teardown. An unproven or unknown extra completed ref still blocks. The proof does
not mark its parent complete. Ordinary body refs and nonfrozen task currency keep
their existing behavior.

A subsequent ordinary record replaces the entry and drops its proof. Reopening or
withdrawing a child must record it incomplete; reintegration must recapture the
latest evidence. Never retain a prior pass receipt over a later failed retry.

## Existing deliveries

For a delivery whose genuine integration predates this capture, replay the same
native ledger-record command with the **latest retained native plan/journal
pair** for that phase. The pair may come from a preserved teardown backup. The
original merge commits must still be provably integrated into the actual phase
branch or recorded phase merge commit. Legacy plans missing the explicit synthetic marker remain blocking; the repaired
planner preserves that marker for future expansions. Inspect failures; do not synthesize receipt
fields, use an older passing journal, reset completion, delete ledger refs, or
change the frozen specification to make currency pass.

This command writes delivery progress; perform replay only in the authorized
recovery workflow after the repaired runtime has been reviewed and activated.
