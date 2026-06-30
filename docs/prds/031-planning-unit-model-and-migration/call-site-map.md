# Call-site map — shared doc-format tokenizer (PRD 031 phase 1, R22)

Enumerates every runtime reader/writer of doc-format structural tokens, the tokenizer entrypoint
each will adopt in Phase A, and the fixture that gates cutover on map exhaustion.

| Consumer | Legacy structural parse site | Tokenizer adoption | Phase | Parity / gate fixtures |
| --- | --- | --- | --- | --- |
| `scripts/spec-union.py` | embedded `python3` — R/D-ID bullets, frontmatter directive lists | import `doc_format.tokenize` / `parse_directive_list` | Phase A (task 2.2) | `consumers-tokenizer-only`, `golden-before-after-equivalence` |
| `scripts/spec-rigor-check.py` | embedded `python3` — R/D-ID bullets, section headings, phase headings | import `doc_format.tokenize` | Phase A (task 2.2) | `consumers-tokenizer-only`, `golden-before-after-equivalence` |
| `scripts/traceability-check.py` | embedded `python3` — traceability table rows | import `doc_format.tokenize` | Phase A (task 2.2) | `consumers-tokenizer-only`, `four-consumer-id-agreement` |
| `scripts/wave_deliver.py` | `parse_phases`, `parse_phase_files`, `parse_phase_dependencies`, `parse_frontmatter` | import `doc_format.tokenize` | Phase A (task 2.2) | `consumers-tokenizer-only`, `phaseA-legacy-paths-no-relocation` |

## Writer surfaces

| Surface | Role |
| --- | --- |
| `scripts/doc_format.py` | Canonical tokenizer module — tokenize/emit API |
| `scripts/doc-format-normalize.py` | CLI wrapper (`tokenize`, `emit`, `lint-callsites`; `--check` / `--write` — landed Phase A task 2.1) |

## Mechanical lint

```bash
python3 scripts/doc_format.py lint-callsites \
  --map docs/prds/031-planning-unit-model-and-migration/call-site-map.md
```

Authoritative consumer enumeration: `doc_format.RUNTIME_CALL_SITES` (single source).

## Cutover policy

1. Phase 1 map + tokenizer engine land with `call-site-map-exhaustion` green.
2. **Phase A (task 2.5) — complete:** all four consumers parse exclusively via `doc_format`; exception manifest at `tokenizer-exception-manifest.json`; golden-corpus fixtures green on legacy `docs/prds` paths (no relocation).
3. Phase B relocation (R6) is gated separately — map exhaustion for tokenizer adoption is satisfied.
