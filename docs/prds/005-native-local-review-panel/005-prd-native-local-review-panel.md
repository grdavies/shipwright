---
date: 2026-06-24
topic: native-local-review-panel
source_brainstorm: docs/brainstorms/2026-06-24-native-local-review-panel-requirements.md
frozen: true
frozen_at: 2026-06-24
---

# PRD 005: Native local review panel (phase-1 default-on)

## Overview

Shipwright's `/sw-review` is specified as a two-phase flow (phase 1 local multi-agent review → phase 2
external provider), but phase 1 never fires in practice: it is absent from live config, no resolver injects
the schema defaults at runtime, and the command framing entangles it with the external-provider opt-out. This
PRD replaces the deferred `native` local-review adapter with a real **Shipwright-native phase-1 panel** — a
fixed always-on core plus deterministic signal-gated specialists — that runs **by default on every
`/sw-review` and `/sw-ship`, decoupled from `review.provider`**, autonomously applies eligible fixes (including
verified P1 behind a re-verify gate, subject to the apply-policy in R68), and surfaces an early advisory
work-vs-asked signal. The goal is to catch and resolve issues locally before external review systems run,
minimizing their load and turnaround.

**Input:** [docs/brainstorms/2026-06-24-native-local-review-panel-requirements.md](../../brainstorms/2026-06-24-native-local-review-panel-requirements.md) (Full tier).

**Relationship to prior PRDs.** This PRD owns phase-1 (local) review behavior only. It does **not** change
phase-2 external-provider behavior or the safe `review.provider: "none"` default established by PRD 002/003;
PRD 003 (PR-Agent) explicitly lists phase-1 local changes as a non-goal, so this PRD fills that gap without
disturbing the external surface. It does not change `/sw-deliver` (PRD 004). As a non-binding integration
note, the native panel runs inside each `/sw-ship` that `/sw-deliver` dispatches; its non-interactive behavior
under PRD 004's phase-mode `/sw-ship` contract (PRD 004 R48) is pinned here by R67 so autonomous apply never
lands unattended code without the phase-mode block path. No `/sw-deliver` changes are in scope.

## Goals

1. **Phase 1 actually fires** — running `/sw-review` or `/sw-ship` on a default-config repo visibly spawns the
   native panel, including when `review.provider: "none"`.
2. **Deterministic, explainable roster** — a fixed always-on core plus signal-gated specialists, where
   identical inputs always select the identical panel and every selection reason is announced. (Roster
   selection is deterministic; LLM-generated finding content and applied mutations are not — see R65/R64.)
3. **Safe autonomous remediation** — the panel auto-applies eligible findings behind hard, deterministic rails
   (P0/security never auto-applied; P1 only after independent validation and only in interactive mode;
   mandatory re-verify with per-fix revert) and leaves the tree green.
4. **Early completeness signal without authority creep** — an advisory `scope-fidelity` reviewer surfaces
   silent defers/stubs/omissions before external review, while `gap-check` remains the sole binding
   completeness verdict at `/sw-ship`.
5. **Measurably lighter external review** — eligible issues are resolved locally first, reducing phase-2
   actionable findings on comparable changes, tracked against a defined baseline and a contested-apply rate
   (R74).
6. **No new heavy dependencies** — the panel runs entirely on Shipwright-dispatched subagents and the session
   model; optional UI/UX enrichment degrades gracefully to a native checklist when absent.
7. **Green everywhere** — all gate/doc/impl/code-review fixtures stay green after `core/` → `dist/`
   propagation.

## Non-Goals

- Changing phase-2 external-provider behavior (CodeRabbit / PR-Agent) or its safe `review.provider: "none"`
  default from PRD 002/003.
- Retiring or weakening `gap-check`'s authoritative ownership of requirements completeness.
- Reintroducing `previous-comments` or any PR-thread / PR-history review into phase 1.
- Making the native panel a CI/merge oracle — `check-gate.sh` stays the sole authority.
- Auto-applying P0 or security-sensitive fixes at any severity.
- Suppressing or down-weighting external (phase-2) findings on panel-touched lines (R71).
- Migrating repos that explicitly set `review.local.provider: "ce-code-review"` (they keep that adapter).
- Adding a code-simplification reviewer to the panel — simplification is owned by the `/sw-simplify`
  ship-chain step.
- Hard-depending on `ui-ux-pro-max` or any external design skill (UI/UX reviewer is native-first; external
  enrichment is opt-in only).
- Adopting `ui-ux-pro-max`'s React-Native-specific orientation as the panel default — the native checklist is
  stack-neutral across web + cross-platform JS (and native-mobile globs per R73).
- Hybrid native-shell-with-pluggable-engine architecture (keep `ce-code-review` selectable only).
- Per-repo latency budgeting / adaptive auto-skip-low-risk heuristics (a `--fast` / `--skip-local` escape
  hatch is in scope; adaptive budgeting is not).
- Stack-specific specialists beyond the listed roster (e.g. frontend-races, iOS) — add later on evidence.
- Changing `/sw-deliver` (PRD 004) — the phase-mode interaction (R67) constrains this panel, not `/sw-deliver`.

## Requirements

Requirements `R1`–`R46` carry forward from the brainstorm (verbatim intent, stable R-IDs). `R47`–`R53` resolve
brainstorm Open Questions OQ1–OQ7; `R54` pins the `--fast` / `--skip-local` escape hatch the brainstorm scoped
in (Deferred section, DL-19). `R55`–`R75` are review-panel hardening from the `/sw-doc-review` persona panel.
Each requirement is testable; where a brainstorm requirement is tightened, the amending R-ID is named inline.

### Native engine & contract

- **R1** A native local-review adapter MUST exist at `core/providers/code-review/native.md` and conform to the
  normalized result contract in `core/providers/code-review/CAPABILITIES.md` (`status`, `verdict`, `findings[]`
  with `severity` / `file` / `line` / `title` / `suggested_fix` / `confidence` / `requires_verification`).
- **R2** The native adapter MUST NOT depend on the compound-engineering `ce-code-review` skill or any external
  plugin; it runs entirely on Shipwright-dispatched subagents and the session model.
- **R3** `ce-code-review` MUST remain a selectable `review.local.provider` value (no regression for repos that
  set it explicitly), but `native` becomes the schema default.
- **R4** The native adapter MUST be report-and-apply within Shipwright's own apply machinery (the pf edit
  machinery); reviewer subagents are read-only with respect to the repo and return structured findings only.
- **R5** Normalized output MUST preserve fail-closed semantics: `skipped` / `failed` / `degraded` without a
  `findings` array is never deserialized as "0 findings → pass" (liveness attestation pinned by R66).

### Roster & selection (deterministic)

- **R6** Every native review MUST spawn the always-on core panel: `correctness`, `maintainability`,
  `scope-fidelity`, `testing`, `security`.
- **R7** Signal-gated specialists (`performance`, `api-contract`, `data-migration`, `reliability`,
  `adversarial`) MUST be selected by deterministic, auditable signals (file globs, risk keywords, structural
  markers, changed-line thresholds) such that identical inputs always select the identical panel.
