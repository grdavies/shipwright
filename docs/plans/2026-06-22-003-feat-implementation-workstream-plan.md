---
title: "feat: phase-flow v2 implementation workstream (worktrees + phase loop + ship gate + compounding)"
type: feat
date: 2026-06-22
origin: docs/brainstorms/2026-06-22-unified-dev-workflow-plugin-requirements.md
status: implemented
completed: 2026-06-23
branch: feat/implementation-workstream
pr: null
---

# feat: phase-flow v2 implementation workstream (worktrees + phase loop + ship gate + compounding)

## Implementation status

| Unit | Status | Notes |
|------|--------|-------|
| U0 | **Done** | `scripts/memory_redact.py` + `memory-redact.sh`; memory write contract + `/pf-memory-sync` chokepoint |
| U1 | **Done** | `/pf-worktree`, `skills/worktree/`, `scripts/worktree.sh` (provision/teardown/ceiling) |
| U2 | **Done** | `skills/phase-state/`, `scripts/phase-state.sh` (per-worktree gitdir state + index) |
| U3 | **Done** | `/pf-start` … `/pf-ready`, `rules/pf-workflow-sequencing.mdc` (spec-union consumers) |
| U4 | **Done** | `/pf-ship` orchestrator (stale-green re-verify, CI budget, never-merge) |
| U5 | **Done** | `/pf-gaps`, `skills/gap-check/` |
| U6 | **Done (policy)** | `skills/parallelism/` — ceiling + recombination documented; no executable migration-preflight script yet |
| U7 | **Done** | `rules/pf-subagent-dispatch.mdc` |
| U8 | **Done** | `/pf-retro`, `skills/retro/` |
| U9 | **Done** | `/pf-compound`, `skills/compound/` |
| U10 | **Done** | `/pf-status`, `skills/living-status/`, `scripts/reconcile-status.sh` (R14: branch `pf/<slug>-*`, `prd:<slug>`, task checkboxes as inputs) |

**Verification:** `bash scripts/test/run-impl-fixtures.sh` — 13/13; plus doc + gate fixture suites green.

**Merge state:** implemented on `feat/implementation-workstream`; **not yet merged** to `main` (no PR open).

**Follow-ups (not blocking merge):** executable shared-migration preflight for U6 (`parallel-preflight.sh` or extend `worktree.sh`).

## Summary

Build the implementation half of phase-flow v2's Phase 1: per-work-item git worktrees with environment scaffolding, the atomic `pf-` phase loop (start → execute → verify → review → commit → PR → watch-CI → stabilize → ready) under a gated `/pf-ship` orchestrator that halts at the human merge gate, plus gap-capture, bounded parallelism, sub-agent dispatch policy, retrospective, compounding into memory, and the git-derived living-status layer. This consumes the shipped foundation (gate, review seam, stabilize/RCA core, memory seam, per-worktree state) and the documentation workstream's frozen PRDs + spec-union resolver.

## Problem Frame

The frozen brainstorm (see origin) commits to uniform worktree isolation on every tier, an atomic phase loop driven by a gated orchestrator that never merges, and a compounding step that makes each unit of work start the next one smarter. The foundation plan shipped the deterministic gate, the stabilize loop, the shared RCA core (stabilize entry), the memory seam, and the per-worktree state *model* — but deferred the phase loop, worktrees, ship orchestrator, retrospective, compounding, and the living-status runtime to this workstream.

phase-flow v1 ships a mature phase loop and `/ship` orchestrator, but they are built on a **per-repo** state file and an explicit "never use worktrees" guardrail — a direct conflict with v2's worktree-isolated, tiered model. So this workstream ports v1's phase commands and orchestrator under `pf-`, re-homes their state from per-repo to per-worktree (the model the foundation already established), adds worktree provisioning/teardown + env scaffolding and bounded parallelism that v1 lacks, and wires the compounding + living-status layer the brainstorm requires.

**Why now:** with the documentation workstream producing frozen PRDs + a task list + a spec-union resolver, the implementation workstream is the second half of the core value path — the doc → implement → ship loop that delivers "better code quicker." Proving it is the precondition for the Phase 2 debugging/feedback workstreams.

---

## Requirements Traceability

Carried from origin (implementation-relevant requirements):

