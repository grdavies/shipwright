---
date: 2026-06-27
topic: planning-feedback-lifecycle
prd: docs/prds/031-planning-unit-model-and-migration/031-prd-planning-unit-model-and-migration.md
frozen: true
frozen_at: 2026-06-27
---

# Tasks — PRD 031 Planning-Unit Model, Migration & Doc-Format Tokenizer (Foundation)

Generated from the frozen PRD spec union **R1–R33** (no amendments). Eight dependency-ordered phases mirror
the PRD's atomic-train rollout. The **031 substrate** and **tokenizer Phase A** land and pass fixtures FIRST:
the shared doc-format tokenizer engine (Phase 1) and its Phase-A adoption on legacy `docs/prds` paths
(Phase 2) deliver the GAP-045 parser-parity relief with no relocation; the planning-unit schema + validator +
stub enum (Phase 3), the config-driven path-resolution helper (Phase 4), and the deterministic dual-region
INDEX generator + region-integrity hook (Phase 5) complete the substrate. Only then do the big-bang migration
tool + held lock + redirect map (Phase 6), the atomic cutover — Phase B relocation, cancelled-PRD supersession
edges, the interim privacy guard, the legacy GAP-BACKLOG/INDEX projections, and the kill-criteria/relief
acceptance check (Phase 7) — and the documentation-currency + dist propagation + no-regression + memory
guardrails (Phase 8) land. Phases 1 and 3 are parallel-eligible; all Phase Dependencies are intra-PRD only.
Every phase ships behind passing fixtures registered in `core/sw-reference/pr-test-plan.manifest.json`.

## Tasks

### 1. Shared doc-format tokenizer engine — L

- [ ] 1.1 Doc-format tokenizer module + grammar (R11)
  - **File:** `scripts/doc_format.py`
  - **Expected:** one module defines the canonical structure for unit frontmatter and body — R/D-ID bullets,
    section headings, traceability cells, phase headings, and directive lists including block-list
    `absorbs`/`supersedes`/`retracts`; exposes a single tokenize/emit API. Fixture: `doc-format-grammar-tokenizes`.
  - **R-IDs:** R11
- [ ] 1.2 Normalize wrapper + enumerated call-site map (R22)
  - **File:** `scripts/doc-format-normalize.sh`, `docs/prds/031-planning-unit-model-and-migration/call-site-map.md`
  - **Expected:** `doc-format-normalize.sh` wraps `doc_format.py`; an explicit call-site map (per the PRD
    021/022 pattern) enumerates every runtime reader/writer (`spec-union`, `spec-rigor-check`,
    `traceability-check`, `wave_deliver` incl. phase/`**File:**` parsing); cutover is gated on map exhaustion.
    Fixture: `call-site-map-exhaustion`.
  - **R-IDs:** R22
- [ ] 1.3 Deterministic + offline guarantee (R31)
  - **File:** `scripts/doc_format.py`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** the tokenizer performs no network I/O and is deterministic — identical input yields identical
    output so CI gates stay reproducible. Fixture: `tokenizer-deterministic-offline`.
  - **R-IDs:** R31

### 2. Tokenizer Phase A adoption on legacy `docs/prds` paths — L

- [ ] 2.1 `--check` / `--write` modes + pre-freeze structural check (R13)
  - **File:** `scripts/doc_format.py`, `scripts/doc-format-normalize.sh`
  - **Expected:** `--check` fails closed with `file:line` expected/found diagnostics (never a silent drop);
    `--write` performs structural canonicalization only (shape, never content) and is idempotent; a pre-freeze
    structural check runs before union and traceability; authoring commands pipe output through `--write`
    before persisting so non-canonical drafts cannot reach freeze. Fixtures: `check-fail-closed-diagnostics`,
    `write-idempotent-shape-only`.
  - **R-IDs:** R13