- **R8** `data-migration` MUST fire only when the diff includes a migration / schema artifact (migration
  paths, schema dumps, backfill scripts); `adversarial` MUST fire on ≥50 changed executable code lines OR on
  auth / payments / data-mutation / external-API changes (executable-line counting pinned by R60).
- **R9** `previous-comments` MUST NOT be part of the phase-1 panel (PR-only; out of scope for the uncommitted
  delta).
- **R10** Each selected specialist's selection signal MUST be reported in the panel announce (what fired and
  why), so the panel is explainable.

### scope-fidelity reviewer

- **R11** The `scope-fidelity` reviewer MUST flag work that appears silently deferred, stubbed, marker-commented
  as incomplete (including deferral markers in changed comments), or omitted relative to the stated task /
  intent for the change.
- **R12** `scope-fidelity` output MUST be labeled advisory and MUST NOT emit a binding completeness verdict;
  `gap-check` remains the authoritative completeness authority at `/sw-ship`.
- **R13** The contract documents (`CAPABILITIES.md`, `code-review-automation.mdc`) MUST be updated to permit an
  advisory local completeness signal while preserving gap-check's exclusive ownership of the binding verdict.

### Default, gating & framing fix

- **R14** Native phase 1 MUST be on by default for all repos and MUST run independently of `review.provider` —
  including when `review.provider: "none"`.
- **R15** Phase 1 MUST be disabled only by `review.local.enabled: false` or `review.local.provider: "none"`; no
  other config value (notably `review.provider`) may suppress it.
- **R16** When `review.local` is absent from `workflow.config.json`, the resolved behavior MUST equal the schema
  defaults (`enabled: true`, `provider: "native"`) — an absent block MUST NOT be interpreted as "off"
  (resolution mechanism pinned by R61).
- **R17** `core/commands/sw-review.md` MUST be reworded so the opening framing no longer implies review is off
  by default; it MUST state that phase 1 (local) is default-on and independent of the phase-2 external-provider
  opt-out.
- **R18** `core/commands/sw-ship.md` MUST reflect that the native phase-1 panel runs in-chain by default and
  describe its halt / surface semantics (run-report contract pinned by R69).

### Apply policy & safety rails

- **R19** The panel MUST auto-apply eligible findings at severities P1, P2, P3 when all rails pass: concrete
  `suggested_fix`, in-repo non-symlink path (R57), bounded fix size (R60), non-security-sensitive target
  (R55/R56), and apply-policy `auto` (R68); subject to the P1 validation gate (R22) and phase-mode precedence
  (R67).
- **R20** P0 findings MUST never be auto-applied — always surfaced for human triage.
- **R21** Security-sensitive targets (auth / authz, secrets, credentials, CI / workflow config) MUST never be
  auto-applied at any severity — surfaced only (deny-list pinned by R48 and expanded by R55/R56).
- **R22** P1 auto-apply MUST be gated by an independent validation pass (a fresh second-opinion subagent
  confirming the finding) before the fix is applied; unvalidated P1 findings are surfaced, not applied
  (independence contract pinned by R62; phase-mode override by R67).
- **R23** After any auto-apply, the panel MUST run a bounded `/sw-verify`; any fix whose verification fails MUST
  be reverted and re-surfaced as a finding. The tree MUST never be left failing by the panel (per-fix
  checkpoint / dirty-tree handling pinned by R64).
- **R24** A circuit-breaker MUST stop the apply / re-verify loop after a bounded number of attempts and escalate
  per `rules/sw-subagent-dispatch.mdc` (precise failure-signature + attempt cap pinned by R65).
- **R25** Auto-applied fixes MUST remain in the working tree for downstream phase-2 / external review; any later
  external finding on a panel-touched line MUST be annotated (e.g. `contests applied fix`) additively rather
  than silently re-litigated — and never suppressed or down-weighted (R71).

### Gate, model tiering & integration

- **R26** The local severity gate MUST stay additive: surface-only default (`haltOn: []`), opt-in halting on
  validated P0 / P1; `check-gate.sh` remains the sole CI / merge oracle.
- **R27** High-stakes reviewers (`correctness`, `security`, `adversarial`) MUST inherit the session / deep tier;
  remaining reviewers run mid-tier. No semantic tier name appears in any agent frontmatter (R9 floor).
- **R28** Reviewer dispatch MUST respect the harness's active-subagent limit with bounded parallelism and treat
  capacity errors as backpressure (retry), not reviewer failure (dispatch-rule clause added by R61).

### Memory, redaction & distribution

- **R29** Memory reads (known false positives, file learnings) and writes MUST route through the existing
  preflight / redaction chokepoint (`scripts/memory-redact.sh`); raw reviewer output MUST never be persisted to
  memory, and any finding-derived write (file learnings, known-FP records quoting diff text) MUST pass through
  redaction before persist.
- **R30** Native panel run artifacts MUST be scrubbed after parsing (no cleartext diff / evidence left in temp
  dirs beyond the run), including the persisted run report (R69), consistent with the existing persist-edge
  redaction.
- **R31** All new / changed artifacts MUST land in `core/` and propagate to `dist/cursor/` and
  `dist/claude-code/` via the build / sync pipeline, with `scripts/test/` fixtures and runners updated and
  green.
- **R32** Schema updates MUST set `review.local.provider` default to `"native"` in both `.sw/config.schema.json`
  and `core/sw-reference/config.schema.json`, and the example configs MUST show a populated `review.local`
  block.

### Testing (core)

- **R33** Fixtures MUST prove deterministic panel selection: given fixed diffs, the selected roster (core +
  fired specialists) is exactly reproducible (deterministic selector pinned by R61).
- **R34** Fixtures MUST cover the apply rails: P0 surfaced-not-applied, security-sensitive target
  surfaced-not-applied, P1 applied-only-when-validated, revert-on-failed-verify, and circuit-breaker trip.
- **R35** Regression fixtures MUST prove phase 1 fires when `review.provider: "none"` and when `review.local`
  is absent (schema-default path), and is skipped only on explicit local opt-out.

### Additional optional reviewers (DK8)

- **R36** A `ui-ux` reviewer MUST exist as a signal-gated specialist, fired by deterministic frontend / UI
  signals (R51/R73), surfacing accessibility / contrast, touch / interaction states, layout / responsive
  behavior, and composition / boolean-prop hygiene (native checklist pinned by R72).
- **R37** The `ui-ux` reviewer MUST carry a self-contained native checklist and MUST NOT hard-depend on any
  external design skill. It MAY enrich via `ui-ux-pro-max` or a fetched Vercel Web Interface Guidelines only
  when enrichment is opted in (availability checked only under R52/R73), and MUST degrade gracefully
  (native-only) when they are absent.
- **R38** A `type-design` reviewer MUST exist as a signal-gated specialist, fired when the diff adds or changes
  type definitions, interfaces, or data models, flagging weak invariants, leaky encapsulation, and
  unenforced / unexpressed constraints.
- **R39** A `comment-accuracy` reviewer MUST exist as a signal-gated specialist, fired when the diff changes
  comments, docstrings, or doc files, flagging comment rot and misleading / outdated documentation relative to
  the code it describes.
- **R40** An `ai-native` reviewer MUST exist as a signal-gated specialist, fired on prompt / agent / AI-surface
  changes (including any path where untrusted input reaches an LLM), flagging prompt-injection / trust-boundary
  risks and AI-generated-code readability / slop.
