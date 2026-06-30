---
date: 2026-06-27
topic: planning-feedback-lifecycle
brainstorm: docs/brainstorms/2026-06-27-planning-feedback-lifecycle-requirements.md
frozen: true
frozen_at: 2026-06-27
---

# PRD 031 — Planning-Unit Model, Migration & Doc-Format Tokenizer (Foundation)

## Overview

Establish the foundation of the unified Planning & Feedback Lifecycle: a single typed **planning-unit**
data model, a clean `docs/planning/` home reached by a one-time content-preserving migration, and a single
shared doc-format tokenizer that all spec parsers consume. This PRD is the root of a five-PRD program:
032 (mutation-safety guards), 033 (lifecycle/dependencies/scheduler), 034 (visibility/store), 035
(autonomy/orchestration). The later PRDs `depends:` on this one. It deliberately scopes to the model,
migration, and parsing substrate — not guards, lifecycle automation, visibility backends, or autonomy.

Derived from the frozen brainstorm requirements R1–R8, R26, R32–R35, R46, R47. Greenfield decision per the
brainstorm: this work cancels/supersedes point-fix PRDs 028/029/030 (and 025), folding their problems into
this coherent architecture.

**Atomic release train (doc-review decision, D11):** 031, **032 (guards), and 033 (lifecycle/reconciler)
ship same-day as one atomic cutover**, and the compatibility layer additionally **generates legacy
`docs/prds/GAP-BACKLOG.md` + `INDEX.md` projections** from the planning/gap units until every legacy-path
consumer is migrated. A path alias alone is insufficient — `wave_living_docs.LIVING_PATHS`,
`reconcile-status.py`, and `feedback-backlog.py` hardcode the legacy living-doc paths, and cutting over
without 032 would leave the committed in-flight signal empty and amendments-to-completed unguarded (the two
most acute user pains). See R27.

**Two-phase tokenizer (doc-review decision, D12):** the shared tokenizer ships **Phase A on the current
`docs/prds` paths first** — a standalone GAP-045 parser-parity win with no relocation — gated by the
golden-corpus regression. The big-bang relocation is **Phase B**. A documented **kill-criteria/falsification
plan** (R28) makes the program reversible: if 032/033 slip past a threshold or the reconciler misses an
accuracy floor on the fixture corpus, the program falls back to the shim + legacy layout, and the R10
supersession edges are reversible.

## Goals

- Define one canonical planning-unit frontmatter schema and folder convention covering all artifact types
  (brainstorm, gap, prd, decision, amendment), backed by a committed `planning-unit.schema.json`.
- Relocate the existing corpus (PRDs **including their task lists and amendment trees**, gaps, brainstorms,
  the decision index, and the GAP feedback-checklist) into `docs/planning/` with frozen content preserved
  verbatim and a verifiable 1:1 mapping, including reconstructed supersession edges for the cancelled
  point-fix PRDs.
- Make every path-dependent component resolve through config, eliminating hardcoded `docs/prds`.
- Replace the mutually-disagreeing regex parsers with one shared tokenizer used by spec-union, spec-rigor,
  traceability, and wave_deliver, with `--check`/`--write` modes and machine-readable templates, shipped
  Phase A on legacy paths before relocation.
- Define the INDEX frontmatter schema seam (reconciler-owned derived fields vs deliver-owned in-flight
  fields) with an enforced read-merge-write contract so downstream writers (033 reconciler, 032 in-flight
  signal) never collide.
- Preserve every existing documentation gate (freeze immutability, traceability, spec-rigor) with no
  regression on the migrated corpus, never publish a formerly-private body at cutover, and update the
  operator-facing path/layout documentation so it does not drift.

## Non-Goals

- The mutation-safety guards and the committed in-flight *signal writer* (PRD 032). 031 defines only the
  INDEX schema slot the signal occupies; 032 rides the same atomic cutover (R27).
- Lifecycle state-machine automation, dependency-graph scheduling, priority enforcement, and the
  reconciler that *populates* derived INDEX status (PRD 033). 031 ships only a stub status enum (values
  only); 033 owns transition semantics.
- Visibility/privacy *semantics*, the `planning.store`, and private-unit materialization (PRD 034). 031
  ships only an interim ignore-preserving guard (R18) so the big-bang commit cannot publish a
  formerly-private body before 034.