- **Phase loop + orchestrator:** R15 (atomic phase loop under a gated orchestrator that advances on green and halts at the human merge gate; never merges), R16 (review provider + all-checks gate; normalized feedback → bounded stabilize loop drawing on the shared RCA core).
- **Worktrees + parallelism:** R18 (every work item in its own worktree, all tiers; no work in bare main), R19 (worktree isolation covers ports/DB/deps in a per-worktree scaffold), R20 (bounded ~2–4 ceiling; orchestrator reviews cross-branch diffs; prefer rebase; merge pre-flight; never parallelize shared-migration), R21 (safe lifecycle via `git worktree remove` + `prune`, never `rm`; disk-cost aware).
- **Retro + compounding:** R17 (retrospective/learnings capture after ship feeds compounding), R33 (compounding distills each retro/feedback item into memory with relationship edges and promotes durable guardrails to rule-class, human-gated per R42).
- **Living status:** R13 (task checkboxes + living PRD index + append-only completion log), R14 (git is the source of truth; status derived/reconciled, not hand-set).
- **Sub-agents/loops/tokens:** R28 (sub-agents first-class), R29 (loops have hard stops), R37 (heuristic-gated dispatch ~8+ files / parallelizable / throwaway; cheaper models for delegated mechanical work), R30/R31 (tiered token/model spend; structural isolation dominant).
- **Spec consumption:** R12 (phase loop reads the PRD + amendments union — via the documentation workstream's resolver).

Consumed from the shipped foundation: `scripts/check-gate.sh` (gate), `skills/stabilize-loop` + `skills/rca-core` (stabilize entry), the memory seam (`skills/memory` + `providers/recallium.md`) and its human-gated rule-class promotion (R42), and the per-worktree state model the hooks established (R38). Consumed from the documentation workstream (`002`): frozen PRDs + task lists, and the spec-union resolver (U8 there).

Explicitly **not** here: the documentation pipeline itself (R5–R11, `002`); debugging and feedback workstreams (R22–R27, `004`/`005`); `/pf-upstream` (R40).

---

## Key Technical Decisions

- **Port the phase loop and orchestrator; re-home state per-worktree.** v1's `phase-start/execute/verify/commit/pr/ready` and `ship` are ported under `pf-`, preserving their merge-gate discipline and stabilize wiring, but their state moves from the per-repo `.git/phase-flow.json` to the per-worktree gitdir state the foundation established (`.git/worktrees/<name>/phase-flow.json` for linked worktrees). Rationale: v1's logic is proven (the merge gate never merges, the stale-green re-verify, the CI yellow budget), but its per-repo state and "never use worktrees" guardrail are incompatible with v2's parallel worktree model — so the state layer is the surgical change, not the loop logic. (R15, R38)
- **Worktree is the unit of work on every tier.** Even Quick work runs in its own worktree; there is no work in the bare main checkout. Rationale: origin R18 chose uniform isolation over per-change overhead deliberately (no special-case for "trivial" work that proves non-trivial), accepting that disciplined teardown (R21) and the parallel ceiling (R20) carry the cost. (R18)
- **Lean on Cursor's native worktree support; add only the env scaffold + recombination.** Provisioning uses native worktree creation where available; the plugin's value-add is the per-worktree environment scaffold (unique ports, a separate DB/instance where relevant, independent build/deps) and the cross-branch recombination step — not reimplementing worktrees. Rationale: origin Dependencies/Assumptions. (R19, R20)
- **Teardown is safe-by-construction.** Removal is always `git worktree remove` + `git worktree prune`, never `rm`; the command refuses a raw filesystem delete and surfaces disk cost. Rationale: uniform isolation makes teardown load-bearing (R21); a stray `rm` corrupts the worktree registry. (R21)
- **The phase loop reads the spec union, not the bare PRD.** `/pf-execute` and `/pf-gaps` resolve requirements through the documentation workstream's spec-union resolver so superseded/retracted requirements are honored. Rationale: R12 — implementation must see the precedence-aware union, and the parent PRD alone is stale once amended. (R12)
- **Compounding writes through the memory seam with human-gated rule promotion.** `/pf-compound` distills retro/feedback items into typed memories with relationship edges via the foundation memory seam; promotion to deterministically-injected rule-class is human-gated with provenance (the R42 gate the foundation defined). Rationale: each cycle must start the next smarter (R33), but compounding distills attacker-influenceable signals, so an always-on guardrail must not be auto-writable. (R17, R33, R42)
- **Living status is derived from git, never hand-set.** The PRD index status (`not-started` / `in-progress` / `shipped`) and the completion log are reconciled from merged PRs + task checkboxes, with frozen artifacts carrying no status field. Rationale: origin R14 — a hand-maintained status field drifts; deriving it keeps the index an at-a-glance reconciled view. The PR↔PRD link mechanism and the `shipped` predicate over a multi-PR PRD-plus-amendments span are resolved in U10 (see Open Questions). (R13, R14)
- **Sub-agent dispatch is heuristic-gated and tier-aware.** Delegate when work spans ~8+ files or needs heavy/throwaway exploration whose reads shouldn't pollute the orchestrator context, or when subtasks are independently parallelizable; stay inline for small single-file work; run delegated mechanical work on cheaper models. Rationale: origin R37/R30/R31 — structural isolation is the dominant token lever, but per-agent overhead means isolation shouldn't be forced on small tasks. (R28, R29, R37, R30, R31)

---

## High-Level Technical Design

Each work item gets a worktree with its own scaffold and per-worktree state. The phase loop runs sequentially inside a worktree, reading the spec union; the gated orchestrator advances only on a green gate and halts at the human merge gate. After a human merges, retro → compound write to memory, and the living index reconciles from git. Independent items get separate worktrees up to a bounded ceiling.

```mermaid
flowchart TB
  TASKS[(frozen PRD + tasks + union)] --> WT[/pf-worktree: provision + env scaffold]
  WT --> STATE[(per-worktree gitdir state: tier/phase/workstream)]
  WT --> LOOP

  subgraph LOOP[phase loop in worktree]
    START[/pf-start] --> EXEC[/pf-execute reads union] --> GAPS[/pf-gaps]
    GAPS --> VERIFY[/pf-verify] --> REVIEW[/pf-review] --> COMMIT[/pf-commit]
    COMMIT --> PR[/pf-pr] --> WATCH[/pf-watch-ci] --> STAB[/pf-stabilize] --> READY[/pf-ready]
  end

  SHIP[/pf-ship orchestrator] -->|advance on green gate| LOOP
  READY --> GATE{check-gate.sh == green?}
  GATE -->|yes| MERGEGATE[human merge gate: never auto-merge]
  GATE -->|no| STAB
  MERGEGATE -->|human merges| RETRO[/pf-retro] --> COMPOUND[/pf-compound → memory]
  MERGEGATE --> RECONCILE[living index + completion log reconcile from git]

  PAR[bounded ~2-4 parallel worktrees + recombination]:::note -.-> WT
  classDef note opacity:0.5;
```

Foundation components (`check-gate.sh`, stabilize, rca-core, memory seam) and the documentation workstream's union resolver are consumed, not rebuilt. The diagram is authoritative for loop ordering and the merge-gate boundary; per-unit Files sections are authoritative for exact paths.

---

## Implementation Units

Suggested build order: the executable R41 redaction filter (U0) first — it is a foundation-shared predecessor every ingestion edge depends on; then worktree provisioning + per-worktree state wiring (U1–U2) since the loop runs inside them; then the atomic loop + orchestrator (U3–U4); gap-capture (U5); parallelism + dispatch policy (U6–U7); then post-ship retro/compound + living status (U8–U10).

### U0. Executable R41 redaction filter (foundation hardening)

- **Goal:** Build the deterministic, executable secret/PII redaction filter the foundation shipped as docs-only (`001` U5: "executable redaction filter not built"), as the single shared chokepoint every ingestion edge routes through.
- **Requirements:** R41 (foundation follow-up; `001` lists "executable redaction chokepoint" as a non-blocking follow-up).
- **Dependencies:** foundation memory seam + `rules/memory-guardrails.mdc` (the named secret/PII corpus). No other workstream units.
- **Why here:** `003` is the first plan whose units actually execute an ingestion edge (U9 compounding), so its redaction test ("Ingestion runs the redaction chokepoint before persistence") is the first that needs a real filter. Building it once here, in shared foundation code, lets the later ingestion edges — `004` U2 (Sentry) and `005` U1 (feedback intake) — consume one hardened filter rather than each re-originating it.
- **Files:** `skills/memory/SKILL.md` (extend: redaction step in the write contract), a deterministic filter script under the memory seam (e.g. `skills/memory/redact.*`), `skills/memory/CAPABILITIES.md` (note the executable chokepoint is live).
- **Approach:** Implement redaction as a single deterministic filter (not a prompt-only instruction) in the foundation memory seam's write path, scrubbing the named secret/PII corpus from `001` U5 (AWS `AKIA…`, `ghp_…`/PATs, JWTs, `Bearer` headers, PEM keys, emails). Run it before anything is persisted or re-injected. Expose it as the shared chokepoint other workstreams call. Leave format-specific extensions (deploy-log/feedback secret formats, high-entropy fallback, Sentry PII) to the consuming edges (`004` U2, `005` U1), which extend rather than fork the corpus.
- **Patterns to follow:** `001` U5 redaction policy/docs and `rules/memory-guardrails.mdc`; the memory-seam write contract.
- **Test scenarios:**
  - A payload containing each named secret/PII pattern is scrubbed before persistence or re-injection.
  - The filter is deterministic (same input → same redacted output) and runs offline.
  - The memory seam's write path invokes the filter before any persist/re-inject step.
- **Verification:** Every ingestion edge has one shared, executable, tested redaction chokepoint to route through; `001` U5's deferred filter is now live.

### U1. `/pf-worktree` provisioning, env scaffold, and safe teardown

- **Goal:** Provision a per-work-item worktree with a recorded environment scaffold (unique ports, separate DB/instance where relevant, independent build/deps) and tear it down safely.
- **Requirements:** R18, R19, R21.
- **Dependencies:** none (consumes foundation only).
- **Files:** `commands/pf-worktree.md`, `skills/worktree/SKILL.md`, `config/workflow.config.example.json` (extend: scaffold schema — port ranges, DB template, deps strategy), `docs/config.schema.json` (extend).
- **Approach:** Provision via Cursor/native `git worktree add` (lean on native support per origin assumptions). Generate a per-worktree scaffold: allocate a unique port (or port range) from a configured pool, provision a separate DB/instance where the project needs one, and set up independent build/deps. Record the scaffold in the per-worktree state (U2). Teardown uses `git worktree remove` + `git worktree prune` only — never `rm` — releasing the port/DB and surfacing reclaimed disk. Define the scaffold schema in config so projects declare their port/DB/deps strategy.
- **Patterns to follow:** v1 has no worktree command; model command/skill structure on v1 conventions. Origin Dependencies/Assumptions (native worktrees + plugin value-add = scaffold + recombination).
- **Test scenarios:**
  - Provisioning creates a worktree and a scaffold record with a unique port (two worktrees never collide on the same port).
  - Teardown uses `git worktree remove` + `prune`; a raw `rm` path is refused.
  - Scaffold schema validates against the config schema; a project declaring a DB template gets a separate instance.
  - `Test expectation:` DB/instance provisioning verified structurally where a live DB isn't available in CI.
- **Verification:** Worktrees provision with isolated ports/DB/deps and tear down without leaking the worktree registry or disk.

### U2. Per-worktree phase-state wiring

- **Goal:** Re-home the phase loop's state from v1's per-repo `.git/phase-flow.json` to the per-worktree gitdir state model, tracking the worktree's tier, phase, and workstream.
- **Requirements:** R38, R18.
- **Dependencies:** U1.
- **Files:** `skills/phase-state/SKILL.md` (state read/write contract), `commands/pf-start.md` (writes initial state — see U3).
- **Approach:** Adopt the foundation's per-worktree state location (linked worktrees: `.git/worktrees/<name>/phase-flow.json`). Carry v1's fields (`parentBranch`, `currentBranch`, `phaseSlug`, `branchPrefix`, `startedAt`, `lastCommand`, `phaseStatus`, `iteration`) and add `tier` and `workstream`. The repo-level index is derived at read-time (aggregated via `git worktree list`), never a concurrently written shared file — preserving "no global mutable state." Phase commands resolve their parent/phase context from this per-worktree state rather than a single repo-global file.
- **Patterns to follow:** v1 `rules/workflow-phase-sequencing.mdc` (state field list) and the foundation's per-worktree state model (R38) as established by the hooks.
- **Test scenarios:**
  - Two simulated worktrees maintain independent state; neither overwrites the other.
  - The derived repo-level index reflects both worktrees without a shared-file write.
  - State carries the new `tier`/`workstream` fields plus v1's fields.
- **Verification:** Concurrent worktrees never collide on state; the aggregating index is read-time-derived.

### U3. Port the atomic phase loop under `pf-`

- **Goal:** Port `/pf-start`, `/pf-execute`, `/pf-verify`, `/pf-commit`, `/pf-pr`, `/pf-ready` from v1, re-homed to per-worktree state and reading the spec union.
- **Requirements:** R15, R12, R16 (review/gate consumption).
- **Dependencies:** U2, plus documentation workstream union resolver (`002` U8) and foundation gate/stabilize.
- **Files:** `commands/pf-start.md`, `commands/pf-execute.md`, `commands/pf-verify.md`, `commands/pf-commit.md`, `commands/pf-pr.md`, `commands/pf-ready.md`, `rules/pf-workflow-sequencing.mdc`.
- **Approach:** Port each v1 command's contract intact (branch creation from current branch within the worktree; one phase-sized slice per execute; scoped verify; phase-only commit excluding state/markers; PR base resolution from open-PR base then `parentBranch`; `/pf-ready` as a terminal report that runs `check-gate.sh` and never merges). Two surgical changes: (a) state reads/writes go through U2's per-worktree state, and (b) `/pf-execute` and the diff base resolve requirements through the spec-union resolver, not the bare PRD. Preserve the merge-gate discipline: `/pf-ready` reports `merge-ready` only on gate exit 0 / `verdict == green`.
- **Patterns to follow:** v1 `commands/phase-{start,execute,verify,commit,pr,ready}.md` and `rules/workflow-phase-sequencing.mdc`.
- **Test scenarios:**
  - `/pf-start` branches from the current branch inside the worktree and records parent context in per-worktree state.
  - `/pf-execute` reads the spec union (amended requirements are honored, not just the parent PRD).
  - `/pf-commit` excludes the per-worktree state file and memory-sync markers.
  - `/pf-pr` resolves base from an open PR then `parentBranch`; never guesses from `main`/merge-base.
  - `/pf-ready` reports `merge-ready` only on a green gate and never merges. Covers origin Success Criteria (gate correctness).
- **Verification:** The atomic loop runs in a worktree against the spec union, with v1's merge-gate guarantees intact.

### U4. `/pf-ship` gated orchestrator

- **Goal:** Port v1's `/ship` chain under `pf-`, driving the phase loop on green, bounding the CI/review wait, halting on any blocker, and stopping at the human merge gate — never merging.
- **Requirements:** R15, R16.
- **Dependencies:** U3, foundation stabilize + gate + review seam.
- **Files:** `commands/pf-ship.md`.
- **Approach:** Port the v1 ship chain (execute → verify → review → gap-check → commit → PR → watch-CI → stabilize → ready[PAUSE]), preserving the resume-from-`lastCommand` logic (now per-worktree), the stale-green re-verify, the CI yellow budget, and the CodeRabbit/review-seam re-arm after a stabilize push. The gate is the foundation's `check-gate.sh`; the review feedback is the foundation review seam; stabilize is the foundation loop drawing on the shared RCA core. The orchestrator advances only on a green gate, halts loudly on any blocker or stabilize hard stop, and ends at the merge gate ("ready to merge — your call") without merging. Flags mirror v1 (`--fast` skip gap-check, `--from <step>`, `--dry-run`).
- **Patterns to follow:** v1 `commands/ship.md` (chain, yellow budget, stale-green re-verify, never-merge contract).
- **Test scenarios:**
  - The chain advances step-by-step only on green and persists per-worktree `lastCommand`/`phaseStatus`.
  - A blocker (red/blocked gate, stabilize hard stop, exhausted yellow budget) halts with an actionable message.
  - At a green gate the orchestrator stops at the merge gate and does not merge. Covers origin Success Criteria.
  - `--fast` skips gap-check; `--from <step>` resumes mid-chain.
- **Verification:** `/pf-ship` drives the loop to merge-ready or halts safely, never merging.

### U5. `/pf-gaps` gap-capture

- **Goal:** Port the gap-check skill — compare a phase's diff against its planned tasks (resolved from the spec union), close in-scope gaps with bounded closers, re-verify, and report.
- **Requirements:** R16, R27 (in-scope gap capture overlaps feedback intake), R12.
- **Dependencies:** U3.
- **Files:** `commands/pf-gaps.md`, `skills/gap-check/SKILL.md`.
- **Approach:** Port v1 `gap-check` + `phase-gaps`: a read-only sub-agent maps each planned task (from the U8 spec union of `002`, plus per-worktree `phaseSlug`) to `done`/`partial`/`missing` against `git diff "$PARENT"...HEAD` where `PARENT` is the per-worktree `parentBranch`; bounded closer sub-agents fix in-scope gaps; re-map once for residuals; escalate out-of-scope. Default-on in `/pf-ship` (skipped with `--fast`), standalone via `/pf-gaps --report-only`. Out-of-scope gaps are routed toward the feedback workstream's gap-capture (`005`) rather than silently absorbed.
- **Patterns to follow:** v1 `skills/gap-check/SKILL.md`, `commands/phase-gaps.md`.
- **Test scenarios:**
  - Read-only mapping runs before any closer edits; `--report-only` never mutates.
  - The diff base is the per-worktree `parentBranch`; planned items come from the spec union.
  - A bounded closer fixes an in-scope gap; residuals re-map once then escalate.
  - Out-of-scope work is escalated (toward feedback gap-capture), never silently absorbed.
- **Verification:** In-scope gaps close and verify; scope creep is escalated, not absorbed.

### U6. Bounded parallelism and recombination

- **Goal:** Bound active parallel worktrees to a practical ceiling and provide a cross-branch recombination/orchestration step beyond it.
- **Requirements:** R20.
- **Dependencies:** U1, U4.
- **Files:** `skills/parallelism/SKILL.md`, `commands/pf-worktree.md` (extend: list/ceiling), `rules/pf-workflow-sequencing.mdc` (extend).
- **Approach:** Enforce a configurable ceiling (~2–4) on active worktrees; beyond it, a dedicated orchestrator reviews cross-branch diffs before dispatch. Prefer rebase for linear history; run a merge pre-flight before dispatching long-running parallel agents; refuse to parallelize shared-migration or tightly-coupled work (flagged by overlapping migration paths / shared files). Recombination confines conflicts to the orchestration step.
- **Patterns to follow:** origin R20 + the 2026 worktree-parallelism research captured in the origin Sources.
- **Test scenarios:**
  - Provisioning beyond the ceiling triggers the recombination/review path rather than unbounded fan-out.
  - A merge pre-flight detecting shared-migration overlap refuses parallel dispatch.
  - Rebase is preferred for linear history in the recombination step.
- **Verification:** Parallel streams proceed within the ceiling without cross-stream collisions; risky overlaps are serialized. Covers origin Success Criteria (parallel throughput).

### U7. Sub-agent dispatch policy

- **Goal:** A documented, heuristic-gated dispatch policy that delegates large/parallel/throwaway work to sub-agents on cheaper models and stays inline for small work, with hard-stopped loops.
- **Requirements:** R28, R29, R37, R30, R31.
- **Dependencies:** none (a policy rule consumed by the loop + panel).
- **Files:** `rules/pf-subagent-dispatch.mdc`, `skills/parallelism/SKILL.md` (extend).
- **Approach:** Encode the heuristic: delegate when work spans ~8+ files or needs heavy/throwaway exploration whose reads would bloat the orchestrator context, or when subtasks are independently parallelizable; stay inline for small single-file low-context work. Delegated mechanical work runs on cheaper models (R30); reasoning-heavy work keeps full fidelity. All loops (ship, stabilize, panel, gap-closers) carry hard stops — max iterations, no-progress detection, circuit breaker (R29). This is the structural token lever (R31), with caveman as an output-only add-on on low-reasoning steps.
- **Patterns to follow:** the foundation's stabilize loop hard-stops; origin R37/R30/R31; Recallium memory #2002 (token strategy — context isolation is the dominant lever).
- **Test scenarios:**
  - The rule names concrete thresholds (file count, parallelizability, throwaway) for delegate-vs-inline.
  - Delegated mechanical work is assigned a cheaper model; reasoning-heavy work is not.
  - Every named loop has a documented hard stop.
  - `Test expectation: policy/doc unit — structural verification of the rule's contract.`
- **Verification:** The dispatch policy is unambiguous at the call site and every loop is bounded.

### U8. `/pf-retro` retrospective

- **Goal:** Run a retrospective after shipping a phase that captures what went well/painful and surfaces durable learnings for compounding.
- **Requirements:** R17.
- **Dependencies:** U4.
- **Files:** `commands/pf-retro.md`, `skills/retro/SKILL.md`.
- **Approach:** Port v1 `retro`: review recent commits / the shipped phase, identify what went well, what was painful, what to change, and check current behavior against memory/doctrine. Output distilled learning candidates for `/pf-compound` (U9). Report-only by default; no doctrine edits without approval; never put secrets/transcripts into the output.
- **Patterns to follow:** v1 `commands/retro.md`.
- **Test scenarios:**
  - The retro reviews the shipped phase and produces distilled learning candidates.
  - It is report-only; no memory/doctrine is written without explicit direction.
  - No secrets/raw transcripts appear in the output.
- **Verification:** A retro yields learning candidates ready for compounding without auto-mutating doctrine.

### U9. `/pf-compound` compounding into memory

- **Goal:** Distill retrospective/feedback items into typed durable memories with relationship edges, and promote durable behavioral guardrails to rule-class — human-gated with provenance.
- **Requirements:** R33, R17, R42.
- **Dependencies:** U8, U0 (executable redaction filter), foundation memory seam.
- **Files:** `commands/pf-compound.md`, `skills/compound/SKILL.md`, `skills/memory/SKILL.md` (consume), `commands/pf-memory-audit.md` (consume the allowlist).
- **Approach:** Adapt compound-engineering's compounding pattern to write through the foundation memory seam (not a separate `docs/solutions/` layer — memory is the single source of truth per R32). Distill each retro/feedback item into the right canonical category (decision/learning/debug/design) with relationship edges (`supersedes`, `relates-to`, `file-linked`) and stable tags. Promotion to deterministically-injected rule-class is human-gated: it requires explicit confirmation and carries provenance metadata (source, distillation origin), landing on the repo-side allowlist that `/pf-memory-audit` maintains (the R42 gate the foundation defined). Search-before-store; redact secrets/PII at the ingestion edge (the U0 R41 chokepoint). Untrusted feedback content arrives inside `005` U1's `untrusted_payload` envelope; honor that representation contract — distill it as data and preserve the envelope boundary so injection markers in a feedback item cannot steer compounding or the auto-injected rule-class.
- **Patterns to follow:** compound-engineering `ce-compound` (distill → durable artifact, overlap-aware update) adapted to memory; foundation `rules/memory-guardrails.mdc` + `commands/pf-memory-audit.md` for the promotion gate.
- **Test scenarios:**
  - A retro item is distilled into a typed memory with relationship edges and tags (not a raw dump).
  - A guardrail candidate cannot reach rule-class without the human-confirm step; a promoted rule carries provenance and lands on the allowlist. Covers R42.
  - Ingestion runs the redaction chokepoint before persistence.
  - Search-before-store updates a near-duplicate rather than adding a second memory.
- **Verification:** Each cycle adds durable, relationship-linked memories; rule-class promotion stays human-controlled and provenance-tagged. Covers origin Success Criteria (compounding).

### U10. Git-derived living-status layer

- **Goal:** Maintain the living PRD index and append-only completion log with status derived/reconciled from git — never hand-set — over the documentation workstream's `INDEX.md`/`COMPLETION-LOG.md`.
- **Requirements:** R13, R14.
- **Dependencies:** documentation workstream (`002` U1/U9 seed the files), U4.
- **Files:** `commands/pf-status.md`, `skills/living-status/SKILL.md`, `prds/INDEX.md` (reconcile), `prds/COMPLETION-LOG.md` (append), `prds/GAP-BACKLOG.md` (surface, read-only).
- **Approach:** Define and implement the status-derivation function the origin flags as asserted-but-undefined: derive each PRD's status (`not-started`/`in-progress`/`shipped`) from git facts — merged PRs linked to the PRD and task-checkbox completion — and reconcile `INDEX.md` as an at-a-glance view rather than a hand-maintained field. Append to `COMPLETION-LOG.md` on each shipped phase. Surface `prds/GAP-BACKLOG.md` (the committed, hand-appended trivial-gap backlog written by `005` U3) in the status view as open captured gaps — read-only here; unlike the index/log it is hand-maintained, not git-derived, so living status reflects it but never rewrites it. Resolve the PR↔PRD link mechanism, the `shipped` predicate over a PRD-plus-amendments spanning many PRs, and whether task checkboxes are derivation inputs or outputs (see Open Questions). Frozen artifacts stay untouched and carry no status field.
- **Patterns to follow:** v1's cross-repo registry note (non-authoritative; `.git` wins) for the derived-view principle; origin R14.
- **Test scenarios:**
  - PRD status is derived from merged PRs + task checkboxes, not a hand-set field; re-running reconciles to the same value.
  - A `shipped` PRD spanning multiple PRs is marked shipped only when its `shipped` predicate is satisfied.
  - The completion log is append-only (a shipped phase adds a line; nothing is rewritten).
  - Frozen artifacts are never modified by status updates.
- **Verification:** The index reflects git reality without drift; the completion log is append-only; frozen files are untouched.

---

## Open Questions

- **R14 status-derivation specifics (shared with `002`).** The origin flags R14's status function as asserted-but-undefined: the PR↔PRD link mechanism (issue convention? branch/PR naming? a manifest?), the `shipped` predicate over a PRD-plus-amendments span across many PRs, and whether task checkboxes are derivation *inputs* or *outputs* (if hand-edited they reintroduce the drift R14 eliminates). U10 must resolve these; the decision is coupled to the documentation workstream's GitHub-tracking-issue fork (`002` Open Questions). Resolve jointly before U10 hard-codes a link mechanism.
- **Env-scaffold breadth.** How far to go on per-worktree DB/instance provisioning (full isolated DB vs schema namespace vs shared-with-prefix) depends on the consuming project. U1 ships a schema-configurable scaffold; the default depth is a project choice, not fixed here.

---

## Scope Boundaries

### Deferred to sibling/later plans

- The documentation pipeline (triage, brainstorm, PRD, persona panel, freeze, amendments, spec-union resolver) — documentation workstream (`002`). This plan consumes its frozen output and resolver.
- Debugging and feedback workstreams (R22–R27) — Phase 2 (`004`, `005`). Gap-capture (U5) escalates out-of-scope work toward feedback's intake but does not implement it.
- `/pf-upstream` provenance-diff/refresh (R40).

### Outside this product's identity (from origin)

- A from-scratch reinvention that discards v1's proven gate/stabilize loop — those are consumed from the foundation, not rebuilt.
- A composition that depends on compound-engineering at runtime — the compounding pattern is vendored slim.

---

## Risks & Dependencies

- **State re-homing fidelity.** Moving v1's per-repo state to per-worktree touches every phase command's read/write. A partial port could leave a command reading the wrong state and corrupting parallel runs. *Mitigation:* U2 lands the state contract first; U3 commands all route through it; the two-worktree isolation test (U2) guards regressions.
- **Worktree resource leaks.** Ports/DBs/disk not released on teardown accumulate. *Mitigation:* U1's safe-teardown (`remove` + `prune`, never `rm`) releases scaffold resources and surfaces disk; the no-`rm` test guards it.
- **Cross-plan dependency on the spec-union resolver.** U3/U5 consume `002`'s resolver; if its interface slips, the loop reads stale specs. *Mitigation:* treat `002` U8's interface as a published contract; do not start U3 until it is frozen.
- **Compounding poisoning.** Distilling attacker-influenceable signals into auto-injected rules is a known threat. *Mitigation:* U9 routes promotion through the foundation's human-gated R42 allowlist + provenance and the R41 redaction chokepoint.
- **Living-status under-specification.** R14's derivation is undefined in the origin; building U10 on a guessed link mechanism risks rework. *Mitigation:* resolve the Open Question with `002` before U10 hard-codes anything; default to git + index as the status source if the GitHub-issue convention is dropped.

---

## Sources & Research

Internal (vendored / ported — recorded in `PROVENANCE.md` per R40):

- phase-flow v1 (`cursor-phase-flow`): `commands/phase-{start,execute,verify,commit,pr,ready}.md`, `commands/ship.md`, `commands/phase-gaps.md` + `skills/gap-check/SKILL.md`, `commands/retro.md`, `rules/workflow-phase-sequencing.mdc`, the `stateFile` field model.
- compound-engineering: `ce-compound` compounding pattern (distill → durable artifact, overlap-aware update, human-gated discoverability) — adapted to write through the memory seam, not copied.

Consumed (already shipped, PR #1): `scripts/check-gate.sh`, `skills/stabilize-loop`, `skills/rca-core` (stabilize entry), `skills/memory` + `providers/recallium.md`, `rules/memory-guardrails.mdc`, `commands/pf-memory-audit.md`, the per-worktree state model.

Origin requirements: `docs/brainstorms/2026-06-22-unified-dev-workflow-plugin-requirements.md` (frozen). Foundation: `docs/plans/2026-06-22-001-feat-plugin-foundation-infrastructure-plan.md`. Documentation workstream sibling: `docs/plans/2026-06-22-002-feat-documentation-workstream-plan.md`. Prior decisions: Recallium memories #2003 (worktree/triage shape), #2002 (token strategy), #2004 (cross-cutting flows).