- **R41** Silent-failure detection MUST be folded into the `reliability` specialist's prompt (not a separate
  persona), and the panel MUST NOT add a code-simplification reviewer — simplification remains the
  `/sw-simplify` ship-chain step.
- **R42** All four new specialists MUST be selected by deterministic, auditable signals (same inputs → same
  panel) consistent with R7, and their selection reasons MUST be reported per R10 (signal sets pinned by
  R51/R73).

### Cross-cutting calibration & apply discipline (DK9)

- **R43** Every reviewer prompt MUST embed the review-traps calibration catalog — unverified-absence,
  regression-without-baseline-read, guard widening / narrowing mirror-bug, and projection-leak on hide / filter
  changes — so each finding is evidence-verified before emission.
- **R44** The apply / validation rails MUST encode receiving-review discipline: verify each finding against the
  codebase before applying, apply a YAGNI check, and skip / surface (never auto-apply) findings that are wrong
  for this codebase or unverified. This composes with the R19–R24 rails and the deterministic gates R55–R65.

### Testing (additional reviewers)

- **R45** Fixtures MUST prove deterministic firing for each new specialist: `ui-ux` / `type-design` /
  `comment-accuracy` / `ai-native` fire on their respective seeded signal diffs and stay silent on unrelated
  diffs.
- **R46** A fixture MUST prove the `ui-ux` reviewer produces an accessibility / interaction finding from the
  native checklist alone (against the R72 baseline), with no external design skill installed.

### PRD additions — pinned signals & policies (resolve brainstorm Open Questions)

- **R47** The deterministic selection signals for all gated specialists MUST be specified in a single canonical
  table in `core/providers/code-review/native.md` (the Technical Requirements "Selection signal table" is the
  authoritative source), covering file globs, risk keywords, structural markers, and the `adversarial`
  changed-line threshold, so selection is auditable and reproducible (resolves OQ1; satisfies R7 / R8 / R42).
- **R48** The security-sensitive deny-list (R21) MUST be a concrete, auditable union of path globs and content
  markers pinned in `native.md` and exercised by per-class fixtures; the base set is path globs `**/auth/**`,
  `**/authz/**`, `**/*secret*`, `**/*credential*`, `**/.env*`, `**/.github/workflows/**`, CI / workflow config,
  and content markers (case-insensitive) `password`, `secret`, `token`, `apikey` / `api_key`, `private_key`,
  `authorization`, `set-cookie`. The set is expanded by R55 and matching semantics pinned by R55 (resolves OQ2).
- **R49** The independent P1 validation wave (R22) MUST run a fresh-context second-opinion subagent at the
  deep / session tier; a non-confirming or capacity-degraded validation surfaces the P1 rather than applying
  it (validator creation + independence contract pinned by R62) (resolves OQ3).
- **R50** The `scope-fidelity` advisory signal MUST be written into the native panel run report and forwarded
  as advisory input to `/sw-ship`'s `gap-check` step (wiring pinned by R75) but MUST NOT be persisted to
  durable memory and MUST NOT alter gap-check's binding verdict ownership (resolves OQ4; satisfies R12).
- **R51** The four new specialists MUST fire on these pinned signal sets (same-inputs → same-panel, R42):
  `ui-ux` per R73; `type-design` on changes to type / interface / model declarations (`.d.ts`, `interface` /
  `type` / `class` / `struct` / `enum` / schema-model markers in the diff); `comment-accuracy` on changed
  comment / docstring lines or `*.md` / `*.mdx` doc files; `ai-native` on prompt / agent / AI-surface paths per
  R53. Each fired signal is announced per R10 (resolves OQ5).
- **R52** The `ui-ux` reviewer's default enrichment behavior MUST be native-only (no network fetch, no
  auto-detect of external skills); enrichment via `ui-ux-pro-max` or the Vercel Web Interface Guidelines MUST
  be opt-in through an explicit `review.local.ui.enrich` config value (enum, pinned by R73), and its absence or
  failure MUST never block the review (resolves OQ6).
- **R53** The `ai-native` specialist MUST remain signal-gated (not special-cased always-on), but its signal set
  MUST include this repo's own AI-surface paths — `commands/**`, `core/commands/**`, `skills/**`,
  `core/skills/**`, `rules/**`, `providers/**`, and `*.md` files declaring prompts / agent instructions — AND
  any path where untrusted input reaches an LLM, so it reliably fires on changes to a prompts / skills / agents
  product without an always-on exception (resolves OQ7).
- **R54** `/sw-review` and `/sw-ship` MUST accept a `--fast` / `--skip-local` escape hatch that skips the native
  phase-1 panel for a single run; the skip MUST be announced in the run output and MUST NOT change persisted
  config defaults (phase-mode handling pinned by R67).

### PRD additions — review-panel hardening (from `/sw-doc-review`)

- **R55** The R48 deny-list MUST be expanded and its matching semantics pinned: additional path globs
  (case-insensitive, matched on the repo-relative target path) `**/*.pem`, `**/*.key`, `**/*.p12`, `**/*.pfx`,
  `**/*.jks`, `**/*.keystore`, `**/.ssh/**`, `**/id_rsa*`, `**/id_ed25519*`, `**/*.asc`, `**/*.gpg`,
  `**/.npmrc`, `**/.netrc`, `**/.pypirc`, `**/.dockercfg`, `**/.docker/config.json`, `**/*.tf`, `**/*.tfvars`,
  `**/Dockerfile*`, and a provider-neutral CI set (`**/.gitlab-ci.yml`, `**/.circleci/**`, `**/Jenkinsfile`,
  `**/azure-pipelines.yml`, `**/.drone.yml`, `**/bitbucket-pipelines.yml`); additional content markers
  `-----BEGIN`, `client_secret`, `_authToken`. Content markers MUST be matched against BOTH the target's
  changed lines AND the proposed `suggested_fix` content; a match on either is surface-only.
- **R56** Any finding the `security` core reviewer emits, any finding touching lines another reviewer marked
  security-relevant, and any finding whose changed lines match security-control markers (`authorize`,
  `permission`, `role`, `isAdmin`, `verify(Token|Signature|Password)`, `hmac`, `jwt`, `session`, `cookie`,
  `csrf`, `cors`, `bcrypt`, `crypto`) MUST be surface-only regardless of path glob, so security logic outside
  named `auth/` directories cannot be auto-applied.
- **R57** Apply path validation MUST realpath-canonicalize the target, require the canonical path within the
  repo root with no symlinked path component, reject `.git/**` explicitly, re-validate immediately before the
  write to close the TOCTOU window, and validate the exact field used to perform the write (rejecting any patch
  whose internal target path differs from the validated `finding.file`).
- **R58** All reviewer and validator prompts MUST fence untrusted diff content as data (delimited / datamarked)
  with explicit instruction-injection hardening; deny-list classification, security severity floors, and apply
  gating MUST be evaluated deterministically and MUST NEVER be delegated to the model; the R49 validator's
  confirmation is necessary-not-sufficient (deterministic gates R55–R57 always run regardless of confirmation).
