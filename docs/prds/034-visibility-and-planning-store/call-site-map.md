# Call-site map — planning visibility emission points (PRD 034 phase 2, R14)

Enumerates every planning-body read/write path that must route through `planning_visibility.py`
(single authority, R19). CI lint: `bash scripts/visibility-callsite-lint.sh`.

| Emission point | Script / surface | Resolver wrapper | Phase | Parity / gate fixtures |
| --- | --- | --- | --- | --- |
| `index-active` | `scripts/planning_index_gen.py` | `planning_visibility.redact_index_row` | 2 (live) | `index-redaction-opaque-title` |
| `index-archive` | `scripts/planning_reconcile.py` | `planning_index_gen.index_row_dict` | 2 (live) | `index-redaction-opaque-title` |
| `legacy-gap-backlog` | `scripts/planning_legacy_projection.py` | `planning_index_gen.index_row_dict` | 2 (live) | `index-redaction-opaque-title` |
| `legacy-prd-index` | `scripts/planning_legacy_projection.py` | `planning_index_gen.index_row_dict` | 2 (live) | `index-redaction-opaque-title` |
| `spec-seed` | `scripts/wave_spec_seed.py` | `planning_visibility.resolve_unit_visibility` | 2 (live) | `spec-seed-visibility-route` |
| `pr-diff` | `scripts/planning_deliver_gate.py` | *(deferred phase 5)* | — | — |
| `dispatch-context` | `scripts/dispatch-check.sh` | *(deferred phase 5)* | — | — |
| `store-get` | `scripts/planning_store.py` | *(deferred phase 3)* | — | — |
| `superseded-manifest` | `scripts/planning_reconcile.py` | *(deferred — metadata only)* | — | — |
| `inflight-tuple` | `scripts/inflight_signal.py` | `planning_visibility.redact_inflight_tuple` | 1 (resolver) | `resolver-single-authority` |
| `reconciler-output` | `scripts/planning_reconcile.py` | *(partial — archive wired)* | 2 | — |
| `run-log` | `scripts/wave_bookkeeping.py` | *(deferred)* | — | — |
| `handoff-032` | `scripts/inflight_signal.py` | *(deferred)* | — | — |
| `pull-in-confirm` | `scripts/wave_deliver.py` | *(deferred phase 5)* | — | — |

## Writer surfaces

| Surface | Role |
| --- | --- |
| `scripts/planning_visibility.py` | Single authority resolver + emission-point registry |
| `scripts/visibility-resolve.sh` | Thin CLI wrapper |
| `scripts/visibility-callsite-lint.py` | Map exhaustion + wired-script bypass lint |

## Mechanical lint

```bash
bash scripts/visibility-callsite-lint.sh \
  docs/prds/034-visibility-and-planning-store/call-site-map.md
```

Authoritative emission-point enumeration: `planning_visibility.EMISSION_POINTS`.

## Cutover policy

1. Phase 2 map + wired consumers green in `verify.test` (`emission-callsite-map-bypass-fails`).
2. Deferred rows tracked here until their owning phase lands — map must list all R14 points.
3. Unknown/unresolved visibility treated as `private` (fail-closed, R24).
