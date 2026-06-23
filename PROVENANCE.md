# Provenance manifest (R40)

Tracks source and version of vendored/borrowed components. Refresh via `/pf-upstream` is deferred to a
follow-up plan; this file is seeded during foundation build and updated as units land.

| Component | Source repo | Derived-from commit / ref | Ported in unit | Notes |
|-----------|-------------|---------------------------|----------------|-------|
| Plugin manifest shape | [cursor-phase-flow](https://github.com/grdavies/cursor-phase-flow) | `64f6e4ea9df5e232736bd064da899e316ed4f1da` | U1 | `.cursor-plugin/plugin.json` structure |
| Config schema + example | [cursor-phase-flow](https://github.com/grdavies/cursor-phase-flow) | `64f6e4ea9df5e232736bd064da899e316ed4f1da` | U1 | Extended with `review.provider`, `reviewGraceMinutes` |
| Local install sync script | [cursor-phase-flow](https://github.com/grdavies/cursor-phase-flow) | `64f6e4ea9df5e232736bd064da899e316ed4f1da` | U1 | Dest renamed to `phase-flow-v2` |
| CI gate (`check-gate.sh`) | [cursor-phase-flow](https://github.com/grdavies/cursor-phase-flow) | `64f6e4ea9df5e232736bd064da899e316ed4f1da` | U2 | #322/#330 false-green fixes preserved |
| Checks-gate skill + rule | [cursor-phase-flow](https://github.com/grdavies/cursor-phase-flow) | `64f6e4ea9df5e232736bd064da899e316ed4f1da` | U2 | |
| Review seam + CodeRabbit adapter | [cursor-phase-flow](https://github.com/grdavies/cursor-phase-flow) | `64f6e4ea9df5e232736bd064da899e316ed4f1da` | U3 | Generalized from inline gate logic |
| Memory skill/spec/provider | [cursor-phase-flow](https://github.com/grdavies/cursor-phase-flow) | `64f6e4ea9df5e232736bd064da899e316ed4f1da` | U4 | `pf-` renames; edge-degraded Recallium |
| Memory safety hardening | — | — | U5 | New (R41–R43); patterns from v1 audit command |
| Stabilize loop | [cursor-phase-flow](https://github.com/grdavies/cursor-phase-flow) | `64f6e4ea9df5e232736bd064da899e316ed4f1da` | U6 | |
| RCA core shape | [cursor-phase-flow](https://github.com/grdavies/cursor-phase-flow) | `64f6e4ea9df5e232736bd064da899e316ed4f1da` | U6 | Factored from stabilize; debug entry stubbed |
| Session/stop hooks | [cursor-phase-flow](https://github.com/grdavies/cursor-phase-flow) | `64f6e4ea9df5e232736bd064da899e316ed4f1da` | U7 | Fail-closed moved to `beforeSubmitPrompt` per A1 |
| Persona panel review pattern | [compound-engineering-plugin](https://github.com/everyinc/compound-engineering-plugin) | cache `2648200ed2352b6e19a93dcfffc764efe70b6a1b` | doc U5 | `pf-doc-review` + seven `pf-*-reviewer` agents; findings schema + synthesis |
| Brainstorm dialogue pattern | [compound-engineering-plugin](https://github.com/everyinc/compound-engineering-plugin) | cache `2648200ed2352b6e19a93dcfffc764efe70b6a1b` | doc U3 | `pf-brainstorm`; one-question dialogue + synthesis checkpoint |
| PRD + tasks pipeline | [cursor-phase-flow](https://github.com/grdavies/cursor-phase-flow) | `64f6e4ea9df5e232736bd064da899e316ed4f1da` | doc U4/U9 | `pf-prd`, `pf-tasks`; Go gate preserved; freeze separated |
| Doc orchestrator pattern | [cursor-phase-flow](https://github.com/grdavies/cursor-phase-flow) | `64f6e4ea9df5e232736bd064da899e316ed4f1da` | doc U10 | `pf-doc` delegates-to-atomics like v1 `/ship` |
| Doc-freeze CI check | — | — | doc U6 | `check-frozen.sh` + `.github/workflows/check-frozen.yml`; local `pre-commit-frozen.sh` is bypassable early warning |

## Update policy

When porting or adapting upstream changes:

1. Record the new derived-from commit in this table.
2. Note behavioral deltas in the unit commit message.
3. Run the relevant golden-fixture / contract tests for the affected seam.