- **R59** P2 / P3 auto-apply MUST pass the deterministic receiving-review verification (R44) re-derived from the
  diff region; any behavior-altering or security-relevant fix MUST surface regardless of severity, so an
  injected non-P1 finding cannot land a logic change without scrutiny.
- **R60** `native.md` MUST pin the exact executable-code-line counting algorithm used for thresholds (exclude
  blank, brace-only, import, and comment lines; define added-versus-deleted handling) and its language
  coverage, and MUST pin a concrete numeric fix-size bound (max changed lines AND hunks per auto-applied fix,
  in addition to the existing character bound); boundary fixtures MUST cover 49 / 50 / 51 executable lines.
- **R61** Deterministic engines MUST back the runtime claims: `scripts/code-review-select.sh` (diff → roster)
  for R7 / R33 / R47 / R51 / R73; an extended `scripts/code-review-apply-check.sh` admitting validated-P1 (via a
  `--validated` input set only after the R49 wave), content-marker and symlink rails (R55 / R57), and the
  expanded deny-list; `scripts/review-local-resolve.sh` (config → fire/skip) for R14 / R15 / R16 / R35; and a
  backpressure clause in `rules/sw-subagent-dispatch.mdc` for R28. Fixtures invoke these scripts for true
  determinism; doc-grep fixtures cover prompt content only.
- **R62** The P1 validation wave MUST be newly created (not "reuse" of any prior template). The validator's
  input MUST be the diff plus the neutral finding location only — never the first reviewer's title,
  `suggested_fix`, or reasoning — and the validator MUST NOT read the same memory entries the first reviewer
  used. The contract MUST document that same-model validation cannot catch correlated false positives.
- **R63** `native.md` MUST document that `/sw-verify` is the smallest reliable check whose scope may be narrower
  than `check-gate.sh`, so verify-green is necessary but not sufficient for autonomy; auto-apply MUST be
  restricted to fix classes the configured verify can validate, and security-relevant or behavior-altering
  changes surface regardless of verify outcome (composes with R56 / R59).
- **R64** The panel MUST NOT clobber pre-existing user edits: it MUST refuse to run on a dirty tree OR snapshot
  the pre-apply state and restore deterministically; it MUST apply-and-verify with a per-fix checkpoint so a
  failed verify reverts only that fix's hunks (never user edits); and it MUST define a deterministic apply
  ordering with line re-anchoring after each applied hunk so batched fixes do not corrupt each other.
- **R65** The circuit-breaker MUST define `identical` as a normalized failure signature (e.g. failing check id
  plus normalized message, excluding timestamps / temp paths) AND enforce an absolute cap on total apply
  attempts per finding and per run, independent of whether the diff changed between attempts; the native
  panel's bounded apply loop and its relationship to `rules/sw-subagent-dispatch.mdc` MUST be reconciled
  (the rule MUST state which loop governs the native adapter).
- **R66** Each spawned reviewer MUST attest evidence of having processed the diff (e.g. files-examined count /
  heartbeat); an unattested empty result MUST be treated as `degraded` (fail-closed), not a clean pass; and a
  panel that cannot spawn or complete its always-on core roster MUST yield a panel-level `degraded` / `blocked`
  that blocks any `merge-ready-green`.
- **R67** Under the non-interactive phase-mode contract (a `/sw-deliver`-dispatched `/sw-ship`, PRD 004 R48):
  validated P1 MUST surface as `blocked` rather than auto-apply (auto-apply of P1 is permitted only in
  interactive `/sw-review` / `/sw-ship`); a circuit-breaker trip MUST emit a written `blocked` status with
  cause; `--fast` / `--skip-local` MUST be either refused or recorded in the durable per-phase status surface
  (PRD 004 R47); and a panel that cannot spawn its reviewers (gated on the PRD 004 R45 nested-dispatch spike)
  MUST yield `blocked`, never `merge-ready-green`.
- **R68** A persistent apply-policy config `review.local.apply` (enum `off` | `surface` | `auto`) MUST exist so
  operators can keep the review value while opting out of autonomous edits: `surface` reviews and surfaces but
  never auto-applies; `off` disables apply entirely; `auto` applies eligible fixes per R19. The shipped default
  MUST be `auto` (honoring brainstorm DK5; DL-28).
- **R69** Each run MUST emit a user-facing run report: the announced roster + selection reasons (R10), counts of
  applied / surfaced / reverted findings, an explicit human-triage block (P0, security-sensitive,
  unvalidated / non-confirmed P1, reverted-on-verify, circuit-breaker escalations), a digest of applied fixes
  (finding → file / line → applied change), and a documented one-shot revert for the run's applied changes;
  advisory `scope-fidelity` entries MUST be labeled advisory and name `gap-check` as the binding authority.
- **R70** The panel MUST deduplicate / merge overlapping findings across personas before surface or apply, and
  MUST apply a deterministic priority order with a soft cap on concurrently fired specialists, so the
  default-everywhere panel does not produce duplicated or unbounded surfaced / applied findings.
- **R71** External (phase-2) findings on panel-touched lines MUST NEVER be suppressed or down-weighted; the R25
  annotation is additive context only, and external P0 / P1 on panel-touched lines remain fully actionable.
- **R72** `native.md` MUST pin an authoritative native UI/UX checklist anchored to WCAG 2.2 AA — contrast,
  visible focus / focus order, keyboard operability (no traps, Enter / Escape semantics), name / role / value
  (ARIA roles, accessible names, landmarks), `prefers-reduced-motion`, minimum target size (2.5.5 / 2.5.8),
  semantic structure / heading hierarchy, form-label / error association, plus touch / interaction states,
  layout / responsive, and composition / boolean-prop hygiene; it MAY use the local `accessibility-a11y` skill
  as a native (non-network) authoring source. R46 asserts a finding against this baseline.
- **R73** The `ui-ux` selection signals MUST be pinned concretely: file globs `*.tsx` / `*.jsx` / `*.vue` /
  `*.svelte` / `*.css` / `*.scss` / `*.less`, style-suffixed files `*.styles.ts` / `*.css.ts`, CSS-in-JS
  markers (`styled` / `css\`` / `makeStyles` / `createGlobalStyle`) in `.ts` / `.js`, and directory globs
  `**/components/**` / `**/ui/**` / `**/styles/**` / `**/theme/**`; the stack-neutral claim MUST either be
  narrowed to "web + cross-platform JS" or extended with native-mobile globs (`*.swift`, `*.kt`, Android layout
  `*.xml`, `*.dart`, `*.storyboard`, `*.xib`). `review.local.ui.enrich` MUST be an enum with a native / off
  default, a bounded fetch timeout with fall-back-to-native and an announce-on-use / announce-on-degradation
  line, and enrichment MUST augment but never override the stack-neutral native baseline.
- **R74** Success MUST be measurable: define a baseline (phase-2 actionable findings per comparable change
  pre-feature) and an instrumentation requirement counting (a) phase-2 findings on panel-touched versus
  untouched lines and (b) the R71 contested-apply rate as a false-apply proxy; the success criterion ties
  continued confidence in auto-apply to a stated contested-apply threshold.
