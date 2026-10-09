---
name: ship
description: Phase ship loop gates for /sw-ship — dist freshness, build-chain parity, operator-local closeout hygiene. Use when executing or resuming the ship chain. Does not merge.
---

# ship

Procedure skill backing `/sw-ship` — mechanical gates, dist regeneration, and merge-ready halt semantics.
Load `skills/conductor/SKILL.md` for in-turn continuation, legitimate halts, and phase-mode contract; command
surface details live in `core/commands/sw-ship.md`.

**Model tier:** inherit — resolve delegated atomics via
`python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --command <child-slug>`.

## Dist freshness (PRD 274 — D3)

Committed `dist/` zipapps mirror packaged `scripts/` helpers. Drift fails emitter-freshness CI and must be
resolved before push.

**Detect (side-effect-free — no `dist/` mutation):**

```bash
python3 scripts/dist_freshness.py detect
# machine-readable: python3 scripts/dist_freshness.py json
```

On drift, errors **fail closed** with the canonical regen command: `python3 -m sw generate --all`.

**Ship path before `sw-commit`** — when drift is present and auto-fixable, regenerate and stage only outputs
from this invocation:

```bash
python3 scripts/dist_freshness_ship.py regen
```

Behavior:

- Captures preexisting operator edits under `dist/` before regen.
- Runs `python3 -m sw generate --all` when drift is detected.
- Stages only paths changed by this regen (not unrelated `dist/` edits).
- **Fail closed** with `overlapping-preexisting` when preexisting `dist/` edits overlap regenerated outputs —
  reconcile manually; do not blind-stage.
- **Fail closed** with `residual-drift` when regen does not clear drift — re-run detect and inspect stderr.

Local detect is advisory/pre-push; the ship path may auto-stage when safe (D3). When not safe, halt with the
canonical regen command — never push with stale zipapps.

## Build-chain verify (R25)

When the phase diff touches `core/sw-reference/build-chain-paths.json` prefixes, run before `sw-commit`:

```bash
python3 scripts/ship-build-chain-check.py
```

The native `build-chain` handler always executes the helper with `--root <consumer-root>`,
`--phase-slug <phase>` and `--out <phase-run-dir>/build-chain.status.json`. This mode reads
`parentBranch`, `currentBranch` and `phaseSlug` from the consumer's per-worktree
`shipwright.json` in its Git directory. The recorded parent must resolve to one exact branch
and one merge base with HEAD; there is no fallback to ambient `main` or HEAD. Canonical
parent refs (including symbolic aliases) cannot be the current phase ref. Distinct parent
branches at the same commit remain valid for a newly started phase.

Applicability includes committed changes from that merge base, staged changes, unstaged changes
and untracked non-ignored files. Renames retain both paths; index/worktree cancellation cannot
hide a touched path. The installed runtime's `core/sw-reference/build-chain-paths.json` is the
prefix authority, and consumer-mode environment overrides are ignored. Missing or invalid
manifest/state, wrong phase identity, ambiguous Git scope, conflicts or changed acquisition
fail closed. Only a fully acquired scope outside all prefixes yields `not-applicable`.

The JSON status records actual paths, base/head, manifest digest and applicability. Matching paths
run the consumer repository's `scripts/build-chain-sync.py --check`; a missing script or real
parity failure blocks. The evidence writer retains actual child argv, exit code and output digests
and references that status artifact. A no-argument standalone Shipwright invocation retains its
unconditional local parity check.

On failure, remediate with `python3 scripts/build-chain-sync.py` (not `copy-to-core --force`).

## Operator-local deliver closeout (PRD 274)

Closure manifests and PR maps write to `.sw/deliver-closeout/` only (gitignored operator-local state).
`core_content_sync` denylists and purges `deliver-closeout/` from the `core/sw-reference/` mirror — never
commit `core/sw-reference/deliver-closeout/` trees or treat them as authoritative.

## Guardrails

- Never merge or force-push.
- Dist auto-regen stages only when `dist_freshness_ship.py regen` returns `verdict: pass`.
- Build-chain and dist freshness gates complement CI emitter-freshness — they do not weaken it.
