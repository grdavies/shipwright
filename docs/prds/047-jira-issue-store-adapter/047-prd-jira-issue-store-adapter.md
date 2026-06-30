---
date: 2026-06-30
topic: jira-issue-store-adapter
brainstorm: docs/brainstorms/2026-06-30-issue-backed-planning-store-requirements.md
program: issue-backed-planning-store
depends: [043]
frozen: true
frozen_at: 2026-06-30
---

# PRD 047 — Jira issue-store adapter

## Overview

This PRD adds a **Jira** `issuesProvider` adapter to the PRD 043 issue-store — the future-proof planning
store for Bitbucket code repos (whose native issue tracker reaches end-of-life on 2026-08-20) and for teams
whose planning already lives in Jira. Per PRD 043 D9 the issues provider is decoupled from the code host, so
a Bitbucket (or any) code repo can point its planning store at Jira — **or** at a separate GitHub/GitLab
planning project. This PRD implements Jira against the PRD 043 LCD contract, capability matrix, and canonical
hash; it does not re-specify any of those core contracts.

This PRD **owns** core R-ID **R32** (stated as **R32a**/**R32b**) and **references** the core contracts it
builds on — PRD 043 R28/R43 (visibility/destination resolver), R29 (`sw-edges`), R30/R31 (LCD + capability
matrix), R35 (canonical serialization), R37 (on-read tamper-evidence), R39 (request budget), R40 (lifecycle
tombstones), R42 (body-marker isolation), R44 (dedicated `issues.tokenEnv` + min-scope init probe), R45
(secret-scan chokepoint), R46 (comment overflow), R50 (REST-primary / capability-gated GraphQL). New
hardening requirements use the program-allocated band **R100–R115** and new decisions use **D25+**
(PRD 043 Program table); PRD 043 D9/D14 are **referenced**, not restated. Cross-PRD references are written
`PRD 043 RNN`.

## Adopter impact

- **P-A — Default file-store user.** Inert (PRD 043 R1/R3).
- **P-B — Bitbucket host (post-EOL).** Needs a planning store after native Bitbucket issues are removed; the
  **default** is a separate GitHub/GitLab planning project, with Jira as the opt-in path for Jira-standardized
  orgs (D25).
- **P-C — Jira-native org.** Runs planning in its existing Jira project; until PRD 045/046 add Jira
  dev-tracking and planning-graph coverage, 047 alone unlocks the **core** artifact lifecycle (PRD 043).
- **P-D — GitHub/GitLab issue-store user.** Unchanged; Jira is an additional adapter, not a replacement.

## Goals

- Implement a Jira adapter for the PRD 043 `issues.*` verb set (REST-primary), mapping the LCD contract with a
  documented capability/degradation matrix (PRD 043 R31).
- Give Bitbucket and Jira-centric users a supported planning store without native Bitbucket issues.
- Satisfy the PRD 043 R35 canonical-hash and R37 tamper-evidence guarantees for Jira's ADF/wiki rendering, so
  freeze is portable and benign server re-serialization never trips a false tamper failure.

## Non-Goals

- The issue-store contract, identification, freeze, hashing, capability-matrix definition (PRD 043) — 047
  satisfies them, it does not re-specify them.
- Dev-tracking (PRD 045), planning-graph derivation (PRD 046), migration (PRD 044) — these compose with the
  Jira adapter via the PRD 043 contract but are not re-specified or Jira-ported here.
- Bitbucket native issues (intentionally unsupported; EOL 2026-08-20).
- Dictating PRD 043 rollout behavior; the Bitbucket host-fallback guidance is emitted by PRD 043 Phase 1
  (R32b asserts acceptance, it does not own that emission).

## Requirements

### Core carry-forward (owned R32)

- **R32a** — A Jira `issuesProvider` adapter implements the PRD 043 `issues.*` verb set via Jira REST, mapping the LCD contract (title→summary, body→description, comments, open/closed→status category, flat labels→labels) with a documented PRD 043 R31 capability/degradation matrix. `issue-lock` is registered as a **degraded** verb (Jira has no native lock; see R104).
- **R32b** — Bitbucket code repos configure their planning store as either Jira or a separate GitHub/GitLab planning project; native Bitbucket issues are not a supported store. The unset-`issuesProvider` guidance for `host.provider == bitbucket` is emitted by PRD 043 Phase 1; 047 asserts acceptance that the Bitbucket→Jira (and Bitbucket→separate-project) path works end to end.

### Variant, auth, and visibility (R100–R101)

- **R100** — A per-verb Cloud-vs-DC/Server **parity/degradation matrix** (PRD 043 R31) records endpoint, auth, serialization, and capability splits behind a Jira-flavor capability flag, and maps Jira issue links / sub-tasks to PRD 043 R29 edges and the PRD 046 R23 hierarchy projection (consumed, not owned here).
- **R101** — Jira auth uses the dedicated PRD 043 R44 `issues.tokenEnv` (never `host.tokenEnv`); minimum project + write scopes are documented and probed at init (PRD 043 R44). Cloud uses email + API-token; DC/Server **requires** a PAT and **rejects** password/basic auth. The project-visibility probe resolves via the PRD 043 R28/R43 resolver and **fails closed**, refusing and rerouting `private`/`memory` artifacts (to a private Jira project, a separate private GH/GL repo, or the local file-store) — see R105.

### Canonicalization and artifact placement (R102–R103)

- **R102** — The adapter satisfies the PRD 043 R35 canonical-hash contract for Jira: ADF (Cloud) and wiki-markup (DC/Server) descriptions are normalized into the canonical markdown subset, and the freeze hash is computed over the **post-write re-fetched canonical form** (not the submit payload) so benign Jira server re-serialization (smart links, mention expansion, emoji node IDs) is absorbed and does not trip PRD 043 R37 tamper-evidence. Server-normalization drift beyond the canonical subset is classified distinctly from true tamper and fails closed. Secret-scan (PRD 043 R45) runs on the **post-normalization plaintext** before submit. Jira-specific golden vectors include live round-trip and server-mutated-ADF fixtures; the guarantee is the same **contract** as GitHub/GitLab with Jira-specific vectors.
- **R103** — Artifact placement is pinned for Jira's single description field: the description carries the artifact markdown plus the PRD 043 R29 `sw-edges` block and the PRD 043 R42 body marker inside an ADF-safe fenced block; the PRD 043 R13 freeze-record lives in a **write-once custom field or description footer** (not a deletable comment), carries the reserved `sw-freeze-record` marker, and is excluded from canonicalization; PRD 043 R46 overflow uses ordered comments pinned by **immutable comment IDs** in the canonical manifest. A missing freeze-record or deleted overflow comment is classified as a PRD 043 R40 tombstone, not a hash mismatch.

### Lifecycle, privacy, budget, and field hardening (R104–R109)

- **R104** — Freeze is **decoupled from Jira status** (D26): the `sw:frozen` label + content-hash are authoritative for immutability; the status category is read for display and probed for a required workflow constraint (no automation auto-transition of `sw:frozen` issues). An external/automation transition of a frozen issue is a `lifecycle-drift` halt, classified distinctly from a PRD 043 R37 hash mismatch, with operator remediation. `issue-lock` degrades to hash-authoritative tamper-evidence (R32a).
- **R105** — Because Jira has no per-issue privacy, the init probe **rejects** a multi-tenant shared Jira project when any unit resolves `private`/`memory`; the capability matrix marks per-issue privacy unsupported; private/`memory` units require a separate Jira project per visibility tier or are rerouted per PRD 043 R28/R43 (fail-closed on create, not only at init).
- **R106** — A Jira request-budget binding implements PRD 043 R39: Cloud vs DC/Server rate-limit ceilings, JQL pagination caps, and 429 handling **without** reliance on `Retry-After` (exponential backoff + jitter); per-run/per-CI budgets; a partial-page abort mid-refresh fails closed (`deliver-aborted-inconsistent`); resilience fixtures cover 429 exhaustion and partial-page abort.
- **R107** — Lifecycle edges implement PRD 043 R40: issue move / key change (detected via changelog), archived-project `404`/`410`, and issue-type conversion are each classified as distinct tombstone/transfer halt codes with a recovery path, keyed on a stable provider id + project key.
- **R108** — An init **createmeta / field-schema probe** runs per mapped issue type; required custom fields that would block `issue-create` fail closed with a field manifest + admin remediation, or are satisfied by allowlisted configured defaults (PRD 043 R31 degradation) — never a runtime 400 mid-pipeline.
- **R109** — A label degradation ladder is defined: labels (primary) → components (degraded) → an optional configured custom field; the init probe validates label-write permission; the PRD 043 R42 body marker remains authoritative for project isolation regardless of the label surface available.

(R110–R115 reserved for this PRD's band.)

## Technical Requirements

- REST-primary Jira client; Cloud and DC/Server endpoint/auth/serialization variants behind a Jira-flavor
  capability flag (R100).
- Field-mapping table: summary/description/comments/status/labels/components/links/sub-tasks → PRD 043 LCD +
  edges + hierarchy; ADF↔markdown and wiki↔markdown normalization feeding R102 canonicalization; freeze-record
  custom-field/footer placement (R103).
- Init probes: project existence, write scope, label-write permission, createmeta required fields, project
  visibility classification, and workflow auto-transition constraint (R101/R104/R105/R108/R109).
- Budget + lifecycle: PRD 043 R39 ceilings + 429 handling (R106); PRD 043 R40 move/archive/convert detection
  via changelog (R107).
- Capability-matrix entries for the Jira adapter live in `core/providers/issues/CAPABILITIES.md` and are
  registered in `core/sw-reference/capability-index.json` (regenerated via the emitter), including
  unsupported/degraded verbs (`issue-lock`, per-issue privacy).

## Security & Compliance

- **Token scope (PRD 043 R44).** Dedicated `issues.tokenEnv`; min scopes documented + probed at init; DC/Server
  PAT required, password/basic rejected; never reuse `host.tokenEnv`; fixtures token-redacted.
- **Secret-scan (PRD 043 R45).** Runs on post-normalization plaintext (ADF/wiki → canonical) for descriptions,
  comments, overflow chunks, and freeze-record before submit; a token embedded in an ADF node is caught.
- **Visibility fail-closed (PRD 043 R28/R43).** Resolver-driven; refuse + reroute `private`/`memory` on a
  shared/public Jira project at init **and** on create (R105).
- **Tamper-evidence (PRD 043 R37).** On-read hash verification inherited via the cross-provider suite; benign
  server-ADF drift absorbed by R102, true post-freeze edits fail closed and are classified distinctly from
  auth/outage and from `lifecycle-drift` (R104).
- **Isolation (PRD 043 R42).** Body marker authoritative on a shared Jira project; label/title spoofing
  mitigated by the marker, not Jira ACLs (application-layer residual risk).

## Testing Strategy

- **Adapter conformance (R32a/R100):** the PRD 043 cross-provider acceptance suite runs against recorded Jira
  Cloud and DC/Server fixtures; verb mapping and degradation (incl. degraded `issue-lock`) asserted.
- **Canonical hash (R102):** golden vectors prove render-independent freeze hashes for ADF and wiki
  descriptions, **including** a "freeze → server re-serializes ADF → re-fetch → hash stable" scenario (no
  false tamper) and an "out-of-subset edit → fail closed" scenario.
- **Placement (R103):** freeze-record in custom field/footer survives a comment purge; overflow reassembles by
  immutable comment ID; a deleted overflow comment is a tombstone, not a hash mismatch.
- **Freeze vs status (R104):** an external automation transition of a `sw:frozen` issue yields `lifecycle-drift`
  (distinct from R37); `sw:frozen` + hash remain authoritative.
- **Auth/visibility/fields (R101/R105/R108):** missing scope, password-only DC auth, a shared project with a
  private unit (refused + rerouted at create), and a required custom field each fail closed at init/create with
  remediation.
- **Budget/lifecycle (R106/R107):** 429 exhaustion and partial-page abort fail closed; issue move/archive/type
  conversion classified as the correct tombstone/transfer code.
- **Bitbucket guidance (R32b):** `host.provider == bitbucket` with no issues provider emits the
  Jira / separate-planning-project guidance (PRD 043 Phase 1) and never falls back to native Bitbucket issues.
- **Doc-impact fixture:** `run-planning-047-doc-impact-fixtures.sh` asserts per-phase doc updates.

## Success Criteria

1. A Bitbucket + Jira pilot completes author → freeze → deliver on Jira issues for the core artifact lifecycle.
2. A Jira-native team runs planning in its existing Jira project with no GitHub/GitLab planning-repo requirement.
3. The PRD 043 cross-provider acceptance suite passes against Jira Cloud and DC/Server fixtures.
4. Freeze hashes are render-independent and golden-vector-verified, including a server-mutated-ADF round-trip
   that does **not** raise a false tamper failure.
5. Auth, visibility, required-field, and workflow misconfiguration fail closed at init/create with actionable
   remediation; a private unit on a shared Jira project is refused and rerouted.
6. A Bitbucket repo with `issuesProvider` unset receives the separate-planning-project / Jira guidance and
   never falls back to native Bitbucket issues.

## Rollout Plan

Cloud-first; DC/Server gated on validated demand (D25). Per-phase documentation-impact gate backed by
`run-planning-047-doc-impact-fixtures.sh` (precedent PRD 034/035/043). Each phase updates its docs before
shipping (PRD 043 R49).

1. **Jira Cloud adapter + mapping + canonicalization + placement + freeze-decoupling** (R32a, R100 Cloud,
   R102, R103, R104). *Docs:* `core/providers/issues/jira.md` (new) + `core/providers/issues/CAPABILITIES.md`
   (new); cross-ref `core/providers/planning-store/issue-store.md` + `core/providers/planning-store/CAPABILITIES.md`;
   `core/sw-reference/config.schema.json` + `.sw/config.schema.json` + both `workflow.config.example.json`
   (`issuesProvider: jira`, `issues.tokenEnv`, Jira endpoint/flavor keys); `docs/guides/configuration.md`
   (Bitbucket + Jira / issue-store section). *Exit:* Cloud conformance + canonical golden vectors green.
2. **DC/Server variant + auth/visibility/field/budget/lifecycle probes** (R100 DC, R101, R105, R106, R107,
   R108, R109). *Docs:* `core/providers/issues/jira.md` (DC section), `core/commands/sw-init.md` (doctor +
   probe behavior), `core/sw-reference/capability-index.json` (regen via emitter), dist emitter parity
   (`dist/*/providers/issues/`). *Exit:* DC conformance + fail-closed probe tests green.
3. **Bitbucket guidance wiring + acceptance suite + doc-impact gate** (R32b, conformance). *Docs:*
   `core/providers/host/bitbucket.md` (EOL + routing note only), `scripts/test/run-planning-047-doc-impact-fixtures.sh`
   + `core/sw-reference/pr-test-plan.manifest.json`, plus `docs/guides/workflows.md`/`commands.md` Jira notes.
   *Exit:* doc-impact fixture green; Bitbucket + Jira end-to-end.

## Decision Log

- *References (defined in PRD 043, not restated here):* PRD 043 D9 (issues provider decoupled from code host)
  and PRD 043 D14 (Jira as a dependent PRD; R32 namespace) are the governing decisions for this adapter.
- **D25** — The **default** planning store for a Bitbucket host is a separate GitHub/GitLab planning project;
  Jira is the **opt-in** path for Jira-standardized orgs. Ship Jira **Cloud** first with Bitbucket guidance;
  expand to DC/Server only on a validated demand signal (mirrors the PRD 043 MVP checkpoint). The Bitbucket
  EOL premise is validated; the "Jira is the right default" premise is explicitly **not** assumed.
- **D26** — Freeze is decoupled from Jira status: `sw:frozen` label + content-hash are authoritative; status is
  display/probe only; `issue-lock` degrades to hash-authoritative tamper-evidence; an external transition of a
  frozen issue is a distinct `lifecycle-drift` halt.
- **D27** — The freeze hash is computed over the **post-write re-fetched** canonical form so benign Jira
  server re-serialization is absorbed, with Jira-specific golden vectors (live round-trip + server-mutated
  ADF) rather than re-specifying PRD 043 R35.

## Open Questions

None blocking. Resolved during `/sw-tasks` against the PRD 043 R35 canonical contract: the exact ADF↔markdown
(and wiki↔markdown) normalization library and golden-vector corpus; the ADF-safe fence format for the body
marker + `sw-edges`; the freeze-record custom-field vs description-footer choice per Jira flavor; and the
per-project workflow-constraint / status-transition config schema.