- **R75** The `scope-fidelity` → `gap-check` handoff MUST specify the run-report path (under the resolved
  `runDir` from `shipwright-state`) and a `gap-check` read step that consumes it advisory-only without altering
  the binding verdict (R12); the run-report path is covered by the R30 scrub and any persisted / memory write
  routes through R29 redaction.

## Technical Requirements

### Config resolution (R14–R16, R32, R61, R68)

The native panel fires on a resolved view of `review.local`, computed by `scripts/review-local-resolve.sh`
(schema-default-merged) so the absent-block path is deterministically testable:

```
resolve(review.local):
  enabled  = config.review.local.enabled  ?? true        # schema default
  provider = config.review.local.provider ?? "native"    # schema default (was "ce-code-review")
  apply    = config.review.local.apply    ?? "auto"      # off | surface | auto (default auto, DL-28)
  fire phase-1 iff (enabled == true AND provider != "none")
  independent of config.review.provider  (R15)
```

- Absent `review.local` block → resolves to `{enabled: true, provider: "native"}` (R16).
- `review.provider: "none"` does **not** suppress phase 1 (R14/R15).
- `--fast` / `--skip-local` overrides the resolved value for one run only (R54), announced; in phase-mode,
  handled per R67.

### Selection signal table (authoritative; R7, R8, R42, R47, R51, R53, R60, R73)

Core (always-on, R6): `correctness`, `maintainability`, `scope-fidelity`, `testing`, `security`.

| Specialist | Fires when (deterministic signal) |
|------------|-----------------------------------|
| `performance` | hot-path / loop / query / index keywords or `**/*.sql` perf-relevant changes |
| `api-contract` | changes to public API / route / handler / OpenAPI / proto / GraphQL schema files |
| `data-migration` | diff includes migration paths, schema dumps, or backfill scripts (R8) |
| `reliability` | error-handling / retry / timeout / concurrency markers; **silent-failure lens folded in (R41)** |
| `adversarial` | ≥50 changed executable code lines (counted per R60) OR auth / payments / data-mutation / external-API changes (R8) |
| `ui-ux` | globs per R73 (`*.tsx`/`*.jsx`/`*.vue`/`*.svelte`/`*.css`/`*.scss`/`*.less`, `*.styles.ts`/`*.css.ts`, CSS-in-JS markers in `.ts`/`.js`, dirs `**/components/**`/`**/ui/**`/`**/styles/**`/`**/theme/**`, + native-mobile globs) |
| `type-design` | type / interface / model decls: `*.d.ts`, `interface`/`type`/`class`/`struct`/`enum`/schema-model markers (R51) |
| `comment-accuracy` | changed comment / docstring lines, or `*.md`/`*.mdx` doc files (R51) |
| `ai-native` | AI-surface paths per R53 (`commands/**`, `core/commands/**`, `skills/**`, `core/skills/**`, `rules/**`, `providers/**`, prompt-declaring `*.md`) + any path where untrusted input reaches an LLM |

`previous-comments` is **excluded** from phase 1 (R9). Thresholds count executable code lines only per the
pinned R60 algorithm; identical diffs → identical panel (`scripts/code-review-select.sh`, R61); every fired
signal is announced (R10).

### Apply rails state machine (R19–R25, R44, R48, R55–R67)

```
finding → classify severity (deterministic; never model-delegated, R58)
  apply-policy != auto             → surface only (R68)  [surface/off]
  phase-mode AND P1                → blocked (R67)        [no unattended P1 apply]
  P0                               → surface only (R20)
  security-sensitive target        → surface only (R21/R48/R55)  [path glob OR content marker, in diff OR suggested_fix]
  security-reviewer-touched / control-marker → surface only (R56)
  no concrete suggested_fix         → surface only
  symlink / out-of-repo / .git/**   → surface only (R57)
  patch target != validated file    → surface only (R57)
  fix size > bound (lines/hunks/chars) → surface only (R60)
  behavior-altering / security-relevant → surface only (R59/R63)
  wrong-for-codebase / unverified   → surface only (R44 receiving-review + YAGNI)
  P1 (interactive only)             → independent validation wave (R22/R49/R62, deep tier, fresh context)
                                        confirmed   → apply  (deterministic gates above still run, R58)
                                        not-confirmed / degraded → surface only
  P2 / P3                           → deterministic receiving-review re-derive (R59) → apply
apply: deterministic ordering + per-fix checkpoint + line re-anchor (R64); refuse dirty tree or snapshot (R64)
  per-fix /sw-verify (bounded, R23/R63)
    pass    → keep (remains in tree for phase-2, R25; external findings additive-only, R71)
    fail    → revert only that fix's hunks, re-surface as finding
  identical failure signature, attempt cap reached → circuit-breaker (R65); phase-mode → blocked (R67)
emit run report (R69): applied / surfaced / reverted counts, human-triage block, change digest, one-shot revert
```

### Model tiering (R27)

`correctness`, `security`, `adversarial`, and the P1 validation wave (R49/R62) inherit the deep / session tier;
all other reviewers run mid-tier. Tiers resolve from `workflow.config.json` `models.tiers` only — no semantic
tier name in agent frontmatter (R9 floor).

### Reviewer registration (R6, R27, R31, R36–R40)

Native panel personas are **inline prompts authored in `native.md`** (core + specialists), dispatched via the
Task tool as deep/mid-tier subagents — not 14 separately registered `core/agents/*.md` files — so the panel
adds one adapter artifact plus its prompts rather than a large agent surface. Dispatch obeys
`rules/sw-subagent-dispatch.mdc` (bounded parallelism, backpressure R28/R61, circuit-breaker R65).

### Run report contract (R10, R18, R50, R69, R75)

The run report (written under the resolved `runDir`) contains: announced roster + per-specialist selection
reasons; per-severity counts of applied / surfaced / reverted; a human-triage block listing every surface-only
finding with reason (P0, security-sensitive, unvalidated / non-confirmed P1, reverted-on-verify,
circuit-breaker escalations); a change digest (finding → file / line → applied hunk) with a documented one-shot
revert; and the advisory `scope-fidelity` block (labeled advisory; names `gap-check` as binding) forwarded to
the `gap-check` step per R75. The report path is scrubbed per R30; any memory write routes through R29.

### Native UI/UX checklist (R72)

Authoritative checklist pinned in `native.md`, WCAG 2.2 AA-anchored: contrast; visible focus + focus order;
keyboard operability (no traps, Enter / Escape); name / role / value (ARIA roles, accessible names, landmarks);
`prefers-reduced-motion`; minimum target size (2.5.5 / 2.5.8); semantic structure / heading hierarchy;
form-label / error association; touch / interaction states; layout / responsive; composition / boolean-prop
hygiene. Native (non-network) authoring may draw on the local `accessibility-a11y` skill. Optional enrichment
(R52/R73) augments but never overrides this baseline.

### Files touched (implementation checklist)