- [ ] 2.2 Four-consumer adoption + machine-checked exception manifest (R12)
  - **File:** `scripts/spec-union.sh`, `scripts/spec-rigor-check.sh`, `scripts/traceability-check.sh`, `scripts/wave_deliver.py`
  - **Expected:** all four parse exclusively through the shared tokenizer with no independent structural regex
    retained; per-consumer baseline snapshots captured *before* adoption; divergence classes recorded in a
    machine-checked exception manifest keyed per file + per consumer + per divergence-class; the gate fails
    closed on any unlisted divergence; the manifest is finite/capped and requires doc-review sign-off;
    exceptions may not cover post-migration edits. Fixtures: `consumers-tokenizer-only`,
    `unlisted-divergence-fails-closed`.
  - **R-IDs:** R12
- [ ] 2.3 Authoring slot-fill templates + directive fail-closed (R14)
  - **File:** `scripts/doc_format.py`, `core/commands/sw-prd.md`
  - **Expected:** authoring commands emit machine-readable slot-filling templates matching the canonical shape;
    a non-empty directive key (`absorbs`/`supersedes`/`retracts`) that yields zero parsed ids fails closed.
    Fixtures: `template-slot-fill`, `directive-zero-ids-fails-closed`.
  - **R-IDs:** R14
- [ ] 2.4 Golden-corpus regression (R15)
  - **File:** `core/sw-reference/pr-test-plan.manifest.json`, `scripts/doc_format.py`
  - **Expected:** for the migrated frozen set plus the GAP-045 adversarial structural variants — (a) per-consumer
    parse equivalence before vs after tokenizer adoption; (b) four-consumer agreement on extracted id sets
    *after* adoption; (c) a post-`--write` round-trip asserting no consumer's extracted requirement set changes;
    any unit not in the R12 exception manifest that diverges fails the gate. Fixtures:
    `golden-before-after-equivalence`, `four-consumer-id-agreement`, `write-roundtrip-stable`.
  - **R-IDs:** R15
- [ ] 2.5 Phase A landing on `docs/prds` with no relocation (R16)
  - **File:** `docs/prds/031-planning-unit-model-and-migration/call-site-map.md`, `scripts/doc_format.py`
  - **Expected:** full tokenizer adoption + golden-corpus regression ship on the current `docs/prds` paths with
    no relocation, delivering GAP-045 parser-parity relief independently; Phase A acceptance does not depend on
    the planning-unit schema or `docs/planning/`. Fixture: `phaseA-legacy-paths-no-relocation`.
  - **R-IDs:** R16

### 3. Planning-unit schema + validator + stub enum — L

- [ ] 3.1 Canonical `planning-unit.schema.json` (R1)
  - **File:** `core/sw-reference/planning-unit.schema.json`
  - **Expected:** schema defines fields `id`, `type`, `status`, `title`, `visibility`, `depends`, `blocks`,
    `supersedes`, `extends`, `absorbs`, `priority`, `tags`, with `type` one of `brainstorm`/`gap`/`prd`/
    `decision`/`amendment`; committed and consumed by the validator. Fixture: `schema-fields-and-type-enum`.
  - **R-IDs:** R1
