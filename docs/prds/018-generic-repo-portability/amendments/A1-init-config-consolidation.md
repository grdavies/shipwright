---
date: 2026-06-26
amends: docs/prds/018-generic-repo-portability/018-prd-generic-repo-portability.md
supersedes: [R3]
frozen: true
frozen_at: 2026-06-26
---

# Amendment A1: `/sw-init` rename + install/config consolidation + version-drift refresh

## Overview

PRD 018 substantially rewrites the per-repo configuration command (`/sw-setup`): project-type detection,
verify configuration, the portability self-check, the schema-resolution path, and the dev-repo marker. While
that work is frozen but not yet implemented, two adjacent problems surfaced that should be built once, in the
same body of work, rather than layered onto a surface we are about to rework:

1. **Naming.** `/sw-setup` is less descriptive than `/sw-init` for "initialize this repo for Shipwright"
   (mirroring the `/…-init` convention used by comparable skills).
2. **The real friction — config drift on version bump.** Installing a new plugin build
   (`scripts/install.sh` on the manual path, or a marketplace update) does **not** re-apply a repo's
   configuration. The operator must remember to re-run `/sw-setup` to pick up new schema fields, defaults, and
   routing — and forgets. Today nothing tells the repo its config is stale relative to the installed plugin.

This amendment renames the command to **`/sw-init`** (retaining `/sw-setup` as a deprecated alias so no parent
requirement is contradicted), unifies the per-repo configuration logic behind a single configurator, lets the
manual `install.sh` path *offer* to run it (without coupling per-repo config into the global installer), and
adds a **configured-version stamp + drift notice** so a stale repo config announces itself and offers a
non-destructive refresh.

It does **not** revisit the architectural fact established in PRD 018 that global install (`install.sh`,
absent for marketplace installs) and per-repo configuration are distinct scopes — per-repo config remains a
per-repo action available regardless of install method.

## Context

`scripts/install.sh` is a global, manual-install convenience (excluded from `dist/`; absent for marketplace
installs). Per-repo state — including differing review/memory/verify configuration across multiple local
repos — cannot live in a once-per-machine installer. PRD 018 already centralizes per-repo behavior in the
configuration command; this amendment makes that command the single configurator, gives it a clearer name,
and closes the version-drift gap that causes the maintainer (and future users) to run a new build against
stale config without noticing.

## Goals

1. **Clearer entry** — `/sw-init` is the canonical per-repo configuration command; `/sw-setup` keeps working
   as a deprecated alias for one release.
2. **One configurator** — `/sw-init` and any scriptable entry share a single source of truth for per-repo
   config; install and config do not maintain divergent logic.
3. **No forgotten second step** — after a manual `install.sh` run inside a repo, the operator is offered the
   per-repo init; and any repo whose config predates the installed plugin version is told so and offered a
   non-destructive refresh.

## Non-Goals

- Folding per-repo configuration *into* the global installer or making `install.sh` a required user step
  (marketplace installs have no `install.sh`).
- `install.sh` enumerating, scanning, or initializing *other* local repos, or invoking the configurator
  itself — it may only print an opt-in reminder + the `/sw-init` invocation hint for the current repo.
- Auto-applying config changes without operator consent — refresh is additive/doctor-scoped (see R32); it
  never auto-merges `verify.*`, user-set `defaultBaseBranch`, memory/review choices, or model tiers, and never
  silently overwrites user-edited values.
- Changing the configuration *content* defined by PRD 018 R1–R27 (detection, presets, verify, self-check,
  schema path, marker). This amendment **does** change: the command name (R28), single-configurator
  consolidation (R29–R30), the manual-install opt-in offer (R31), and the version-drift stamp/notice (R32).
- A package-manager/marketplace publishing pipeline.

## Requirements

Continue the parent namespace (parent max R27).

- **R28** The per-repo configuration command MUST be named **`/sw-init`**, with the canonical command file
  `core/commands/sw-init.md`. `/sw-setup` MUST be retained as a **delegate-only deprecated alias** for one
  release: `core/commands/sw-setup.md` prints a deprecation notice and delegates to `/sw-init` with identical
  behavior (no duplicate body); the `models.routing`/`communication.routing` `sw-setup` key gains an
  `sw-init` entry, keeping `sw-setup` as an alias for one release. Wherever parent requirements name the
  command or file `/sw-setup` (including R18/TR2/TR8 and the R3 CTA — superseded below), the canonical name is
  `/sw-init`; the alias keeps parent *behavioral* MUSTs satisfied at invocation time.

### Superseded requirement (replaces parent R3)