| Area | Paths |
|------|-------|
| Native adapter | `core/providers/code-review/native.md` (new — selection table, deny-list, counting algo, fix-size bound, checklist, validator contract, registration) |
| Contract | `core/providers/code-review/CAPABILITIES.md` (advisory scope-fidelity R13; validated-P1 + expanded deny-list + symlink boundary) |
| Review automation rule | `core/rules/code-review-automation.mdc` (advisory signal, default-on framing) |
| Dispatch rule | `rules/sw-subagent-dispatch.mdc` (backpressure R28/R61; native apply-loop reconciliation R65) |
| Commands | `core/commands/sw-review.md` (R17/R54), `core/commands/sw-ship.md` (R18/R54/R67), `core/skills/gap-check` (R75 read step) |
| Reviewer prompts | inline native panel personas in `native.md` (core + specialists), embedding the R43 calibration catalog + R58 injection fencing |
| Selection / apply scripts | `scripts/code-review-select.sh` (new), `scripts/code-review-apply-check.sh` (extend: validated-P1, expanded deny-list, content markers, symlink/`.git`, fix-size lines/hunks), `scripts/review-local-resolve.sh` (new) |
| Config schema | `.sw/config.schema.json`, `core/sw-reference/config.schema.json` (`provider` default `native`, `review.local.apply` enum, `review.local.ui.enrich` enum) |
| Example config | `.sw/workflow.config.example.json` (populated `review.local` block, R32) |
| Memory | `scripts/memory-redact.sh` chokepoint (R29/R30) — used, not re-implemented |
| Tests | `scripts/test/fixtures/code-review-*`, `scripts/test/run-code-review-fixtures.sh`, `run-persona-selection-fixtures.sh` |
| Dist | sync to `dist/cursor/`, `dist/claude-code/` (R31) |

## Security & Compliance

- **No auto-apply on sensitive targets:** the R21/R48/R55 deny-list (auth / authz, secrets, credentials,
  key material, IaC, registry/credential config, provider-neutral CI config) is surface-only at every severity,
  matched (case-insensitively) by path glob OR content marker against both the diff and the `suggested_fix`.
- **Security logic outside named dirs:** any `security`-reviewer-touched finding or security-control-marker
  match is surface-only regardless of path (R56), closing the "benign-named file weakens a control" hole.
- **P0 never auto-applied:** P0 findings are always surfaced for human triage (R20).
- **Prompt-injection containment:** untrusted diff content is fenced as data in every reviewer / validator
  prompt; deny-list classification, security severity floors, and apply gating are deterministic and never
  model-delegated (R58); the validator's confirmation is necessary-not-sufficient.
- **Untrusted apply path:** `suggested_fix` / `file` are untrusted — realpath canonicalization, no-symlink, no
  `.git/**`, TOCTOU re-validation, write-field validation, and bounded fix size are enforced before any edit
  (R57/R60). The panel refuses a dirty tree or snapshots and restores deterministically (R64).
- **Autonomy oversight:** validated-P1 auto-apply happens only interactively; unattended phase-mode surfaces P1
  as `blocked` (R67). A persistent `review.local.apply` knob lets operators keep review value with no edits
  (R68). `/sw-verify` is documented as narrower than `check-gate.sh` — verify-green is necessary not sufficient
  (R63).
- **Fail-closed:** `skipped` / `failed` / `degraded` without `findings` is never a pass; unattested empties →
  `degraded`; a panel that cannot run its core roster blocks `merge-ready-green` (R5/R66).
- **Memory redaction:** all reads / writes (incl. finding-derived) route through `scripts/memory-redact.sh`;
  only distilled learnings persist, never raw reviewer output, diffs, or transcripts (R29); run artifacts and
  the run report are scrubbed after parsing (R30).
- **Gate authority preserved:** the local severity gate is additive (`haltOn: []` default); `check-gate.sh`
  remains the sole CI / merge oracle (R26); external findings are never suppressed (R71).
- **AI trust boundary:** `ai-native` flags paths where untrusted input reaches an LLM (R40/R53).

## Testing Strategy

Fixtures split into **deterministic-script** assertions (invoke `code-review-select.sh` /
`code-review-apply-check.sh` / `review-local-resolve.sh`) and **doc-grep** assertions (prompt / checklist
content). Runtime agent behavior is asserted only via the deterministic scripts, never by claiming a grep
proves a runtime outcome.

### Fixtures (`scripts/test/run-code-review-fixtures.sh` + `run-persona-selection-fixtures.sh`)

| Fixture | Asserts | R-IDs |
|---------|---------|-------|
| `native-panel-core` | core roster always selected on any diff (select.sh) | R6 |
| `native-panel-selection-deterministic` | fixed diff → exact reproducible roster (select.sh) | R7, R33, R47, R61 |
| `native-panel-data-migration-gate` | `data-migration` fires only on migration / schema / backfill artifacts | R8 |
| `native-panel-adversarial-threshold` | `adversarial` fires per R60 count; boundary 49 / 50 / 51 exec lines | R8, R60 |
| `native-line-count-algo` | executable-line counter excludes blanks / braces / imports / comments per R60 | R60 |
| `native-panel-no-previous-comments` | `previous-comments` never in phase-1 panel | R9 |
| `native-panel-announce` | each fired specialist's selection reason announced | R10, R42 |
| `native-resolve-default` | `review-local-resolve.sh` fires phase-1 on default / absent block / provider:none | R14, R16, R35, R61 |
| `native-resolve-opt-out` | skipped only on `enabled:false` / `provider:"none"` | R15, R35 |
| `native-apply-policy` | `apply:off|surface` never auto-applies; `auto` applies eligible | R68 |
| `native-apply-p0-surface` | P0 surfaced, never applied | R20, R34 |
| `native-apply-p2p3-happy` | P2 / P3 with all rails passing → applied | R19, R59 |
| `native-apply-security-surface` | per-class deny-list (each glob + each marker, diff + suggested_fix) surfaced; negative cases not over-blocked | R21, R48, R55, R34 |
| `native-apply-security-logic` | security-reviewer-touched / control-marker finding surfaced regardless of path | R56 |
| `native-apply-symlink` | symlink / `.git/**` / patch-target-mismatch target surfaced, not applied | R57 |
| `native-apply-p1-validated` | P1 applied only after confirming independent validation; unvalidated surfaced | R22, R49, R62, R34 |
| `native-apply-injection` | injected payload in diff does not flip a surface-only decision or suppress a P0 | R58 |
| `native-apply-dirty-tree` | dirty tree refused or snapshotted; revert restores only panel hunks | R64 |
| `native-apply-revert-on-fail` | failed `/sw-verify` reverts only that fix and re-surfaces it | R23, R64, R34 |
| `native-apply-circuit-breaker` | identical-signature attempts hit cap → halt + escalate; phase-mode → blocked | R24, R65, R67, R34 |
| `native-apply-fix-persists` | applied fix remains in tree; external finding annotated additively, not suppressed | R25, R71 |
| `native-phase-mode-p1-blocked` | non-interactive phase-mode: validated P1 → `blocked`, not applied | R67 |
| `native-skip-local-flag` | `--fast` / `--skip-local` skips panel for one run, announced; phase-mode records / refuses | R54, R67 |
| `native-scope-fidelity-advisory` | advisory defer / stub / TODO-marked / omission surfaced; no binding verdict; forwarded to gap-check | R11, R12, R50, R75 |
| `native-run-report` | report lists roster, applied / surfaced / reverted counts, human-triage block, change digest, one-shot revert | R69 |
| `native-dedup` | overlapping findings across personas deduped; soft cap honored | R70 |
| `native-attestation` | unattested empty reviewer → `degraded`; core-roster spawn failure blocks merge-ready-green | R5, R66 |
| `native-calibration-traps` | reviewer prompts embed the calibration catalog (doc-grep) | R43, R44 |
| `native-uiux-fires` | `ui-ux` fires on seeded frontend / CSS-in-JS / mobile diff, silent on unrelated | R36, R45, R51, R73 |
| `native-uiux-native-only` | `ui-ux` produces a WCAG-baseline a11y finding from native checklist, no external skill | R37, R46, R52, R72 |
| `native-uiux-enrich-degrade` | enrich opted-in but source unavailable → completes native-only + announces degradation | R52, R73 |
| `native-type-design-fires` | `type-design` fires on seeded type / model diff, silent otherwise | R38, R45, R51 |
| `native-comment-accuracy-fires` | `comment-accuracy` fires on seeded comment / doc diff, silent otherwise | R39, R45, R51 |
| `native-ai-native-fires` | `ai-native` fires on seeded prompt / agent / AI-surface diff (incl. `core/` plugin paths + untrusted-LLM path) | R40, R45, R51, R53 |
| `native-reliability-silent-failure` | silent-failure lens folded into `reliability`; no separate persona; no simplifier added | R41 |
| `native-tiering` | high-stakes reviewers + P1 validation at deep tier; no tier name in frontmatter (doc-grep) | R27, R49 |
| `native-dispatch-backpressure` | capacity error → retry as backpressure, not reviewer failure (doc-grep on rule) | R28, R61 |
| `native-memory-redaction` | finding whose detail / suggested_fix quotes a secret-bearing line is redacted on persist | R29, R30 |
| `native-schema-default` | schema `review.local.provider` default `native`; `apply` + `ui.enrich` enums; example populated | R3, R32, R68, R73 |
| `native-doc-framing` | `sw-review.md` / `sw-ship.md` framing states default-on + halt/surface semantics (doc-grep) | R17, R18 |
| `native-dist-parity` | `core/` → `dist/` propagation parity; runners green | R31 |