- Autonomy, backlog pull-in, two-track doc edits, and the autonomy posture (PRD 035).
- Any change to the human merge-to-`main` gate or to the delivery/wave execution engine.
- Reviving "memory as the sole source of truth" — superseded by PRD 015; out of scope here.
- **Mechanical vs gated split:** mechanical supersession/absorption *edge effects* and reconciler status
  flips are owned by PRD 033; supersession/absorption *proposal and human-gated authoring* are owned by
  PRD 035. 031 only relocates existing edges and records the cancelled-PRD supersession edges (R10).

## Requirements

- **R1** A single canonical planning-unit frontmatter schema defines the fields `id`, `type`, `status`,
  `title`, `visibility`, `depends`, `blocks`, `supersedes`, `extends`, `absorbs`, `priority`, and `tags`,
  with `type` one of `brainstorm`, `gap`, `prd`, `decision`, `amendment`; a committed
  `core/sw-reference/planning-unit.schema.json` validates it.
- **R2** Every planning unit is a folder containing a canonical-frontmatter body file **plus optional
  ancillary tracked files** (e.g. a PRD unit's frozen task lists and `amendments/` tree); unit ids are
  stable, monotonic, and never reused, and all cross-references use the unit id (never a table row or
  positional reference).
- **R3** Gaps are first-class units (folder + frontmatter), replacing GAP-BACKLOG table rows; gaps render
  as rows in **the single generated unified INDEX (R5)**, not a separate gap-only index.
- **R4** `status` validation is **type-conditioned** and single-sourced: gap-type units use the gap enum
  (`open`, `planned`, `partially resolved`, `resolved`); all other unit types use the lifecycle enum owned
  by PRD 033 (`proposed`, `planned`, `in-progress`, `complete`, `superseded`, `cancelled`, `deferred`,
  `blocked`). 031 ships a **minimal stub enum module (values only, no transition logic)** that the validator
  imports; PRD 033 replaces/extends it with transition semantics. The schema enforces the correct enum per
  `type`, rejects cross-enum tokens, and documents the `planned` homonym as distinct per type.
- **R5** The canonical planning-unit home is a typed-unit tree under `docs/planning/`, with **one** generated
  unified INDEX produced from unit frontmatter.
- **R6** A one-time, idempotent migration relocates **all** existing artifacts into the unified model: PRD
  folders **including their nested frozen task lists and `amendments/` trees**, gap rows, brainstorms, the
  decision index, and the GAP feedback-checklist content. Frozen unit content is preserved verbatim
  (relocation plus frontmatter backfill only, with no body edits).
- **R7** All path-dependent machinery (spec-seed, deliver path resolution, living-docs **path resolution**,
  `.gitignore`, freeze/immutability checks) resolves paths through config dirs (`planningDir` plus the
  existing `prdsDir`/`tasksDir`/`decisionsDir`); no component hardcodes `docs/prds`. 031 reroutes paths
  only — reconcile *logic* and derived-status population remain PRD 033.
- **R8** A migration-verification fixture proves every pre-migration artifact maps one-to-one to a
  post-migration unit with byte-preserved body content and reconstructed edges. It is staged into explicit
  snapshots — PRD folders (with task lists + amendment trees), gap units, brainstorms, the decision index,
  and cancelled-PRD edges — and validates an explicit `GAP-id → unit-id` map and feedback-checklist item
  preservation as separate assertions.
- **R9** The generated INDEX is produced deterministically from frontmatter (id, type, title, status,
  visibility, edges) and never hand-maintained. It carries **two disjoint writer-owned regions**: a
  `derived` region (reconciler-owned, PRD 033) and an `inFlight` region (deliver-owned, PRD 032). At
  cutover both regions are **empty schema slots**. The generator and every INDEX writer use **read-merge-
  write**: they parse the existing INDEX and preserve the non-owned region byte-for-byte; full-file regen
  that drops a sibling region is prohibited. **Status precedence:** lifecycle-unit consumers read
  `derived.status` when populated and fall back to structural frontmatter `status`; gap units use
  structural status only; this rule is stated in the INDEX schema doc.
- **R10** The migration records, for each cancelled/superseded point-fix PRD (025/028/029/030), a unit with
  `status: superseded`/`cancelled` and the corresponding supersession edge **to a named absorbing unit id**
  (recorded in the migration map), satisfying brainstorm R46 mechanically. Per the kill-criteria (R28),
  these supersession edges are reversible.
- **R11** A single shared doc-format tokenizer/grammar defines the canonical structure for unit frontmatter
  and body (R/D-ID bullets, section headings, traceability cells, phase headings, and directive lists
  including block-list `absorbs`/`supersedes`/`retracts`).
- **R12** `spec-union`, `spec-rigor-check`, `traceability-check`, and `wave_deliver` parse exclusively
  through the shared tokenizer; no component retains an independent structural regex. Per-consumer baseline
  snapshots are captured *before* adoption. Semantic divergence classes are recorded in a **machine-checked
  exception manifest** keyed per file + per consumer + per divergence-class; the gate **fails closed on any
  unlisted divergence**, the manifest is finite/capped and requires doc-review sign-off, and exceptions may
  not cover post-migration edits.
- **R13** The tokenizer provides a `--check` mode (fail closed with file:line, expected/found diagnostics,
  never a silent drop) and a `--write` mode (structural canonicalization only — shape, never content —
  idempotent); a pre-freeze structural check runs before union and traceability, and authoring commands
  pipe output through `--write` before persisting so non-canonical drafts cannot reach freeze.
- **R14** Authoring commands emit machine-readable slot-filling templates matching the canonical shape, and
  a non-empty directive key (`absorbs`/`supersedes`/`retracts`) that yields zero parsed ids fails closed.
- **R15** The golden-corpus regression proves, for the migrated frozen set plus the GAP-045 adversarial
  structural variants: **(a)** per-consumer parse equivalence before vs after tokenizer adoption; **(b)**
  four-consumer agreement on extracted id sets **after** adoption; and **(c)** a post-`--write` round-trip
  asserting no consumer's extracted requirement set changes. Any unit not in the R12 exception manifest that
  diverges fails the gate.
- **R16** **Tokenizer Phase A** ships on the current `docs/prds` paths first — full tokenizer adoption +
  golden-corpus regression with **no relocation** — delivering the GAP-045 parser-parity relief
  independently. The big-bang relocation (R5–R10) is **Phase B**; Phase A acceptance does not depend on the
  planning-unit schema or `docs/planning/`.
- **R17** No documentation gate regresses: frozen immutability, traceability, and spec-rigor are preserved
  (re-expressed over the tokenizer); the merge-to-`main` gate is unchanged; and the foundational frozen
  workflow invariants (worktree isolation, freeze-at-handoff with no unfreeze, amendment-only changes,
  doc/implementation separation) are retained.
- **R18** **Interim privacy guard (no exposure before PRD 034):** the migration backfills `visibility:
  private` (interim `legacy-pre-034` profile token) for every unit whose pre-migration source path was
  gitignored (brainstorms, decision bodies); R7's `.gitignore` relocation **preserves the ignored status**
  of those body paths until 034 activates visibility profiles; and a pre-commit/cutover gate **fails closed
  if any formerly-gitignored body would become tracked** by the migration commit. (R19's tracked-private
  rejection is necessary but not sufficient — it does not block a default-public unit from being committed.)

## Technical Requirements

- **R19** The `planning-unit.schema.json` plus a validator entrypoint (`scripts/planning-unit-validate.py`)
  fails closed on unknown keys, cross-enum/unknown status tokens (per the type-conditioned R4 stub enum),
  and — at migration/bootstrap time — on a `visibility: private` unit whose body path is git-tracked.
  Ongoing visibility validation is PRD 034.
- **R20** The migration tool exposes `--dry-run`, `--write`, `--verify`, and `--rollback`. It runs the
  relocation as a **single atomic commit** with **filesystem-atomic staging** (relocations staged under a
  temp prefix; the reverse map + `GAP-id → unit-id` map emitted only **after** a successful commit; safe to
  re-run / idempotent). `--rollback` performs a **dirty-tree/post-edit preflight** (refuse if `docs/planning/`
  has post-migration edits or newer-than-commit units unless `--force` with a logged reason), restores the
  pre-migration tree from the reverse map, **and restores config keys in inverse order** (flip `planningDir`
  back before/with the tree restore). `--verify` is a mandatory gate before the config flip.
- **R21** A **migration lock/sentinel** is acquired atomically with the run-state scan and **held through
  `--verify`** (re-checked immediately before commit), closing the TOCTOU window. The run-state scan
  covers **all linked git worktrees and `.sw-worktrees/**`** (not a root-only glob), and while held it
  refuses `/sw-deliver` run-start, living-doc reconcile, and `/sw-feedback` gap-append. A legacy→migrated
  **path-redirect map** is consumed by an explicit, enumerated consumer list (`wave_deliver_loop`,
  `wave_deliver` preflight/plan, `wave_spec_seed`, freeze-immutability checks, phase `**File:**` touch
  detection, living-docs); the cutover checklist enumerates open feature branches/worktrees carrying
  `docs/prds` task lists and resolves or halts on them.
- **R22** A single tokenizer module (`doc_format.py` with a `doc-format-normalize.py` wrapper) is consumed
  by `spec-union`, `spec-rigor-check`, `traceability-check`, and `wave_deliver`; an explicit **call-site
  map** (per the PRD 021/022 pattern) enumerates every runtime reader/writer, and cutover is gated on map
  exhaustion. `wave_deliver` phase/`**File:**` parsing is in tokenizer scope from Phase A.
- **R23** A path-resolution helper (`scripts/planning_paths.*`) plus the `planningDir` config key route all
  planning-path reads/writes. It resolves paths with **canonical realpath**, requires the resolved path to
  stay under the worktree root, and **rejects `..` traversal and symlinks that escape the worktree**
  (absolute paths contained within the worktree are allowed); a fixture proves no path-dependent component
  references a hardcoded `docs/prds` literal.
- **R24** A deterministic INDEX generator (frontmatter → INDEX) is wired into the living-doc single-writer
  lock and implements the R9 read-merge-write contract (preserve the non-owned region byte-for-byte). A
  **region-integrity hook (pre-commit + CI)** rejects commits that modify the `derived` region outside the
  reconciler or the `inFlight` region outside the deliver writer, and rejects an empty `inFlight` tuple when
  live deliver run-state exists.
- **R25** Foundation artifacts land in `core/` and propagate to both dist trees; `copy-to-core` parity and
  emitter-freshness fixtures cover the new scripts and schemas (including `planning-unit.schema.json` and
  the updated `workflow.config.example.json`), and the cutover checklist includes a mandatory `copy-to-core`
  + emitter-fixture run so dist installs do not drift mid-migration.
- **R26** This PRD updates the path/layout source-of-truth documentation it invalidates, as **acceptance
  criteria** (not follow-on work):
  `.sw/layout.md` and its emitter mirror `core/sw-reference/layout.md` (unit tree; frontmatter schema
  reference + `planning-unit.schema.json` path; INDEX active/archive + SUPERSEDED manifest paths; command
  read/write map; a pinned **Migration cutover checklist** section referencing R27/R28);
  `core/sw-reference/config.schema.json` (add `planningDir`; document legacy dir-key aliases); **both**
  `workflow.config.example.json` copies (`.sw/` and `core/sw-reference/`, add `planningDir` + alias note);
  `.gitignore` (**mechanical relocation of ignore/un-ignore rules from `docs/prds` to `docs/planning/`
  only** — see R18); `core/skills/spec-rigor/SKILL.md` and `core/skills/spec-union/SKILL.md` (point parsing
  at the shared tokenizer, document `--check`/`--write` + template slots, replace `docs/prds` literals with
  `planningDir`/layout-relative examples); `README.md` (living-doc path bullets) and
  `docs/guides/configuration.md` (`planningDir` + legacy-alias config rows; living-doc path paragraph).
  **Exclusion clause:** 031 does **not** own `core/skills/living-status/SKILL.md`, deliver/status/command
  procedure docs, the autonomy/feedback routing docs (PRD 033/035), or the **visibility-profile-driven**
  `.gitignore` generator (PRD 034); `layout.md` is the interim path authority until those siblings land.
- **R27** **Release train:** 031, 032 (guards), and 033 (lifecycle/reconciler) ship **same-day as one
  atomic cutover**; additionally, the compatibility layer **generates legacy `docs/prds/GAP-BACKLOG.md` +
  `INDEX.md` projections** from the planning/gap units until `wave_living_docs`, `reconcile-status`,
  `feedback-backlog`, and feedback skills are migrated. No config flip merges to `main` that leaves the loop
  reading a half-migrated tree.
- **R28** **Kill-criteria / falsification plan:** the cutover documents a fallback — if 032/033 slip past a
  defined threshold or the 033 reconciler misses an accuracy floor on the fixture corpus, the program falls
  back to the shim + legacy layout; R10 supersession edges are reversible; and the cutover is gated on a
  **relief acceptance check** (post-reconcile INDEX `derived` status matches deliver state), not merely
  migration `--verify`.

## Security & Compliance

- **R29** The migration touches documentation artifacts and the path-resolution/`.gitignore` config keys
  only; it never moves or modifies code, secrets, or other configuration. (The `.gitignore` + `planningDir`
  changes affect what git tracks — covered by the R18 interim privacy guard and the R24 region hook.)
- **R30** The redaction chokepoint (`memory-redact.py`) and memory guardrails are unchanged; this PRD
  introduces no memory writes and no new credential surfaces.
- **R31** The tokenizer is deterministic and offline (no network; same input yields same output) so CI
  gates remain reproducible.
- **R32** The reverse map and `GAP-id → unit-id` map are operational artifacts (not planning units): stored
  gitignored under `.cursor/`, never containing body content, with old paths redacted for private-source
  units.
- **R33** INDEX metadata for `visibility: private` units (title/edges) is provisional until PRD 034 defines
  redaction/omission of private rows; 031 keeps such bodies ignored (R18) and records this as a 034 handoff.

## Testing Strategy

- Migration one-to-one fixture (R8): staged corpus snapshots (PRD folders + task lists + amendment trees,
  gaps, brainstorms, decision index, cancelled-PRD edges) migrate with byte-identical bodies; the
  `GAP-id → unit-id` map and feedback-checklist preservation validate as separate assertions; `--verify`
  fails closed on drift.
- Atomicity/interruption fixture (R20): a simulated mid-migration interruption leaves a recoverable state
  (temp-staged, reverse map not yet emitted); re-run is idempotent; partial trees never pass `--verify`;
  `--rollback` refuses on a dirty/post-edited tree without `--force` and restores config keys inversely.
- Migration-lock/TOCTOU fixture (R21): a deliver run-start attempted during the held lock is refused;
  run-state is detected across `.sw-worktrees/**`; the path-redirect map resolves legacy paths on resume
  across the enumerated consumer list.
- INDEX region fixtures (R9, R24): concurrent generator/reconciler/deliver writes preserve the non-owned
  region byte-for-byte; a full-file regen dropping `inFlight` is rejected by the region-integrity hook; an
  empty `inFlight` with live run-state fails closed; status-precedence resolves derived-vs-structural.
- Tokenizer fixtures (R12–R16): Phase A adoption on legacy paths passes the golden corpus; per-consumer
  before/after equivalence, post-adoption four-consumer agreement, and post-`--write` round-trip all hold;
  an unlisted divergence fails closed; the exception manifest is finite and sign-off-gated.
- Schema-validation fixtures (R1, R4, R19): valid unit accepted; unknown key, cross-enum status token, and
  a migration-time tracked private-body path are rejected; the stub enum rejects lifecycle tokens on gap
  units and vice-versa.
- Interim-privacy fixtures (R18): a formerly-gitignored brainstorm/decision body that would become tracked
  fails the pre-commit cutover gate; the migration backfills `legacy-pre-034` private visibility.
- Path-resolution/symlink fixtures (R23): no hardcoded `docs/prds` literal remains; a symlink escaping the
  worktree is rejected by realpath containment.
- Supersession-edge fixture (R10): cancelled PRDs 025/028/029/030 migrate to superseded units with named
  absorbing-unit edges; edges are reversible.
- Doc-currency + emitter fixtures (R25, R26): layout/config/example-config/.gitignore/skill-doc/README/guide
  surfaces reflect the new layout; emitter/parity pass for `planning-unit.schema.json` + example config.
- Release-train + kill-criteria fixtures (R27, R28): the generated legacy GAP-BACKLOG/INDEX projections keep
  `feedback-backlog`/`wave_living_docs` working pre-migration of those consumers; the relief acceptance
  check gates the cutover.
- No-regression run (R17) on the migrated corpus.

## Rollout Plan

1. **Tokenizer Phase A (no relocation, R16):** land the shared tokenizer module + the four consumers
   switched to it on the current `docs/prds` paths behind the golden-corpus regression (baselines captured
   first). Standalone shippable parser-parity relief.
2. **Substrate:** land the planning-unit schema + validator (stub enum), the path-resolution helper +
   `planningDir` key (default still resolves to today's layout), and the INDEX generator with the
   read-merge-write contract + region-integrity hook.
3. **Migration tooling:** land the migration tool (`--dry-run`/`--verify`/`--rollback`, temp-staged,
   filesystem-atomic), the held migration lock + cross-worktree run detection (R21), and the path-redirect
   map across the enumerated consumer list.
4. **Cutover (atomic train, R27/R28):** stop runs → acquire lock → big-bang migration (Phase B) → `--verify`
   → relief acceptance check → flip path resolution → regenerate INDEX → reconcile. Ships same-day with 032
   (guards) and 033 (reconciler) plus the generated legacy GAP-BACKLOG/INDEX projections. Mandatory
   `copy-to-core` + emitter-fixture run. Falls back to shim + legacy layout if the kill-criteria trip.
5. **Handoff:** PRD 034 (visibility/store) and PRD 035 (autonomy) `depends:` on this train and proceed once
   it is complete.

## Decision Log

- **D1.** Big-bang relocation to `docs/planning/` (not in-place backfill) — chosen for the clean end state;
  the large blast radius is accepted as scoped migration work with a one-to-one verification fixture,
  atomic commit, rollback path, and the R28 kill-criteria.
- **D2.** One shared tokenizer module consumed by all four parsers — eliminates the mutually-disagreeing
  regex problem (GAP-045) at the root; baselines captured first because the consumers do not agree today.
- **D3.** Config-driven path resolution (`planningDir` plus existing dirs) via one helper — the cutover is a
  config/resolver flip rather than scattered edits.
- **D4.** Gaps become first-class units (folder-per-item) rendered in the single unified INDEX — pull-in,
  absorption, and supersession become edge operations in later PRDs.
- **D5.** Migration preserves frozen content verbatim and is verified one-to-one — freeze immutability is
  honored; only location and frontmatter are added.
- **D6.** INDEX generation lands here with a schema seam that splits the reconciler-owned `derived` region
  (PRD 033) from the deliver-owned `inFlight` region (PRD 032), **enforced by read-merge-write + a
  region-integrity hook** (D13) rather than convention.
- **D7.** Migration bootstrapping (resolves brainstorm OQ2/OQ8): the cutover runs as a one-shot atomic
  commit outside the deliver loop, gated by the held migration lock (R21). Because 032 now ships in the same
  atomic train (D11), the committed in-flight signal is backfilled by 032's migration-bridge within the
  cutover; the deliver-freeze window + path-redirect map protect in-progress units during the move.
- **D8.** `decision` remains a distinct unit type (resolves brainstorm OQ4); the schema `type` enum is
  `brainstorm`, `gap`, `prd`, `decision`, `amendment` (R1). Distilled `design` content stays a memory class.
- **D9.** The INDEX generator seam is a single deterministic generator (resolves brainstorm OQ7); the
  active/archived split is realized in PRD 033. 031 documents the path placeholders + generator seam;
  archive collapse semantics are 033 acceptance criteria cross-referenced from `layout.md`.
- **D10.** 031 owns the documentation-currency updates for the path surfaces it invalidates (R26) with an
  explicit exclusion clause; the docs-currency panel showed the path move silently breaks `.sw/layout.md`,
  `config.schema.json`, `.gitignore`, the example configs, and the tokenizer-consumer skills if treated as
  follow-on work.
- **D11.** **Release train = 031+032+033 same-day + generated legacy GAP-BACKLOG/INDEX projections**
  (doc-review decision). A path alias alone is insufficient, and the acute user pains (lost amendments,
  silent in-flight mutation) are 032-owned — so guards + lifecycle truth land **at** cutover, not after
  (R27).
- **D12.** **Tokenizer Phase A on legacy paths first + kill-criteria** (doc-review decision). The standalone
  parser-parity win validates the engine before the irreversible relocation; R28 makes the program
  reversible (reversible R10 edges, slip/accuracy fallback to shim + legacy).
- **D13.** The disjoint-region seam is enforced by **read-merge-write + a pre-commit/CI region-integrity
  hook** (R9/R24), not ownership-by-convention — closing the adversarial full-file-regen clobber scenario.
- **D14.** The migration is guarded by a **held lock through `--verify` with cross-worktree run detection**
  (R21) — closing the adversarial TOCTOU window and the feasibility root-only-scan gap.
- **D15.** R15 is **semantic equivalence with a machine-checked, capped, sign-off-gated exception manifest**
  plus a post-`--write` round-trip (not byte-identical four-way parity, which is impossible given today's
  divergent baselines) — resolving the coherence/feasibility/adversarial R12↔R15 contradiction.
