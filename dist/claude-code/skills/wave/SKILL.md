---
name: sw-wave
description: Dependency-ordered build waves with dependent-branch stacking and integration branch lifecycle.
---

# Wave orchestration

Layer above `/sw-ship` for multi-item rounds. Reuses `scripts/worktree.sh` and `skills/parallelism/` wholesale.

## Wave plan representation

Path: `.cursor/sw-wave-plan.json` (machine-readable; see `.sw/layout.md`).

```json
{
  "items": [{"id": "A", "branch": "pf/A"}, ...],
  "edges": [{"from": "A", "to": "C"}],
  "waves": [["A", "B"], ["C"]],
  "contention": {"serialized": ["doc-numbering"], "notes": "..."}
}
```

- **waves:** ordered batches; no intra-wave dependencies.
- **contention:** shared-migration refusal + living INDEX/numbering counters force serialization.

## Stacking

Dependents provision with:

```bash
scripts/worktree.sh provision <name> --base <dependency-branch> --branch pf/<name>
```

Merge pre-flight from `skills/parallelism/` runs before stacking. No item touches `main` mid-wave.

## Integration branch

After green leaves:

1. Create `integration/<stamp>` from `main`.
2. Merge green leaf branches.
3. Run whole-suite check (`check-gate.sh` on integration PR head).
4. Human gate authorizes `promote` in dependency order.

## Promotion (pre-merge validated)

For each leaf in dependency order:

1. Build disposable candidate ref: `main` + already-promoted + this leaf.
2. Push candidate branch + open short-lived PR.
3. Run `check-gate.sh` on PR head — green only then fast-forward to `main`.
4. Red candidate halts promotion before `main` is touched.

## Attributability

| Integration red type | Action |
|---------------------|--------|
| Reproduces in one leaf | Route to that leaf's stabilize loop |
| Every leaf/pair green in isolation | Delta-debug minimal subset + human escalation |

## High-contention surfaces

Living `docs/prds/INDEX.md`, `docs/decisions/INDEX.md`, and doc-numbering counters are shared mutable state — serialize doc-creation across a wave or late-bind numbering at integration.