### Regression

- Existing `ce-code-review` adapter behavior in `run-code-review-fixtures.sh` and
  `run-persona-selection-fixtures.sh` stays green (R3); the current "apply-check rejects P1" fixture is updated
  to "rejects **unvalidated** P1, admits **validated** P1" (R22/R61).
- Emitter / parity fixtures green after `core/` → `dist/` regenerate (R31).

### Manual smoke (post-implementation)

1. Default-config repo, `review.provider: "none"`: `/sw-review` announces roster + per-specialist reasons (R14/R10).
2. Seed an incomplete-work diff: `scope-fidelity` surfaces an advisory signal; `gap-check` stays the only binding
   completeness verdict (R11/R12/R50).
3. Seed a P1 logic fix + a P0 + a `.pem`/secrets change: P1 applies after validation (interactive), re-verify keeps
   tree green; P0 and secrets surfaced only (R19–R23/R48/R55).
4. Seed a frontend `.tsx` contrast / focus issue, no `ui-ux-pro-max`: `ui-ux` fires, surfaces a WCAG-baseline a11y
   finding from the native checklist (R36/R37/R46/R72).
5. `/sw-review --skip-local` → panel skipped for that run, announced; config unchanged (R54).
6. `review.local.apply: surface` → panel reviews and surfaces but applies nothing (R68).

## Success Criteria

1. `/sw-review` / `/sw-ship` on default config visibly spawn the native panel (announced roster + per-specialist
   reasons), including `review.provider: "none"` (R14/R10).
2. Identical diffs produce identical panels across runs and fixtures (R7/R33/R61).
3. The panel auto-applies eligible P2–P3 (and interactive validated P1) fixes, re-verifies, leaves the tree green;
   P0 and security-sensitive findings are surfaced, never auto-applied (R19–R23).
4. `scope-fidelity` surfaces ≥1 advisory defer / stub / omission on a seeded diff while `gap-check` remains the only
   binding completeness verdict (R11/R12/R50).
5. Each new specialist fires on its seeded signal diff and stays silent on unrelated diffs (R45); `ui-ux` surfaces a
   WCAG-baseline finding native-only (R46/R72).
6. Injected diff content cannot flip a surface-only decision or suppress a P0 (R58); deny-list / symlink rails hold
   per-class (R48/R55/R56/R57).
7. Phase-2 actionable findings on comparable changes drop against the baseline, with the contested-apply rate below
   the stated threshold (R74).
8. All gate / doc / impl / code-review fixtures stay green after `core/` → `dist/` propagation (R31).

## Rollout Plan

### Phase 1 — Contract, config & deterministic scripts

- Author `native.md` (selection table R47, deny-list R48/R55, counting algo + fix-size bound R60, checklist R72,
  validator contract R62, registration); update `CAPABILITIES.md` / `code-review-automation.mdc` (R13); add
  `code-review-select.sh` + `review-local-resolve.sh`, extend `code-review-apply-check.sh` (validated-P1, expanded
  deny-list, symlink/`.git`, content markers, fix-size); schema defaults + `apply` + `ui.enrich` enums + example
  (R32/R68/R73); backpressure clause in dispatch rule (R28/R61). Contract / schema / selection / deny-list /
  resolve fixtures green.

### Phase 2 — Roster, selection & calibration

- Core panel (R6) + gated specialists with pinned signals (R7/R8/R51/R53/R73), announce record (R10),
  `previous-comments` exclusion (R9), reliability silent-failure fold-in / no simplifier (R41), calibration catalog
  + injection fencing in every prompt (R43/R58), attestation (R66). Selection / announce / calibration / attestation
  fixtures green.

### Phase 3 — Apply rails & autonomy

- Report-and-apply machinery (R4), deterministic severity gating (R58), deny-list + security-logic + symlink rails
  (R20/R21/R48/R55/R56/R57), P1 validation wave (R22/R49/R62), behavior-altering surface (R59/R63), per-fix
  checkpoint + dirty-tree + ordering (R64), bounded re-verify + circuit-breaker (R23/R24/R65), apply-policy knob
  (R68), external-annotation additive-only (R25/R71), model tiering (R27), dedup + cap (R70). Apply-rails fixtures
  green.

### Phase 4 — Gating, framing, phase-mode & report

- `review-local-resolve.sh` default-on independent of `review.provider` (R14/R15/R16); reword `sw-review.md` /
  `sw-ship.md` (R17/R18); additive gate (R26); `--fast` / `--skip-local` (R54); phase-mode precedence (R67);
  run-report contract + scope-fidelity → gap-check forwarding (R69/R50/R75). Gating / framing / phase-mode / report
  fixtures green.

### Phase 5 — Memory, instrumentation, distribution & docs

- Memory redaction wiring + run-artifact scrub (R29/R30); instrumentation for phase-2-load + contested-apply rate
  (R74); `core/` → `dist/` propagation (R31); fixtures + runners wired into `verify.test`. All suites green; dogfood
  on a Shipwright change.

