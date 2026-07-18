# Recallium memory provider — catalog conformance review

Review artifact for PRD 071 **R10**. Compares the seeded Recallium catalog row and adapter doc against the
registration checklist in `core/skills/memory/CAPABILITIES.md` — **not** a Recallium product feature audit.

**Catalog authority:** `.sw/memory-provider-catalog.json` (source) → `core/sw-reference/memory-provider-catalog.json`
(build-chain emit). **Adapter doc:** `core/providers/recallium.md`. **Rules script:** `providers/recallium-rules.py`.

**Review date:** 2026-07-18. **Catalog version:** 1. **Provider id:** `recallium`.

## Summary

| Area | Verdict |
| --- | --- |
| Catalog row completeness | **pass** |
| Registration checklist (R5) | **pass** |
| Capability flags (adapter ↔ catalog) | **pass** |
| Hook transport + REST SSRF policy | **pass** |
| Interchange (`jsonl` / `okf`) | **pass** (synthesized — degrade-open) |
| Source-of-truth class | **pass** (`memory-authoritative`) |
| Credentials clause | **pass** (`env-only`) |
| Typed relationship edges | **gap** (edge-degraded; documented) |
| Native export/import | **gap** (synthesized; documented) |

Overall: **conformant with documented gaps**. No catalog or registration blockers for the seeded row.

## Catalog row vs registration checklist

Validated mechanically by `scripts/memory_adapter_checklist.py` and
`scripts/unit_tests/memory/test_adapter_checklist.py`.

| Checklist item | Catalog / adapter evidence | Verdict |
| --- | --- | --- |
| **Dual-transport** | `hookTransport.agentSession: mcp`; `ruleFetch: out-of-band-script`; notes document MCP vs `recallium-rules.py` REST fetch | **pass** |
| **Category map** | Canonical → `memory_type` table in `recallium.md`; banned catch-alls called out | **pass** |
| **R41 redaction** | Write recipe + planning-store sections require `memory-redact.py` chokepoint | **pass** |
| **Degrade-open** | `export`/`import` capability flags `false`; commands synthesize interchange — never block unrelated surfaces | **pass** |
| **Interchange** | `interchange.jsonl: synthesized`, `interchange.okf: synthesized` | **pass** |
| **Credentials** | `credentials.location: env-only`; notes forbid catalog/config/memory secret storage | **pass** |
| **REST SSRF** | `restFetchPolicy` localhost-only; enforced via `scripts/sw_recallium_url.py` | **pass** |

## Capability flag parity

Adapter doc capability block matches the catalog row exactly:

| Flag | Catalog | Adapter doc | Verdict |
| --- | --- | --- | --- |
| `typedMemories` | true | true | **pass** |
| `filePathSearch` | true | true | **pass** |
| `categoryFilter` | true | true | **pass** |
| `recencyControl` | true | true | **pass** |
| `rulesAtStartup` | true | true | **pass** |
| `tasks` | true | true | **pass** |
| `export` | false | false | **pass** |
| `import` | false | false | **pass** |
| `softDelete` | true | true | **pass** |
| `semanticSearch` | true | true | **pass** |

## Interchange and source-of-truth

| Field | Catalog value | Operator impact | Verdict |
| --- | --- | --- | --- |
| `interchange.jsonl` | `synthesized` | `/sw-memory-export` / `/sw-memory-import` page `search` + `expand`; lossy vs native in-repo | **pass** (documented degrade-open) |
| `interchange.okf` | `synthesized` | Same synthesis path; redaction before bundle write | **pass** (documented degrade-open) |
| `sourceOfTruthClass` | `memory-authoritative` | `memory_sot.py` auto-classifies Recallium as memory-SoT; repo docs remain pointers only | **pass** |

Provider-switch flow (`scripts/memory_switch.py`) surfaces `lossy` migration when targeting in-repo — expected.

## Documented gaps (intentional degrade-open)

These are **not** registration failures. They are explicit capability degradations called out in the adapter
doc and `CAPABILITIES.md` **Relationship edges** section.

| Gap | Behavior | Mitigation |
| --- | --- | --- |
| **Typed edges** | Recallium `link_task_memories` is untyped; `traverse`/`expand` degrade to tag-search when native edges absent | Export/import sidecar stores typed `links[]`; `supersedes` reconciliation uses explicit traverse |
| **Native export/import** | MCP has no neutral JSONL/OKF ops | Plugin synthesizes via search+expand; capability flags `false` so commands degrade gracefully |
| **`playbook` category** | Maps to `working-notes` + tags, not a native Recallium playbook type | Aligns with in-repo playbook contract via tag sidecar; promotion gates unchanged |
| **Semantic search runtime** | Depends on local Ollama embeddings | Operational prerequisite; no catalog change required |

## Registration validator reachability

`scripts/memory_provider_register.py` accepts `recallium` when:

- Catalog row is present and schema-valid.
- `adapterDoc` resolves to `core/providers/recallium.md`.
- `rulesScript` resolves to `providers/recallium-rules.py`.

Hook trust remains gated by `capability_trust.py` — catalog membership alone does not authorize execution.

## References

- Catalog source: `.sw/memory-provider-catalog.json`
- Adapter: `core/providers/recallium.md`
- Checklist contract: `core/skills/memory/CAPABILITIES.md` (Adapter registration checklist)
- Switch flow: `scripts/memory_switch.py`
- SSRF policy: `scripts/sw_recallium_url.py`
