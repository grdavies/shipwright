---
date: 2026-06-27
topic: planning-feedback-lifecycle
brainstorm: docs/brainstorms/2026-06-27-planning-feedback-lifecycle-requirements.md
depends: [031, 033]
frozen: true
frozen_at: 2026-06-27
---

# PRD 034 — Per-Unit Visibility & Pluggable Planning Store

## Overview

Give every planning unit a `visibility:` and route unit *bodies* through a pluggable `planning.store` so a
user of a **public** repo can keep early thinking — and, via the store seam, specs — private without
breaking the delivery loop. The tracked INDEX always lists every unit but **redacts** private bodies to
id/title/status/edges. Private spec units required by a delivery run are **materialized (copied) into
the phase worktree on demand** from the configured store, because the deliver loop reads spec content inside
the agent's worktree (not GitHub CI) — delivering private+shareable+durable specs without encryption,
opaque diffs, or keys-in-CI.

`depends:` on PRD 031 (unit schema + path resolution) and **PRD 033** (the reconciler that generates the
INDEX + legacy projections must consume this PRD's visibility resolver; 034 wraps 033 output rather than
reimplementing it). Sequenced **after 033** (parallel-after, before 035). Derived from frozen brainstorm
requirements R9–R16; resolves brainstorm OQ5 (default profile shipped) and OQ6 (memory store ↔ PRD-015
source-of-truth). This is the answer to the user's public-repo privacy concern, including the
no-memory-provider case.

**Public-repo-aware default (doc-review decision).** Rather than a single global `specs-public` default,
`/sw-init` **detects the origin remote**: a **public** remote defaults to `all-private` and requires an
explicit acknowledgement before the first tracked spec commit; a **private** (or no) remote keeps the
zero-config `specs-public` default. This closes the product/adversarial/security "leaky-by-default" foot-gun
while preserving zero-config delivery where it is safe.

## Goals

- Add a per-unit `visibility:` field with a repo-level default profile, resolved **public-repo-aware** at
  init.
- Keep the INDEX always tracked while redacting private/memory unit bodies to metadata + edges only, behind
  a single fail-closed visibility resolver used at every emission point, with an enforced **machine-checked
  call-site map**.
- Define a pluggable `planning.store` interface with shipped backends (`in-repo public`, `local/synced`,
  `memory`) and a clean seam for deferred ones (private repo, encryption-at-rest), pinned for a run's
  duration.
- Materialize private spec units into phase worktrees on demand with a **commit-boundary** barrier, body
  freshness validation, orphan cleanup, and teardown.
- Accept the PRD 032 in-flight-metadata redaction handoff; fail closed everywhere; reconcile the PRD-015
  committed-snapshot vs `.gitignore` conflict.

## Non-Goals

- The unit schema, migration, tokenizer (PRD 031); lifecycle, scheduler, reconciler (PRD 033).
- The in-flight signal **writer** and the mutation-safety guards (PRD 032). 034 **does** own the redaction of
  the committed in-flight signal's branch/run-id metadata for private units (the 032 R13 handoff, see R12);
  it does not write the signal.
- Autonomy, pull-in, two-track edits (PRD 035).
- **Encryption-at-rest and private-repo/submodule backends** — designed-for via the store seam but not
  implemented in v1.
- Reviving "memory as the sole source of truth" — the memory backend is storage-only and does not change
  PRD-015 source-of-truth policy.
- A general-purpose backlog query UI beyond the generated index and `list --json`.

## Requirements

- **R1** Each unit declares `visibility: public|private|memory`; a repo-level default profile
  (`all-private` | `specs-public` | `all-public`) supplies the default when `visibility` is unset.
- **R2** Advisory content classes (`brainstorm`, `decision`, learnings) default to `private`; spec classes
  (`prd`, task lists) default to `public` **under the `specs-public` profile**; both are overridable per
  unit and per profile. (Learnings are a memory class, not a planning-unit type — phrased as content
  classes per the coherence panel.)