**Rollout safety:** additive — repos that explicitly set `review.local.provider: "ce-code-review"` keep that
adapter (R3); the only default change is `provider` `ce-code-review` → `native` plus the new `review.local.apply`
default (DL-28). No migration required.

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-1 | Build a native phase-1 engine; make `review.local.provider: "native"` the default | User wants full roster control + drop the soft `ce-code-review` dependency; native is local-only (no egress / vendor cost). Brainstorm DK1. |
| DL-2 | Keep `ce-code-review` selectable but not default | No regression for repos that set it explicitly; hybrid pluggable-engine deferred. Brainstorm DK1. |
| DL-3 | Roster = fixed core + signal-gated specialists; `testing` + `security` always-on | User treats coverage + security as non-negotiable. Brainstorm DK2. |
| DL-4 | `scope-fidelity` advisory; `gap-check` stays the binding completeness authority | Surfaces gaps early without verdict creep. Brainstorm DK3. |
| DL-5 | Default-ON, decoupled from `review.provider` (incl. `none`); only `review.local` opt-out disables | Native review is fully local, so external-provider safe-default-off reasons (PRD 002/003) do not apply to *surfacing*. Brainstorm DK4. |
| DL-6 | Autonomous apply incl. validated P1, behind hard rails | P0 / security never auto-applied; P1 needs independent validation; mandatory re-verify + revert + circuit-breaker. Brainstorm DK5. |
| DL-7 | Severity gate stays additive (`haltOn: []` default) | `check-gate.sh` remains the sole CI oracle. Brainstorm DK6. |
| DL-8 | High-stakes reviewers + P1 validation at deep tier; tiers only in `models.tiers` | R9 floor. Brainstorm DK7. |
| DL-9 | Add four optional specialists; fold silent-failure into `reliability`; no simplifier | Simplification stays `/sw-simplify`. Brainstorm DK8. |
| DL-10 | Calibration catalog in every prompt; rails encode receiving-review discipline | Findings evidence-verified; wrong-for-codebase findings skipped, not applied. Brainstorm DK9. |
| DL-11 | `ui-ux` native-first with optional enrichment | Native checklist owns a11y / interaction / layout / composition; enrichment opt-in, never blocks. Brainstorm DK10. |
| DL-12 | Pin all gated-specialist selection signals in one canonical table in `native.md` (R47) | Auditable, reproducible selection; resolves OQ1. |
| DL-13 | Security-sensitive deny-list = concrete path globs ∪ content markers, fixture-exercised (R48) | A real auto-apply guard needs a concrete, testable list; resolves OQ2. |
| DL-14 | P1 validation = fresh-context deep-tier second opinion; created, not reused (R49/R62) | Independent second opinion that cannot anchor on the first reviewer; resolves OQ3. |
| DL-15 | `scope-fidelity` advisory → run report + gap-check input, not durable memory (R50/R75) | Surfaces forward without storage or verdict creep; resolves OQ4. |
| DL-16 | Pin the four new specialists' signal sets (R51/R73) | Same-inputs → same-panel determinism; resolves OQ5. |
| DL-17 | `ui-ux` enrichment native-only by default; opt-in via `review.local.ui.enrich` enum (R52/R73) | Preserves no-heavy-dependency / no-network-by-default; resolves OQ6. |
| DL-18 | `ai-native` stays signal-gated; signal set includes this repo's AI-surface paths (R53) | Fires on a prompts / skills / agents product without a special-case always-on; resolves OQ7. |
| DL-19 | Ship a `--fast` / `--skip-local` one-run escape hatch (R54) | Brainstorm scoped this hatch in (Deferred); adaptive latency budgeting stays deferred. |
| DL-20 | Expand the deny-list (key material, IaC, registry config, provider-neutral CI) + match diff AND suggested_fix, case-insensitive (R55) | Path-only GitHub-Actions-only matching missed high-value secret / CI classes (security + adversarial panel). |
| DL-21 | Route security-reviewer-touched / control-marker findings to surface-only regardless of path (R56) | Auth/authz logic lives outside `auth/` dirs; syntactic path matching alone is bypassable. |
| DL-22 | Realpath / no-symlink / no-`.git` / TOCTOU / write-field validation on the apply path (R57) | Lexical in-repo checks are defeated by symlinks and patch-internal target paths. |
| DL-23 | Fence untrusted diff as data; deterministic (never model-delegated) gating; validator necessary-not-sufficient (R58/R59) | The diff is attacker-influenceable; injection could confirm a malicious P2/P3 or suppress a P0. |
| DL-24 | Pin executable-line counting algorithm + numeric fix-size bound (R60) | The 50-line `adversarial` threshold is a determinism cliff without a pinned counter; "bounded size" needs a number. |
| DL-25 | Back runtime claims with `code-review-select.sh` / extended `apply-check.sh` / `review-local-resolve.sh` (R61) | The existing harness greps markdown + runs scripts; runtime determinism needs real engines, and `apply-check.sh` hard-rejects P1 today. |
| DL-26 | Validator independence: diff + neutral location only; no shared memory entries; same-model FP limit documented (R62) | "Independent" must be operationally defined or it collapses into a confirming second pass. |
| DL-27 | Per-fix checkpoint + dirty-tree refusal/snapshot + deterministic apply ordering + line re-anchor (R64) | Batch verify cannot attribute failure; naive revert clobbers user edits; offset drift corrupts batched applies. |
| DL-28 | Add persistent `review.local.apply` (`off`/`surface`/`auto`); **shipped default `auto`** (user-confirmed at the doc boundary) | Reviewers (product / security) flagged that bundling default-ON autonomous edits with the phase-1 bug fix expands write authority with no surface-only middle option; the knob restores the choice (`surface`/`off`). The user confirmed `auto` as the shipped default to honor the frozen brainstorm's maximum-safe-autonomy decision (DK5); the hard rails (R20/R21/R48/R55–R67) and the opt-out knob bound the risk. |
| DL-29 | Interactive-only P1 auto-apply; phase-mode validated-P1 → `blocked` (R67) | Reconciles with PRD 004 R48 (phase-mode converts the validated-P0/P1 halt to `blocked`); keeps unattended P1 code off `<type>/<slug>` without human review. |
| DL-30 | Run-report contract + change digest + one-shot revert; dedup + cap; external findings additive-only (R69/R70/R71) | Trust in default-ON autonomy needs transparency, easy reversal, bounded noise, and no masking of external regressions. |
| DL-31 | Pin native UI/UX checklist to WCAG 2.2 AA; concrete `ui-ux` globs + CSS-in-JS + mobile; enrich enum + bounded fetch (R72/R73) | "Stack-neutral" must match the firing globs; a shippable a11y checklist needs focus / keyboard / ARIA / reduced-motion, not just contrast. |
| DL-32 | Measurable external-load reduction: baseline + panel-touched-vs-untouched + contested-apply rate (R74) | The headline value goal was unfalsifiable; a false-apply proxy makes the autonomy net-value checkable. |

## Open Questions

None — all brainstorm Open Questions are resolved and recorded in the Decision Log: OQ1→DL-12, OQ2→DL-13,
OQ3→DL-14, OQ4→DL-15, OQ5→DL-16, OQ6→DL-17, OQ7→DL-18. The single product trade-off surfaced by the persona
panel — the shipped default for `review.local.apply` (R68/DL-28) — was confirmed by the user as `auto` at the
documentation boundary before freeze.
