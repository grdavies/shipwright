# Call-site map — capability selector migration (PRD 021 phase 6, TR9)

Enumerates every legacy selection site, its replacement selector invocation, and the migration family
parity fixture that gates cutover.

| Call site | Legacy path | Selector invocation | Family | Parity fixture |
| --- | --- | --- | --- | --- |
| `/sw-doc-review` persona panel | `skills/doc-review/SKILL.md` selection algorithm | `bash scripts/doc-review-select.sh --context-json '<signal_context>'` | `doc-review` | `migration-parity-doc-review` |
| `/sw-review` / `/sw-ship` native panel roster | `scripts/code-review-select.sh` embedded rules | `bash scripts/code-review-select.sh --diff-json '<change_digest>'` | `code-review` | `migration-parity-code-review` |
| `check-gate.sh` / `wave_preflight` provider configuredness | `review-local-resolve.sh`, `wave_preflight.scan_review_provider` | `capability_migration_parity.select_family providers` | `providers` | `migration-parity-providers` |
| Deliver / phase entry (`wave_preflight` index freshness) | `wave_preflight.run_capability_index_check` | `capability-select.sh` + freshness gate (phase 2) | `providers` | (freshness fixtures) |
| `sw-subagent-dispatch` inline vs delegate | `rules/sw-subagent-dispatch.mdc` execute inline ≤3 files + `background_phase` | `capability_migration_parity.select_family dispatch` | `dispatch` | `migration-parity-dispatch` |
| Durable run-log activation record | doc-review activation prose | `capability_run_log.build_activation_record` (phase 7) | `doc-review` | `run-log-capability-set-surfaced` |

## Dual-run shadow harness

Before removing a legacy branch, run:

```bash
bash scripts/migration-parity-shadow.sh --family <family> --context-json '<signal_context>'
```

The harness compares canonical legacy JSON vs selector-projected JSON on the golden corpus in
`scripts/test/run-migration-parity-fixtures.sh`. Exit `0` only when byte-identical.

## Cutover policy (TR9)

1. Dual-run green on family golden corpus.
2. Call site dispatches selector wrapper (`doc-review-select.sh`, migrated `code-review-select.sh`).
3. Legacy branch removed from the call site; legacy implementation retained only inside
   `capability_migration_legacy.py` for fixture shadow comparison.