- **R3** The default-profile resolution is **public-repo-aware**: `/sw-init` probes the origin remote; a
  public remote selects `all-private` (spec bodies private until the operator opts in) and requires a logged
  acknowledgement before the first tracked spec commit; a private/absent remote selects `specs-public`. The
  resolved profile and the ack are recorded in config + durable state.
- **R4** The INDEX is always tracked; private/memory units are redacted in it to id/title/status/type and
  edges only — never body content. A private unit may opt into an **opaque title** (id + generic label) so a
  sensitive codename in the title is not exposed in the tracked INDEX or PR diffs (adversarial metadata-leak
  mitigation); R23 documents that edges/metadata are not semantically anonymized.
- **R5** Unit bodies are addressed through a pluggable `planning.store` abstraction with a single interface
  (`put`/`get`/`exists`/`materialize`); the default backend is `in-repo public`.
- **R6** Store backends for a `local/synced` folder and the `memory` provider are supported by the same
  interface; the private-repo and encryption backends are seam-compatible but deferred (out of scope v1,
  seam-present-but-inert in tests).
- **R7** Private spec units required by a delivery run are materialized (copied) into the phase worktree at
  provision time from the configured store, **after worktree creation and before any preflight/plan/
  spec-seed read**, so the deliver loop reads them without git-tracking; CI/host never materializes private
  bodies (delivery gates run worktree-local). The **store backend + revision are pinned in deliver run-state
  at provision** and every phase read validates against the pinned backend; a config change to
  `planning.store` mid-run halts with remediation (closes the adversarial backend-swap scenario).
- **R8** Materialized private bodies have a **commit-boundary** barrier, not a point-in-time check: they are
  written under a deterministic ignored prefix (e.g. `.cursor/planning-materialized/`) added to `.gitignore`;
  a `secret-scan file` runs immediately after materialize; **a pre-commit and pre-push hook reject any staged
  path under the materialized prefix (even `git add -f`)**, and a CI check scans PR diffs for the prefix and
  private-body golden markers; a teardown hook deletes the tree on worktree removal (fixture-proven no
  residual). A stale/orphaned materialized tree from a crashed run is swept by a doctor/cleanup check that
  reads the materialize paths recorded in run-state (closes the adversarial point-in-time bypass + the
  security crash-residual finding).
- **R9** Materialization validates body freshness: the unit frontmatter carries a content hash/revision, and
  `materialize` fails closed on a hash mismatch versus the store body (the reconciler warns when graph
  `updated_at` is newer than the store revision), so a stale store body cannot be implemented against a
  newer graph identity. **Cross-PRD freshness contract:** 034 owns the store-revision hash; the 033
  reconciler reads it through this interface and emits structured freshness drift (warn at reconcile, block
  at materialize).
- **R10** A missing, unreachable, or doc-incapable store backend never exposes a private body and never
  silently breaks delivery: it fails closed with explicit remediation guidance (keep the unit public, or
  refuse delivery of the private unit with a message), never a partial/leaky state.
- **R11** Memory-backed visibility routes exclusively through the provider-agnostic memory adapter (never a
  direct provider call) and preserves the redaction chokepoint (`memory-redact.py`) on **both write (`put`)
  and read**; it degrades open when no provider exists or the provider cannot store the document class. A
  fixture bans direct provider MCP calls from the store memory backend (adapter-only). Store memory writes
  are scoped to the configured `memory.project`; a supersede/cancel hook requests body inactivation; the
  `discussion`/`progress` memory classes are banned for planning bodies (no raw transcript sink).
- **R12** The memory store backend is storage/retrieval for unit bodies only and does not alter
  source-of-truth: the unit graph remains the canonical identity, and PRD-015 source-of-truth policy is
  unchanged. For `decision`-class units, the PRD-015 always-committed redacted snapshot + pointer flow runs
  regardless of `visibility`, and a fixture proves a `visibility: memory` decision cannot bypass the
  committed snapshot. **032 in-flight handoff:** the visibility resolver redacts the committed `inFlight`
  tuple's branch/run-id to the 032 R13 opaque-token form for `private`/`memory` units, so the in-flight
  signal carries no sensitive branch/codename metadata.