- **R3 (superseded)** The verification gate, **`/sw-init`** doctor, `/sw-status`, and `/sw-ready` MUST surface
  an unconfigured verify via a distinct `verify-unconfigured` signal with an actionable CTA (**"run
  `/sw-init`"**). A placeholder taxonomy MUST classify no-op verify (empty, `echo …`, `:`, `true`, `exit 0`)
  as unconfigured so the echo-ban cannot be trivially bypassed. Blocking semantics (parent DL-13): non-blocking
  and loud in interactive/manual flows; hard-block under `/sw-deliver` and autonomous mode unless
  `verify.allowUnconfigured: true`. (Only the command-name CTA changes from parent R3; taxonomy and blocking
  semantics are unchanged.)
- **R29** Per-repo configuration logic MUST have a single source of truth (one configurator invoked by
  `/sw-init` and by any scriptable entry point); install tooling MUST NOT reimplement configuration logic.
- **R30** `/sw-init` MUST be the interactive in-editor surface; the non-interactive scriptable path (parent
  R4 `--accept-defaults`) MUST remain available for CI/headless configuration through the same configurator.
- **R31** When `scripts/install.sh` (manual/dev path) is run **from within the current git repository**, after
  the global copy it MUST print a **cwd-scoped opt-in offer** to run `/sw-init` for *that* repo — an opt-in
  reminder plus the `/sw-init` invocation hint only; it MUST NOT run the configurator, hold any config logic
  (R29), enumerate/init other repos, or act automatically on the global copy. It MUST be a no-op when not in a
  repo and impose no requirement on marketplace installs (where `install.sh` is absent). R31 removes the
  forgot-to-configure friction only for the repo the operator is in; **cross-repo staleness is addressed by
  R32**, not R31.
- **R32** `/sw-init` MUST stamp the configured-against versions into `.cursor/workflow.config.json` as
  `configuredWith: { shipwrightVersion, schemaVersion }` (sources: the installed plugin version and the
  bundled `config.schema.json` revision). The config is **stale** when either differs from the running
  plugin/schema. On staleness, Shipwright MUST surface a notice — "config may be stale; run `/sw-init` to
  refresh" — across a **closed set** of surfaces only: the `/sw-init` doctor, the portability self-check
  (parent R24), and one shared at-entry helper (no `beforeSubmitPrompt` hook, no per-command duplication).
  Refresh MUST be **additive and consent-gated**: add absent schema keys with their schema defaults, with an
  explicit confirm per affected subtree; it MUST NOT auto-merge `verify.*`, a user-set `defaultBaseBranch`,
  memory/review provider choices, or model tiers; and `configuredWith` is bumped only after an accepted
  refresh.
- **R33** Documentation and naming MUST align: `README.md`, `docs/guides/getting-started.md`,
  `docs/guides/configuration.md`, `rules/sw-naming.mdc`, and the canonical command file
  `core/commands/sw-init.md` (with the delegate-only `core/commands/sw-setup.md` alias) MUST use `/sw-init`
  (noting the `/sw-setup` deprecation), and MUST document the "global install once vs per-repo `/sw-init`"
  model and the version-drift refresh behavior. On task regeneration, R33 doc work MERGES into the parent R18
  doc task — no parallel doc phase.

## Testing Strategy

| Fixture | Asserts | R-IDs |
|---------|---------|-------|
| `init-command-rename` | `/sw-init` is the command; `/sw-setup` alias prints deprecation + delegates with identical behavior | R28 |
| `init-single-configurator` | `/sw-init` and the scriptable path invoke one configurator; install tooling holds no config logic | R29, R30 |
| `install-offers-init-in-repo` | `install.sh` run inside a repo offers `/sw-init` post-copy (opt-in); no-op outside a repo; never auto-runs on global copy | R31 |
| `config-version-stamp` | `/sw-init` writes `configuredWith.{shipwrightVersion,schemaVersion}` to config | R32 |
| `stale-config-notice-and-refresh` | version/schema mismatch surfaces the stale-config notice in doctor + self-check + at-entry nudge; refresh merges non-destructively | R32 |
| `init-docs-and-naming` | README, getting-started, configuration, `sw-naming.mdc`, command file use `/sw-init` + document install/config model + drift refresh | R33 |

These extend PRD 018's `run-portability-setup-fixtures.sh` / onboarding suites; register in the dogfood verify
chain alongside the parent's fixtures.

## Implementation note (task integration)

This amendment adds R28–R33 and supersedes R3 in the PRD 018 spec union. The frozen task list
`tasks-018-generic-repo-portability.md` MUST be regenerated against the union (R1–R33, superseded R3) before
implementation so the new requirements carry tasks + traceability. Regeneration MUST also update parent
fixture/command-path references that name `/sw-setup` / `core/commands/sw-setup.md` (e.g. `portability-self-check`,
`setup-accept-defaults-no-write`, task File paths) to `/sw-init` / `core/commands/sw-init.md` (alias retained).
The rename + single-configurator fold into Phase 1 (configuration surface); R31 attaches to the boundary/
install phase; R32 to the setup phase; R33 merges into the R18 doc task. No new feature branch — same
`feat/generic-repo-portability`.

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-14 | Rename `/sw-setup` → `/sw-init`; keep `/sw-setup` as a one-release deprecated alias | Clearer intent; alias avoids contradicting parent R1–R27 and preserves muscle memory during transition. |
| DL-15 | Per-repo config stays a per-repo command; `install.sh` only *offers* it on the manual path | Global installer can't hold per-repo (multi-repo, differing review configs) and is absent for marketplace installs; offering-not-folding removes the friction without breaking those cases. |
| DL-16 | Configured-version stamp + drift notice + non-destructive refresh | Fixes the actual reported friction (new build run against stale config) by making staleness self-announcing rather than relying on the operator remembering a second step. |
| DL-17 | Amend PRD 018 (not a standalone PRD) and regenerate its task list against the union | The change reshapes the very `/sw-setup` surface 018 builds; one coherent PR avoids building then reworking that surface (operator selection). |

## Open Questions

None.
