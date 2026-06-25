---
date: 2026-06-25
topic: model-tier-setup-defaults
prd: docs/prds/008-model-tier-setup-defaults/008-prd-model-tier-setup-defaults.md
frozen: true
frozen_at: 2026-06-25
---

# Task list — PRD 008 model tier setup defaults

## Relevant Files

| Area | Canonical paths |
|------|-----------------|
| Routing defaults | `core/sw-reference/model-routing.defaults.json` (new) |
| Resolver | `scripts/resolve-model-tier.sh` (new) |
| Platform detect | `scripts/detect-platform.sh` (new, optional helper) |
| Tier check | `scripts/model-tier-check.sh`, `scripts/model-routing-check.sh` (new sibling) |
| Schema | `.sw/config.schema.json`, `core/sw-reference/config.schema.json` |
| Example config | `.sw/workflow.config.example.json`, `core/sw-reference/workflow.config.example.json` |
| Setup | `core/commands/sw-setup.md` |
| Tiering doc | `.sw/models-tiering.md`, `core/sw-reference/models-tiering.md` |
| Subagent dispatch | `core/rules/sw-subagent-dispatch.mdc` |
| All commands | `core/commands/sw-*.md` (~36 files) |
| Reasoning skills | `core/skills/*/SKILL.md` (~25 files) |
| Config guide | `docs/guides/configuration.md`, `README.md` |
| Fixtures | `scripts/test/fixtures/model-tier-routing.sh` (new) |
| Dogfood config | `.cursor/workflow.config.json` |
| Emitter | `platforms/cursor/emitter.py`, `platforms/claude-code/emitter.py` |
| Dist | `dist/cursor/`, `dist/claude-code/` |

## Notes

- Effective spec union: parent PRD R1–R27 (`spec-union.sh`); R2b is an implementation sub-requirement of R2.
- Coordinate with PRD 006: `communication-routing.defaults.json` key parity (R27) before or with model routing land.
- Atomic rollout step 0: four-tier `CANONICAL_TIER_ORDER` before setup seeds four-tier catalogs.
- Cursor `mid` canonical slug: `gpt-5.5-medium` per Decision Log D4.
- Claude Code `mid` collapses to `build` — document in setup report (D3).

## Tasks

### 1. Schema & four-tier policy foundation (M)

- [x] 1.1 Fix `models.routing` schema enum (R16, R15)
  - **File:** `.sw/config.schema.json`, `core/sw-reference/config.schema.json`
  - **Expected:** `models.routing.commands` and `skills` values enum `cheap|build|mid|deep|inherit`; remove communication-intensity enum; `models` block remains optional
  - **R-IDs:** R16, R15

- [x] 1.2 Update four-tier order in tier check (R4)
  - **File:** `scripts/model-tier-check.sh`, `core/scripts/model-tier-check.sh` (if duplicated)
  - **Expected:** `CANONICAL_TIER_ORDER` = `cheap`, `build`, `mid`, `deep`; reviewer ≥ builder rank uses four-tier order
  - **R-IDs:** R4

- [x] 1.3 Refresh example config to Cursor four-tier catalog (R5)
  - **File:** `.sw/workflow.config.example.json`, `core/sw-reference/workflow.config.example.json`
  - **Expected:** `mid: gpt-5.5-medium`, `deep: claude-opus-4-8-thinking-high`; inline `models.routing` sample from defaults
  - **R-IDs:** R5

### 2. Routing defaults & resolver (L)

- [ ] 2.1 Author `model-routing.defaults.json` (R21, R17, R27)
  - **File:** `core/sw-reference/model-routing.defaults.json`
  - **Expected:** all 36 shipped `sw-*` commands + 25 reasoning skills mapped per brainstorm KD5/KD6; includes `sw-cleanup`, `sw-caveman`; keys match communication routing when present
  - **R-IDs:** R21, R17, R27

- [ ] 2.2 Implement `resolve-model-tier.sh` (R11, R18, R26)
  - **File:** `scripts/resolve-model-tier.sh`
  - **Expected:** `--tier`, `--command`, `--skill`, `--delegate` flags; JSON `{tier, modelId, source}`; `inherit` → `modelId: null` exit 0; missing atomic key exit 20
  - **R-IDs:** R11, R18, R26

- [ ] 2.3 Add `model-routing-check.sh` (R22)
  - **File:** `scripts/model-routing-check.sh` (or extend `model-tier-check.sh`)
  - **Expected:** validates defaults keys ⊆ tiers+inherit; full command/skill coverage; R27 key parity with communication defaults
  - **R-IDs:** R22, R27

### 3. Setup integration (M)

- [ ] 3.1 Add platform detection helper (R3)
  - **File:** `scripts/detect-platform.sh` (or documented procedure in `sw-setup.md`)
  - **Expected:** returns `cursor` or `claude-code` from env signals; ambiguous → prompt; fixture with mocked env
  - **R-IDs:** R3