- **R13** The model governs decision-record visibility and reconciles the PRD-015 committed-snapshot vs
  `.gitignore` conflict: the `.gitignore` is **generated from the visibility resolver** (track frontmatter
  stubs + public bodies only); the migration verifier asserts zero private-body bytes in the git index, and
  `planning-unit-validate.py` rejects a `visibility: private` unit whose body path is tracked. (This is the
  **visibility-profile-driven** `.gitignore` generation; PRD 031 R24 only relocated the rules mechanically.)
- **R14** Visibility is enforced at every emission point through a single central resolver/wrapper, and a
  **machine-checked call-site map (PRD 021/022 pattern) enumerates every planning-body read/write path**; CI
  fails on any planning-body read that bypasses the resolver. The emission-point registry covers at minimum:
  INDEX (active + archive), **the 033 legacy GAP-BACKLOG/INDEX projections**, PR diffs, dispatch/subagent
  context, spec-seed, `list --json`/store `get`, the SUPERSEDED manifest, **032 handoff artifacts**, **035
  pull-in proposal confirm-lists**, the committed `inFlight` tuple, reconciler output, and run logs. A CI
  check fails if a private-body golden marker appears in any generated artifact; unknown/unresolved
  visibility is treated as `private` (fail-closed).
- **R15** `spec-seed` routes through the visibility resolver: it skips `private`/`memory` bodies entirely,
  commits only public bodies plus the redacted INDEX, and a tracked private body aborts the seed with
  remediation (closing the security panel's spec-seed gap).
- **R16** `local/synced` store paths are validated by a doctor check: the path must resolve inside the
  operator home or a configured allowlist, reject symlinks and `..`, and have a directory mode no looser
  than `0700`; known cloud-sync roots warn (cloud-sync exfiltration risk noted); the backend is documented
  as convenience-not-security and is not the default in public-repo templates.
- **R17** No regression to the documentation that feeds the delivery loop: public units behave exactly as
  today; frozen immutability, traceability, and spec-rigor gates are preserved; the human merge-to-`main`
  gate is unchanged.

## Technical Requirements

- **R18** A `planning.store` interface module with a backend registry; `in-repo public`, `local/synced`, and
  `memory` backends implement it; backend selection is config-driven (`planning.store` in
  `workflow.config.json`) and pinned per run (R7). Store `get`/`put`/`materialize` operations **log
  id+hash+backend only — never body content** (closes the security audit-logging gap).
- **R19** A visibility resolver module (per-unit field over the public-repo-aware profile default) is the
  single authority consumed by the INDEX generator/033 reconciler, the legacy projections, spec-seed,
  dispatch redaction, PR-diff paths, the `inFlight` tuple redaction, and every other emission point in the
  R14 registry; a fixture proves redaction at each point and the call-site map is exhaustive.
- **R20** A worktree materialization hook in the deliver provision path (hooked into
  `wave_lifecycle.py`/`phase provision`, after worktree add and before preflight) copies required private
  spec bodies from the store into the ignored prefix, runs the post-materialize secret-scan, registers the
  materialize paths in run-state for orphan sweep, enforces the commit-boundary barrier (R8), validates
  freshness (R9), and cleans up on teardown, routing through the PRD 031 path helper.
- **R21** `/sw-init` resolves and seeds the **public-repo-aware** default profile (R3) and the default store
  backend, records the first-run privacy notice + ack, and a doctor check validates store
  reachability (degrade-open with actionable remediation when the memory backend is configured but no
  provider is present) and sweeps orphaned materialized trees.
- **R22** A `.gitignore` generator derives tracking rules from the visibility resolver output (R13); store/
  visibility artifacts land in `core/` and propagate to both dist trees; `copy-to-core` parity,
  emitter-freshness, and secret-scan fixtures cover the new scripts and config keys.
- **R23** This PRD updates the docs it changes, as **acceptance criteria**: `.gitignore` (visibility-driven
  generation, R13), `core/skills/memory/SKILL.md` (decision paths under `docs/planning/`; memory store is
  body-only storage), `core/providers/recallium.md` (decision unit paths; storage-only note),
  **`core/rules/memory-guardrails.mdc`** (name the `planning.store` memory backend as adapter +
  `memory-redact.py` chokepoint only — closes the R24-vs-doc-list divergence), `core/commands/sw-init.md`
  (public-repo-aware profile/store/privacy-notice + ack seeding), **`core/skills/deliver/SKILL.md`**
  (provision-time materialization, ignored prefix, commit-boundary barrier, teardown — coordinated with the
  032-owned `inFlight` writer section), **`core/sw-reference/config.schema.json` + both
  `workflow.config.example.json` copies** (the `planning.store` + visibility-profile keys, extending the 031
  `planningDir` precedent), and `docs/guides/configuration.md` (store/profile keys).

## Security & Compliance

- **R24** Redaction is fail-closed and centralized (R14, R19): unknown/unresolved visibility is treated as
  `private`; the resolver is the single authority with a machine-checked call-site map; documented limits —
  regex redaction is not semantic anonymization, so truly sensitive specs are steered to `all-private` +
  `local/synced`, sensitive codenames belong in the private store with a generic INDEX title (R4), and the
  memory backend is never labeled encrypted or anonymized.
- **R25** The redaction chokepoint and memory guardrails are unchanged in posture; memory-routed bodies pass
  through `memory-redact.py` on read and write; no raw transcript or secret is ever stored; the
  memory-guardrails rule is updated (R23) to name the `planning.store` memory backend as routing through the
  adapter + chokepoint only.
- **R26** Materialized private bodies live only inside the agent worktree under the ignored prefix, are never
  committed or pushed (R8 commit-boundary barrier), are swept on crash, and are removed on teardown;
  secret-scan covers materialize-time and store-read-time via the existing `secret-scan.py file|stdin`
  chokepoints.
- **R27** No new credential surface beyond the configured store backend's own auth (e.g. memory provider),
  which uses the existing provider-agnostic adapter; the doctor check never prints provider tokens, store
  config references env-var names only, and store operations never log body content (R18).

## Testing Strategy

- Visibility-default fixtures (R1–R3): profile default applies when unset; per-unit override wins; advisory
  vs spec defaults correct; a public origin remote resolves `all-private` + requires ack; a private remote
  resolves `specs-public`.
- Redaction/emission-point fixtures (R4, R14, R15, R19, R24): private bodies redacted at every registry
  emission point (INDEX, legacy projections, PR diff, dispatch, spec-seed, list --json, SUPERSEDED manifest,
  032 handoff, 035 proposals, inFlight tuple, reconciler, logs); the call-site map is exhaustive (CI fails on
  a bypassing read); opaque-title hides a codename; unknown visibility treated as private.
- Store-interface fixtures (R5–R6, R18): each shipped backend satisfies the interface; deferred backends are
  seam-present but inert; memory backend bans direct provider calls; store ops log id+hash+backend only.
- Materialization fixtures (R7–R9, R20): a private spec is copied into the ignored prefix at provision, read
  by delivery, blocked from commit by the pre-commit/pre-push barrier even under `git add -f`,
  freshness-validated (hash mismatch fails closed), backend pinned for the run, swept on crash, and cleaned
  up; nothing is committed.
- Fail-closed fixtures (R10): missing/unreachable/doc-incapable backend refuses with guidance and never
  leaks; memory absent degrades open.
- PRD-015 + 032-handoff fixtures (R11–R13): decision-class SoT unchanged; a `visibility: memory` decision
  still writes the committed snapshot; `.gitignore` generated from visibility no longer contradicts policy;
  tracked private body rejected; the `inFlight` tuple branch is opaque-token-redacted for private units.
- Path-validation fixture (R16): symlink/`..`/loose-mode/cloud-root store paths are rejected or warned.
- Doc-currency (R23) and emitter/parity/secret-scan fixtures (R22, R26).
- No-regression (R17).

## Rollout Plan

1. **Visibility field + resolver + call-site map:** add the `visibility:` field, public-repo-aware
   default-profile resolver, the central redaction wrapper across the R14 emission-point registry (including
   the 033 legacy projections, spec-seed hook, and 032 inFlight redaction), and the machine-checked call-site
   map.
2. **Store interface + in-repo backend:** land the `planning.store` interface with the default `in-repo
   public` backend (no behavior change), then the `local/synced` (with path validation) and `memory`
   backends with adapter-only routing + id/hash/backend-only logging.
3. **Materialization:** wire the deliver provision-time materialization hook with the commit-boundary
   barrier, backend pinning, freshness check, orphan sweep, and teardown cleanup; generate `.gitignore` from
   visibility.
4. **Init/doctor:** resolve + seed the public-repo-aware default profile/backend via `/sw-init`, record the
   first-run privacy notice + ack, and add the store-reachability + orphan-sweep doctor checks; update
   memory/provider/guardrails/deliver/config docs.

## Decision Log

- **D1.** Per-unit `visibility:` over a profile default (brainstorm K3) — granularity plus a sane repo-wide
  default; the always-tracked-but-redacted INDEX keeps the graph navigable without leaking bodies.
- **D2.** Pluggable `planning.store` with on-demand worktree materialization (brainstorm K4) — delivers
  private+shareable+durable specs without encryption/keys-in-CI; the deliver loop reads worktree files, so
  materialization is sufficient and CI never needs private bodies; the backend is pinned per run.
- **D3.** Encryption-at-rest and private-repo backends are deferred behind the same seam (brainstorm K4).
- **D4.** Memory backend is storage-only and never the source of truth (brainstorm R16; resolves OQ6) — the
  graph holds identity/SoT; for decisions the PRD-015 committed snapshot always runs regardless of
  visibility, so no dual-SoT is introduced; raw-transcript classes are banned and writes are project-scoped.
- **D5.** Fail-closed everywhere (R10, R14, R24) — unknown visibility or unreachable store never leaks and
  never silently breaks delivery; redaction is centralized through one resolver/wrapper with a
  machine-checked call-site map because the security/adversarial panels showed the emission surface grows
  across PRDs (legacy projections, 032 handoff, 035 proposals).
- **D6.** **Public-repo-aware default** (doc-review decision, refining brainstorm OQ5): `/sw-init` defaults a
  **public** origin remote to `all-private` + explicit ack before the first tracked spec commit, and keeps
  `specs-public` for private/absent remotes — closing the leaky-by-default foot-gun three panels rated P0/P1
  while preserving zero-config delivery where it is safe.
- **D7.** Private bodies get a **commit-boundary** barrier (R8) — ignored prefix + post-materialize
  secret-scan + pre-commit/pre-push rejection of the prefix (even `-f`) + CI diff scan + crash sweep — because
  the adversarial/security panels showed a point-in-time porcelain check is bypassable by a later `git add`.
- **D8.** Body freshness is hash-validated at materialize (R9) with a 034-owned store-revision hash the 033
  reconciler reads — closes the adversarial stale-store-body scenario and assigns the cross-module freshness
  contract an owner.
- **D9.** 034 accepts the **032 R13 in-flight-metadata redaction handoff** (R12/R14) — the coherence panel
  found 032 deferred this to 034 while 034 had scoped it out; 034 now owns the `inFlight` branch/run-id
  redaction (writing the signal stays 032's).
- **D10.** 034 `depends:` on **033** (not just 031): the resolver must wrap the 033 reconciler/projection
  output and the freshness contract couples to the reconciler — closes the scope/coherence missing-dependency
  finding.