- [ ] 3.2 Folder-per-unit + stable-id convention (R2)
  - **File:** `core/sw-reference/planning-unit.schema.json`, `core/sw-reference/layout.md`
  - **Expected:** every unit is a folder containing a canonical-frontmatter body file plus optional ancillary
    tracked files (e.g. a PRD unit's frozen task lists and `amendments/` tree); unit ids are stable, monotonic,
    never reused; all cross-references use the unit id (never a table row or positional reference). Fixture:
    `unit-folder-and-id-stability`.
  - **R-IDs:** R2
- [ ] 3.3 Gaps as first-class units in the unified INDEX (R3)
  - **File:** `core/sw-reference/planning-unit.schema.json`, `core/sw-reference/layout.md`
  - **Expected:** gaps are first-class units (folder + frontmatter) replacing GAP-BACKLOG table rows and render
    as rows in the single generated unified INDEX (R5), not a separate gap-only index. Fixture:
    `gap-unit-in-unified-index`.
  - **R-IDs:** R3
- [ ] 3.4 Type-conditioned status + stub enum module (R4)
  - **File:** `scripts/planning_status_enum.py`, `core/sw-reference/planning-unit.schema.json`
  - **Expected:** status validation is type-conditioned and single-sourced — gap units use the gap enum
    (`open`/`planned`/`partially resolved`/`resolved`); all other types use the lifecycle enum
    (`proposed`/`planned`/`in-progress`/`complete`/`superseded`/`cancelled`/`deferred`/`blocked`) shipped as a
    minimal stub module (values only, no transition logic) imported by the validator; the schema enforces the
    correct enum per `type`, rejects cross-enum tokens, and documents the `planned` homonym as distinct per type.
    Fixtures: `status-type-conditioned`, `cross-enum-token-rejected`.
  - **R-IDs:** R4
- [ ] 3.5 Validator entrypoint fails closed (R19)
  - **File:** `scripts/planning-unit-validate.sh`
  - **Expected:** the validator fails closed on unknown keys, cross-enum/unknown status tokens (per the R4 stub
    enum), and — at migration/bootstrap time — on a `visibility: private` unit whose body path is git-tracked;
    ongoing visibility validation is deferred to PRD 034. Fixtures: `validate-unknown-key`,
    `validate-tracked-private-rejected`.
  - **R-IDs:** R19

### 4. Config-driven path-resolution helper — M

- [ ] 4.1 `planning_paths` helper + realpath containment (R23)
  - **File:** `scripts/planning_paths.py`, `scripts/planning_paths.sh`
  - **Expected:** the helper plus the `planningDir` config key route all planning-path reads/writes; resolves
    with canonical realpath, requires the resolved path to stay under the worktree root, and rejects `..`
    traversal and symlinks that escape the worktree (contained absolute paths allowed); a fixture proves no
    path-dependent component references a hardcoded `docs/prds` literal. Fixtures:
    `realpath-containment-reject-escape`, `no-hardcoded-prds-literal`.
  - **R-IDs:** R23
- [ ] 4.2 Reroute path-dependent machinery through config dirs (R7)
  - **File:** `scripts/wave_spec_seed.py`, `scripts/wave_deliver.py`, `scripts/wave_living_docs.py`, `core/sw-reference/config.schema.json`
  - **Expected:** spec-seed, deliver path resolution, living-docs path resolution, `.gitignore`, and
    freeze/immutability checks resolve paths through config dirs (`planningDir` plus existing
    `prdsDir`/`tasksDir`/`decisionsDir`); no component hardcodes `docs/prds`; this reroutes paths only —
    reconcile *logic* and derived-status population remain PRD 033. Fixture: `paths-resolve-through-config`.
  - **R-IDs:** R7

### 5. Deterministic dual-region INDEX generator + region-integrity hook — L

- [ ] 5.1 Canonical `docs/planning/` home + single unified INDEX (R5)
  - **File:** `core/sw-reference/layout.md`, `scripts/planning_index_gen.py`
  - **Expected:** the canonical planning-unit home is a typed-unit tree under `docs/planning/` with exactly one
    generated unified INDEX produced from unit frontmatter. Fixture: `single-unified-index-from-frontmatter`.
  - **R-IDs:** R5
- [ ] 5.2 Deterministic generator + dual-region read-merge-write + status precedence (R9)
  - **File:** `scripts/planning_index_gen.py`
  - **Expected:** the INDEX is produced deterministically from frontmatter (id, type, title, status, visibility,
    edges) and never hand-maintained; it carries two disjoint writer-owned regions — `derived` (reconciler-owned,
    PRD 033) and `inFlight` (deliver-owned, PRD 032) — both empty schema slots at cutover; the generator and
    every INDEX writer use read-merge-write, preserving the non-owned region byte-for-byte (full-file regen that
    drops a sibling region is prohibited); status precedence (lifecycle consumers read `derived.status` when
    populated else structural `status`; gaps use structural only) is stated in the INDEX schema doc. Fixtures:
    `region-preserve-byte-for-byte`, `status-precedence-resolves`.
  - **R-IDs:** R9
- [ ] 5.3 Generator wired to single-writer lock + region-integrity hook (R24)
  - **File:** `scripts/planning_index_gen.py`, `scripts/wave_living_docs.py`, `core/hooks/pre-commit`, `scripts/index-region-guard.sh`
  - **Expected:** the generator is wired into the living-doc single-writer lock and implements the R9
    read-merge-write contract; a region-integrity hook (pre-commit + CI) rejects commits that modify the
    `derived` region outside the reconciler or the `inFlight` region outside the deliver writer, and rejects an
    empty `inFlight` tuple when live deliver run-state exists. Fixtures: `region-hook-rejects-cross-writer`,
    `empty-inflight-with-runstate-fails`.
  - **R-IDs:** R24

### 6. Migration tool + held lock + redirect map + verification fixture — L

- [ ] 6.1 Migration tool modes + filesystem-atomic staging (R20)
  - **File:** `scripts/planning_migrate.py`
  - **Expected:** exposes `--dry-run`/`--write`/`--verify`/`--rollback`; runs relocation as a single atomic
    commit with filesystem-atomic staging (relocations staged under a temp prefix; reverse map + `GAP-id → unit-id`
    map emitted only after a successful commit; idempotent re-run); `--rollback` performs a dirty-tree/post-edit
    preflight (refuse on post-migration edits or newer-than-commit units unless `--force` with a logged reason),
    restores the pre-migration tree from the reverse map, and restores config keys in inverse order (flip
    `planningDir` back before/with the tree restore); `--verify` is a mandatory gate before the config flip.
    Fixtures: `migrate-atomic-staging`, `rollback-refuses-dirty-restores-config-inverse`.
  - **R-IDs:** R20
- [ ] 6.2 One-time idempotent relocation of all artifacts (R6)
  - **File:** `scripts/planning_migrate.py`
  - **Expected:** a one-time idempotent migration relocates all existing artifacts into the unified model — PRD
    folders including their nested frozen task lists and `amendments/` trees, gap rows, brainstorms, the decision
    index, and the GAP feedback-checklist content; frozen unit content is preserved verbatim (relocation plus
    frontmatter backfill only, no body edits). Fixture: `migrate-relocates-all-verbatim`.
  - **R-IDs:** R6
- [ ] 6.3 Migration one-to-one verification fixture (R8)
  - **File:** `core/sw-reference/pr-test-plan.manifest.json`, `scripts/planning_migrate.py`
  - **Expected:** proves every pre-migration artifact maps one-to-one to a post-migration unit with byte-preserved
    body content and reconstructed edges; staged into explicit snapshots (PRD folders with task lists + amendment
    trees, gap units, brainstorms, the decision index, cancelled-PRD edges); validates an explicit
    `GAP-id → unit-id` map and feedback-checklist item preservation as separate assertions; `--verify` fails
    closed on drift. Fixtures: `migration-one-to-one`, `gap-id-map-assertion`, `feedback-checklist-preserved`.
  - **R-IDs:** R8
- [ ] 6.4 Held migration lock + cross-worktree scan + path-redirect map (R21)
  - **File:** `scripts/planning_migrate.py`, `scripts/planning_path_redirect.py`, `scripts/worktree_lib.py`
  - **Expected:** a migration lock/sentinel is acquired atomically with the run-state scan and held through
    `--verify` (re-checked immediately before commit), closing the TOCTOU window; the run-state scan covers all
    linked git worktrees and `.sw-worktrees/**` (not a root-only glob); while held it refuses `/sw-deliver`
    run-start, living-doc reconcile, and `/sw-feedback` gap-append; a legacy→migrated path-redirect map is
    consumed by the enumerated consumer list (`wave_deliver_loop`, `wave_deliver` preflight/plan,
    `wave_spec_seed`, freeze-immutability checks, phase `**File:**` touch detection, living-docs); the cutover
    checklist enumerates open feature branches/worktrees carrying `docs/prds` task lists and resolves or halts.
    Fixtures: `migration-lock-toctou`, `cross-worktree-runstate-detect`, `redirect-map-resume`.
  - **R-IDs:** R21
- [ ] 6.5 Migration scope discipline + operational map artifacts (R29, R32)
  - **File:** `scripts/planning_migrate.py`, `.gitignore`
  - **Expected:** the migration touches documentation artifacts and the path-resolution/`.gitignore` config keys
    only — never code, secrets, or other configuration; the reverse map and `GAP-id → unit-id` map are
    operational artifacts (not planning units) stored gitignored under `.cursor/`, never containing body content,
    with old paths redacted for private-source units. Fixtures: `migration-scope-docs-config-only`,
    `opmaps-gitignored-redacted`.
  - **R-IDs:** R29, R32

### 7. Atomic cutover — Phase B relocation, supersession, privacy, projections, kill-criteria — L

- [ ] 7.1 Cancelled-PRD supersession edges (reversible) (R10)
  - **File:** `scripts/planning_migrate.py`, `core/sw-reference/planning-unit.schema.json`
  - **Expected:** the migration records each cancelled/superseded point-fix PRD (025/028/029/030) as a unit with
    `status: superseded`/`cancelled` and the corresponding supersession edge to a named absorbing unit id
    (recorded in the migration map), satisfying brainstorm R46 mechanically; per R28 these edges are reversible.
    Fixture: `cancelled-prd-supersession-edges`.
  - **R-IDs:** R10
- [ ] 7.2 Interim privacy guard — no exposure before PRD 034 (R18)
  - **File:** `scripts/planning-privacy-guard.sh`, `.gitignore`
  - **Expected:** the migration backfills `visibility: private` (interim `legacy-pre-034` profile token) for every
    unit whose pre-migration source path was gitignored (brainstorms, decision bodies); the R7 `.gitignore`
    relocation preserves the ignored status of those body paths until 034; a pre-commit/cutover gate fails closed
    if any formerly-gitignored body would become tracked by the migration commit. Fixtures:
    `privacy-backfill-legacy-token`, `formerly-ignored-body-tracked-fails`.
  - **R-IDs:** R18
- [ ] 7.3 INDEX private-row provisional + 034 handoff (R33)
  - **File:** `scripts/planning_index_gen.py`, `core/sw-reference/layout.md`
  - **Expected:** INDEX metadata for `visibility: private` units (title/edges) is provisional until PRD 034
    defines redaction/omission of private rows; 031 keeps such bodies ignored (R18) and records this as a 034
    handoff. Fixture: `private-index-row-provisional`.
  - **R-IDs:** R33
- [ ] 7.4 Release-train legacy GAP-BACKLOG/INDEX projections (R27)
  - **File:** `scripts/planning_legacy_projection.py`, `scripts/wave_living_docs.py`
  - **Expected:** 031 ships same-day with 032 (guards) and 033 (lifecycle/reconciler) as one atomic cutover; the
    compatibility layer generates legacy `docs/prds/GAP-BACKLOG.md` + `INDEX.md` projections from the planning/gap
    units until `wave_living_docs`, `reconcile-status`, `feedback-backlog`, and the feedback skills are migrated;
    no config flip merges to `main` that leaves the loop reading a half-migrated tree. Fixtures:
    `legacy-projection-gapbacklog-index`, `no-half-migrated-merge`.
  - **R-IDs:** R27
- [ ] 7.5 Kill-criteria / falsification plan + relief acceptance check (R28)
  - **File:** `scripts/relief-acceptance-check.sh`, `core/sw-reference/layout.md`
  - **Expected:** the cutover documents a fallback — if 032/033 slip past a defined threshold or the 033
    reconciler misses an accuracy floor on the fixture corpus, the program falls back to the shim + legacy layout
    and the R10 supersession edges are reversible; the cutover is gated on a relief acceptance check (post-reconcile
    INDEX `derived` status matches deliver state), not merely migration `--verify`. Fixtures:
    `relief-acceptance-gates-cutover`, `kill-criteria-fallback-documented`.
  - **R-IDs:** R28

### 8. Documentation currency + dist propagation + no-regression + memory guardrails — L

- [ ] 8.1 Foundation-artifact dist propagation + emitter parity (R25)
  - **File:** `scripts/copy-to-core.sh`, `core/scripts/copy-to-core.sh`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** foundation artifacts land in `core/` and propagate to both dist trees; `copy-to-core` parity and
    emitter-freshness fixtures cover the new scripts and schemas (including `planning-unit.schema.json` and the
    updated `workflow.config.example.json`); the cutover checklist includes a mandatory `copy-to-core` +
    emitter-fixture run so dist installs do not drift mid-migration. Fixtures: `copy-to-core-parity`,
    `emitter-freshness-planning-artifacts`.
  - **R-IDs:** R25
- [ ] 8.2 Path/layout source-of-truth documentation updates (R26)
  - **File:** `.sw/layout.md`, `core/sw-reference/layout.md`, `core/sw-reference/config.schema.json`, `.sw/workflow.config.example.json`, `core/sw-reference/workflow.config.example.json`, `.gitignore`, `core/skills/spec-rigor/SKILL.md`, `core/skills/spec-union/SKILL.md`, `README.md`, `docs/guides/configuration.md`
  - **Expected:** as acceptance criteria (not follow-on), `layout.md` and its emitter mirror document the unit
    tree, the frontmatter schema reference + `planning-unit.schema.json` path, INDEX active/archive + SUPERSEDED
    manifest paths, the command read/write map, and a pinned Migration cutover checklist referencing R27/R28;
    `config.schema.json` adds `planningDir` + legacy dir-key aliases; both `workflow.config.example.json` copies
    add `planningDir` + alias note; `.gitignore` is a mechanical relocation of ignore/un-ignore rules from
    `docs/prds` to `docs/planning/` only (per R18); the spec-rigor/spec-union SKILLs point parsing at the shared
    tokenizer, document `--check`/`--write` + template slots, and replace `docs/prds` literals with
    `planningDir`/layout-relative examples; `README.md` (living-doc path bullets) and `configuration.md`
    (`planningDir` + legacy-alias rows; living-doc path paragraph) are updated; the exclusion clause is honored
    (no `living-status/SKILL.md`, deliver/status/command procedure docs, autonomy/feedback routing docs, or
    visibility-driven `.gitignore` generator). Fixture: `doc-currency-layout-config-skills-readme-guide`.
  - **R-IDs:** R26
- [ ] 8.3 No documentation gate regresses on the migrated corpus (R17)
  - **File:** `scripts/spec-rigor-check.sh`, `scripts/traceability-check.sh`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** frozen immutability, traceability, and spec-rigor are preserved (re-expressed over the
    tokenizer) with no regression on the migrated corpus; the merge-to-`main` gate is unchanged; the foundational
    frozen workflow invariants (worktree isolation, freeze-at-handoff with no unfreeze, amendment-only changes,
    doc/implementation separation) are retained. Fixture: `no-regression-migrated-corpus`.
  - **R-IDs:** R17
- [ ] 8.4 Memory guardrails + redaction chokepoint unchanged (R30)
  - **File:** `scripts/memory-redact.sh`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** the redaction chokepoint (`memory-redact.sh`) and memory guardrails are unchanged; this PRD
    introduces no memory writes and no new credential surfaces. Fixture: `no-memory-writes-redaction-unchanged`.
  - **R-IDs:** R30

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | none |
| 4 | 3 |
| 5 | 3, 4 |
| 6 | 3, 4, 5 |
| 7 | 2, 6 |
| 8 | 7 |

## Traceability

| R-ID | Task | Test scenario |
|------|------|---------------|
| R1 | 3.1 | schema-fields-and-type-enum |
| R2 | 3.2 | unit-folder-and-id-stability |
| R3 | 3.3 | gap-unit-in-unified-index |
| R4 | 3.4 | status-type-conditioned |
| R5 | 5.1 | single-unified-index-from-frontmatter |
| R6 | 6.2 | migrate-relocates-all-verbatim |
| R7 | 4.2 | paths-resolve-through-config |
| R8 | 6.3 | migration-one-to-one |
| R9 | 5.2 | region-preserve-byte-for-byte |
| R10 | 7.1 | cancelled-prd-supersession-edges |
| R11 | 1.1 | doc-format-grammar-tokenizes |
| R12 | 2.2 | consumers-tokenizer-only |
| R13 | 2.1 | check-fail-closed-diagnostics |
| R14 | 2.3 | directive-zero-ids-fails-closed |
| R15 | 2.4 | golden-before-after-equivalence |
| R16 | 2.5 | phaseA-legacy-paths-no-relocation |
| R17 | 8.3 | no-regression-migrated-corpus |
| R18 | 7.2 | formerly-ignored-body-tracked-fails |
| R19 | 3.5 | validate-tracked-private-rejected |
| R20 | 6.1 | migrate-atomic-staging |
| R21 | 6.4 | migration-lock-toctou |
| R22 | 1.2 | call-site-map-exhaustion |
| R23 | 4.1 | realpath-containment-reject-escape |
| R24 | 5.3 | region-hook-rejects-cross-writer |
| R25 | 8.1 | copy-to-core-parity |
| R26 | 8.2 | doc-currency-layout-config-skills-readme-guide |
| R27 | 7.4 | legacy-projection-gapbacklog-index |
| R28 | 7.5 | relief-acceptance-gates-cutover |
| R29 | 6.5 | migration-scope-docs-config-only |
| R30 | 8.4 | no-memory-writes-redaction-unchanged |
| R31 | 1.3 | tokenizer-deterministic-offline |
| R32 | 6.5 | opmaps-gitignored-redacted |
| R33 | 7.3 | private-index-row-provisional |

## Notes

- Existing surfaces refactored (not exhaustive): `scripts/spec-union.sh`, `scripts/spec-rigor-check.sh`,
  `scripts/traceability-check.sh`, `scripts/wave_deliver.py`, `scripts/wave_deliver_loop.py`,
  `scripts/wave_spec_seed.py`, `scripts/wave_living_docs.py`, `scripts/reconcile-status.sh`,
  `scripts/feedback-backlog.sh`, `scripts/copy-to-core.sh`.
- New substrate scripts/schemas live in `core/` and propagate via `copy-to-core` to both dist trees (R25):
  `scripts/doc_format.py`, `scripts/doc-format-normalize.sh`, `scripts/planning_status_enum.py`,
  `scripts/planning-unit-validate.sh`, `scripts/planning_paths.{py,sh}`, `scripts/planning_index_gen.py`,
  `scripts/index-region-guard.sh`, `scripts/planning_migrate.py`, `scripts/planning_path_redirect.py`,
  `scripts/planning_legacy_projection.py`, `scripts/relief-acceptance-check.sh`,
  `scripts/planning-privacy-guard.sh`, and `core/sw-reference/planning-unit.schema.json`.
- All new fixtures register in `core/sw-reference/pr-test-plan.manifest.json` and run in `verify.test`.
- Atomic release train (R27): 031 + 032 (guards) + 033 (reconciler) ship same-day; PRDs 034/035 `depends:` on
  this train. Phase Dependencies above are intra-PRD only.