- [ ] 3.2 Extend `/sw-setup` for model seeding (R1, R2, R2b, R14, R17, R25)
  - **File:** `core/commands/sw-setup.md`
  - **Expected:** scaffold writes `models` + routing from defaults; doctor adds missing block; realign tiers on confirm only; routing restore validates tier keys; report summarizes tier map
  - **R-IDs:** R1, R2, R14, R17, R25

- [ ] 3.3 Copy defaults via emitter (R21)
  - **File:** `platforms/cursor/emitter.py`, `platforms/claude-code/emitter.py`
  - **Expected:** `model-routing.defaults.json` copied to `dist/*/core/sw-reference/`; regenerate dist
  - **R-IDs:** R21

### 4. Command & skill surfaces (L)

- [ ] 4.1 Stamp Model tier lines on all commands (R19, R10, R24)
  - **File:** `core/commands/sw-*.md`
  - **Expected:** every file has `**Model tier:**` line; orchestrators document `inherit` + `--delegate`; doc-pipeline commands reference `deep` + resolver
  - **R-IDs:** R19, R10, R24

- [ ] 4.2 Document routing tier on reasoning skills (R20)
  - **File:** `core/skills/*/SKILL.md`
  - **Expected:** each reasoning skill documents tier and subagent dispatch tier when Task tool used
  - **R-IDs:** R20

- [ ] 4.3 Update subagent-dispatch rule (R9)
  - **File:** `core/rules/sw-subagent-dispatch.mdc`
  - **Expected:** references `models.tiers.mid`, `models.tiers.deep`, `models.routing`, KD7 panel tiers (procedural)
  - **R-IDs:** R9

### 5. Documentation & dogfood (S)

- [ ] 5.1 Update models-tiering docs (R6)
  - **File:** `.sw/models-tiering.md`, `core/sw-reference/models-tiering.md`
  - **Expected:** four tiers, both platform catalogs, routing resolution, inherit sentinel, Claude mid collapse note
  - **R-IDs:** R6

- [ ] 5.2 Update configuration guide and README (R7)
  - **File:** `docs/guides/configuration.md`, `README.md`
  - **Expected:** Models setup step; `models.tiers`, aliases, roles, routing documented; README mentions model defaults
  - **R-IDs:** R7

- [ ] 5.3 Dogfood Shipwright config (R13)
  - **File:** `.cursor/workflow.config.json`
  - **Expected:** Cursor four-tier `models` block + full `models.routing` from defaults
  - **R-IDs:** R13

### 6. Fixtures & verification (M)

- [ ] 6.1 Add model-tier routing fixtures (R12, R23)
  - **File:** `scripts/test/fixtures/model-tier-routing.sh`, `scripts/test/run-impl-fixtures.sh`
  - **Expected:** four-tier example passes tier-check; `sw-prd`→deep→Opus; `sw-triage`→cheap→fast; `sw-execute`→build→Composer; `sw-gaps`→mid; `sw-doc --delegate sw-prd`→deep; key coverage gate
  - **R-IDs:** R12, R23

- [ ] 6.2 Model tier line grep gate (R19)
  - **File:** `scripts/test/fixtures/model-tier-routing.sh` (or sibling)
  - **Expected:** every `core/commands/sw-*.md` contains `Model tier:`; tier matches defaults file
  - **R-IDs:** R19

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 2 |
| 4 | 2 |
| 5 | 1, 2 |
| 6 | 2, 3, 4, 5 |

## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R1 | 3.2 | model-tier-routing scaffold seed fixture |
| R2 | 3.2 | model-tier-routing doctor repair fixture |
| R3 | 3.1 | detect-platform env mock fixture |
| R4 | 1.2 | model-tier-check four-tier order fixture |
| R5 | 1.3 | example config four-tier validation |
| R6 | 5.1 | models-tiering four-tier doc grep |
| R7 | 5.2 | configuration guide Models section fixture |
| R8 | 3.2 | sw-setup model step grep |
| R9 | 4.3 | subagent-dispatch mid/deep routing refs |
| R10 | 4.1 | doc-pipeline command Model tier grep |
| R11 | 2.2 | resolve-model-tier --tier deep JSON |
| R12 | 6.1 | run-impl-fixtures four-tier pass |
| R13 | 5.3 | dogfood config models block present |
| R14 | 3.2 | sw-setup report tier map prose |
| R15 | 1.1 | schema optional models block |
| R16 | 1.1 | schema routing inherit sentinel |
| R17 | 2.1, 3.2 | defaults completeness + setup seed |
| R18 | 2.2 | resolver command/skill/delegate paths |
| R19 | 4.1, 6.2 | command Model tier grep gate |
| R20 | 4.2 | skill routing tier grep |
| R21 | 2.1, 3.3 | defaults file + emitter copy fixture |
| R22 | 2.3 | model-routing-check coverage |
| R23 | 6.1 | representative resolution paths |
| R24 | 4.1 | orchestrator inherit Model tier lines |
| R25 | 3.2 | doctor routing restore procedure |
| R26 | 2.2 | sw-doc delegate sw-prd deep fixture |
| R27 | 2.1, 2.3 | communication key parity fixture |
