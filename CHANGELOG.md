# Changelog

## [1.6.0](https://github.com/grdavies/shipwright/compare/v1.5.0...v1.6.0) (2026-06-25)


### Features

* **autonomous-orchestration-conductor:** deliver wave ([#73](https://github.com/grdavies/shipwright/issues/73)) ([0ed6e67](https://github.com/grdavies/shipwright/commit/0ed6e671afde2a0da0dd16bd572a64370fd3dd7d))
* **models:** four-tier model tier setup defaults (PRD 008) ([cde20e0](https://github.com/grdavies/shipwright/commit/cde20e0ab8057c8e95bff5b6e152528a05878358))


### Bug Fixes

* **cleanup:** read deliver state from orchestrator worktree ([#75](https://github.com/grdavies/shipwright/issues/75)) ([23f8a9d](https://github.com/grdavies/shipwright/commit/23f8a9dc0486b7e34dd3a702f0ebf95cd5c155b1))
* **cleanup:** skip bogus origin remote ref in enumeration ([#72](https://github.com/grdavies/shipwright/issues/72)) ([7a83a6a](https://github.com/grdavies/shipwright/commit/7a83a6a470b1625a9bb5f658c71f74344afbaf48))
* **deliver:** detect squash-merged terminal PRs; reconcile INDEX ([#74](https://github.com/grdavies/shipwright/issues/74)) ([2d83df8](https://github.com/grdavies/shipwright/commit/2d83df8e1def87d5eb8df82113b72d2b59fe2825))


### Documentation

* post-PRD-007 documentation coverage pass ([#68](https://github.com/grdavies/shipwright/issues/68)) ([07608f8](https://github.com/grdavies/shipwright/commit/07608f8ea2bd9a269856b0f0c0879dbe91951976))
* **prds:** mark PRD 008 complete in index and completion log ([#71](https://github.com/grdavies/shipwright/issues/71)) ([6bcacdb](https://github.com/grdavies/shipwright/commit/6bcacdbbf94efd0c51bb18fd6d983bcdc6bb99ec))

## [Unreleased]


### Features
* merge phase per-orchestrator-audit-adoption-enumeration-s-m into feat/autonomous-orchestration-conductor (08cf681) <!-- sw-deliver:per-orchestrator-audit-adoption-enumeration-s-m -->
* merge phase brainstorm-prd-frontmatter-traceability-s-m into feat/autonomous-orchestration-conductor (84e09d0) <!-- sw-deliver:brainstorm-prd-frontmatter-traceability-s-m -->
* merge phase conductor-contract-config-knobs-m into feat/autonomous-orchestration-conductor (da8d0e5) <!-- sw-deliver:conductor-contract-config-knobs-m -->
* merge phase autonomous-self-continuation-self-wake-m-l into feat/autonomous-orchestration-conductor (240f2fb) <!-- sw-deliver:autonomous-self-continuation-self-wake-m-l -->
* merge phase legitimate-halts-consolidated-reports-liveness-m into feat/autonomous-orchestration-conductor (076397f) <!-- sw-deliver:legitimate-halts-consolidated-reports-liveness-m -->
* merge phase conductor-level-parallel-dispatch-safety-under-concurrency-l into feat/autonomous-orchestration-conductor (9114383) <!-- sw-deliver:conductor-level-parallel-dispatch-safety-under-concurrency-l -->
* merge phase living-doc-currency-hardening-m into feat/autonomous-orchestration-conductor (b830645) <!-- sw-deliver:living-doc-currency-hardening-m -->
* merge phase pilot-validation-surface-docs-emitter-m into feat/autonomous-orchestration-conductor (af575a7) <!-- sw-deliver:pilot-validation-surface-docs-emitter-m -->
* merge phase adopter-facing-readme-user-guide-refresh-s-m into feat/autonomous-orchestration-conductor (e239604) <!-- sw-deliver:adopter-facing-readme-user-guide-refresh-s-m -->
* merge phase sw-doc-post-freeze-command-surface-confirm-prominence-s-m into feat/orchestrator-ux-and-doc-polish (9b1c6a1) <!-- sw-deliver:sw-doc-post-freeze-command-surface-confirm-prominence-s-m -->
* merge phase sw-cleanup-agent-driven-confirm-s into feat/orchestrator-ux-and-doc-polish (8e2e8af) <!-- sw-deliver:sw-cleanup-agent-driven-confirm-s -->
* merge phase optional-repo-link-check-script-wiring-m into feat/orchestrator-ux-and-doc-polish (6756722) <!-- sw-deliver:optional-repo-link-check-script-wiring-m -->
* merge phase config-driven-per-agent-tiers-resolver-agent-m into feat/model-tier-runtime-binding (fe74a29) <!-- sw-deliver:config-driven-per-agent-tiers-resolver-agent-m -->
* merge phase dispatch-preflight-parent-floor-m into feat/model-tier-runtime-binding (c5f13c7) <!-- sw-deliver:dispatch-preflight-parent-floor-m -->
* merge phase rule-skill-rewrite-to-call-the-preflight-s-m into feat/model-tier-runtime-binding (be9f908) <!-- sw-deliver:rule-skill-rewrite-to-call-the-preflight-s-m -->
* merge phase optional-pre-tool-hook-feasibility-gated-m into feat/model-tier-runtime-binding (94778b5) <!-- sw-deliver:optional-pre-tool-hook-feasibility-gated-m -->
* merge phase fixtures-docs-dist-propagation-m into feat/model-tier-runtime-binding (134e59d) <!-- sw-deliver:fixtures-docs-dist-propagation-m -->
* merge phase single-sourced-test-plan-set-classification-s-m into feat/pr-test-plan-ci-enforcement (ffdc2b8) <!-- sw-deliver:single-sourced-test-plan-set-classification-s-m -->
* merge phase ci-workflow-jobs-pr-template-m into feat/pr-test-plan-ci-enforcement (0068d4d) <!-- sw-deliver:ci-workflow-jobs-pr-template-m -->
* merge phase stabilize-gate-integration-s-m into feat/pr-test-plan-ci-enforcement (e47d29f) <!-- sw-deliver:stabilize-gate-integration-s-m -->
* merge phase docs-dist-fixtures-s-m into feat/pr-test-plan-ci-enforcement (a16b106) <!-- sw-deliver:docs-dist-fixtures-s-m -->
* merge phase new-sw-retrospective-command-internal-phase-dispatch-m into feat/retrospective-command-consolidation (90c7566) <!-- sw-deliver:new-sw-retrospective-command-internal-phase-dispatch-m -->
* merge phase deprecated-aliases-rename-propagation-m into feat/retrospective-command-consolidation (7d90846) <!-- sw-deliver:deprecated-aliases-rename-propagation-m -->
* merge phase autonomy-knob-preserved-semantics-conductor-single-source-m into feat/retrospective-command-consolidation (d489c1c) <!-- sw-deliver:autonomy-knob-preserved-semantics-conductor-single-source-m -->
* merge phase docs-dist-fixtures-m into feat/retrospective-command-consolidation (9adda52) <!-- sw-deliver:docs-dist-fixtures-m -->
* merge phase persona-agent-file-taxonomy-s into feat/documentation-impact-review-persona (26fa263) <!-- sw-deliver:persona-agent-file-taxonomy-s -->
* merge phase registry-selection-and-output-contract-m into feat/documentation-impact-review-persona (735ac75) <!-- sw-deliver:registry-selection-and-output-contract-m -->
* merge phase tier-routing-living-doc-complementarity-s into feat/documentation-impact-review-persona (15aa134) <!-- sw-deliver:tier-routing-living-doc-complementarity-s -->
* merge phase docs-dist-fixtures-m into feat/documentation-impact-review-persona (32d6b75) <!-- sw-deliver:docs-dist-fixtures-m -->
* merge phase trust-verify-sw-init-project-type-detection-fixed-presets-setup-write-unconfigured-signal-rename-configurator-version-stamp-l into feat/generic-repo-portability (8492be7) <!-- sw-deliver:trust-verify-sw-init-project-type-detection-fixed-presets-setup-write-unconfigured-signal-rename-configurator-version-stamp-l -->
* merge phase sot-resolver-config-schema-defaults-m into feat/memory-source-of-truth (3493df3) <!-- sw-deliver:sot-resolver-config-schema-defaults-m -->
* merge phase always-committed-redacted-snapshot-offline-safe-freeze-ci-m into feat/memory-source-of-truth (e04c8ef) <!-- sw-deliver:always-committed-redacted-snapshot-offline-safe-freeze-ci-m -->
* merge phase pointer-inversion-supersede-reconcile-m into feat/memory-source-of-truth (076599f) <!-- sw-deliver:pointer-inversion-supersede-reconcile-m -->
* merge phase compound-sot-branch-audit-conflict-migration-m into feat/memory-source-of-truth (3dea6f3) <!-- sw-deliver:compound-sot-branch-audit-conflict-migration-m -->
* merge phase docs-dist-fixtures-m into feat/memory-source-of-truth (e812958) <!-- sw-deliver:docs-dist-fixtures-m -->
* merge phase freeze-time-commit-safety-m into feat/deliver-concurrency-and-freeze-safety (da44ffb) <!-- sw-deliver:freeze-time-commit-safety-m -->
* merge phase scoped-deliver-state-lock-resolver-l into feat/deliver-concurrency-and-freeze-safety (099156f) <!-- sw-deliver:scoped-deliver-state-lock-resolver-l -->
* merge phase concurrent-run-index-enumeration-serialization-m into feat/deliver-concurrency-and-freeze-safety (5f33bee) <!-- sw-deliver:concurrent-run-index-enumeration-serialization-m -->
* merge phase sw-deliver-v1-deferrals-l into feat/deliver-concurrency-and-freeze-safety (9269ef7) <!-- sw-deliver:sw-deliver-v1-deferrals-l -->
* merge phase autonomous-terminal-delivery-amendment-a1-l into feat/deliver-concurrency-and-freeze-safety (eeb784c) <!-- sw-deliver:autonomous-terminal-delivery-amendment-a1-l -->
* merge phase fixtures-docs-dist-propagation-m into feat/deliver-concurrency-and-freeze-safety (9a53494) <!-- sw-deliver:fixtures-docs-dist-propagation-m -->
* merge phase binding-enforcement-foundation-m into feat/pervasive-subagent-delegation (6e97060) <!-- sw-deliver:binding-enforcement-foundation-m -->
* merge phase deliver-reliability-hard-gate-before-phase-3-l into feat/pervasive-subagent-delegation (b3d0c06) <!-- sw-deliver:deliver-reliability-hard-gate-before-phase-3-l -->
* merge phase per-orchestrator-adoption-m into feat/pervasive-subagent-delegation (721319f) <!-- sw-deliver:per-orchestrator-adoption-m -->
* merge phase docs-dist-fixtures-m into feat/pervasive-subagent-delegation (99bb9a7) <!-- sw-deliver:docs-dist-fixtures-m -->
* merge phase sot-resolver-config-schema-defaults-m into feat/memory-source-of-truth (312ee05) <!-- sw-deliver:sot-resolver-config-schema-defaults-m -->
* merge phase always-committed-redacted-snapshot-offline-safe-freeze-ci-m into feat/memory-source-of-truth (89f52ca) <!-- sw-deliver:always-committed-redacted-snapshot-offline-safe-freeze-ci-m -->
* merge phase pointer-inversion-supersede-reconcile-m into feat/memory-source-of-truth (ed509ad) <!-- sw-deliver:pointer-inversion-supersede-reconcile-m -->
* merge phase compound-sot-branch-audit-conflict-migration-m into feat/memory-source-of-truth (c16c11e) <!-- sw-deliver:compound-sot-branch-audit-conflict-migration-m -->
* merge phase docs-dist-fixtures-m into feat/memory-source-of-truth (4db9bef) <!-- sw-deliver:docs-dist-fixtures-m -->
* merge phase memory-preflight-entry-obligation-m into feat/pre-work-memory-search-gate (fd42f46) <!-- sw-deliver:memory-preflight-entry-obligation-m -->
* merge phase search-record-degrade-open-breadcrumb-m into feat/pre-work-memory-search-gate (617b36f) <!-- sw-deliver:search-record-degrade-open-breadcrumb-m -->
* merge phase enforcement-dispatch-inheritance-m into feat/pre-work-memory-search-gate (8b7207a) <!-- sw-deliver:enforcement-dispatch-inheritance-m -->
* merge phase docs-dist-fixtures-m into feat/pre-work-memory-search-gate (635ec0e) <!-- sw-deliver:docs-dist-fixtures-m -->
* merge phase manifest-frontmatter-schema-contract-m into feat/capability-manifest-and-selector (e672065) <!-- sw-deliver:manifest-frontmatter-schema-contract-m -->
* merge phase generated-capability-index-freshness-gates-m into feat/capability-manifest-and-selector (a499a64) <!-- sw-deliver:generated-capability-index-freshness-gates-m -->
* merge phase precedence-policy-author-time-lint-m into feat/capability-manifest-and-selector (74a55cd) <!-- sw-deliver:precedence-policy-author-time-lint-m -->
* merge phase deterministic-selector-signal-context-l into feat/capability-manifest-and-selector (cbe18d5) <!-- sw-deliver:deterministic-selector-signal-context-l -->
* merge phase run-log-surfacing-s into feat/capability-manifest-and-selector (4235f06) <!-- sw-deliver:run-log-surfacing-s -->
* merge phase trust-boundary-execution-chokepoint-kernel-hook-pinning-m into feat/capability-manifest-and-selector (dd8a578) <!-- sw-deliver:trust-boundary-execution-chokepoint-kernel-hook-pinning-m -->
* merge phase migration-with-parity-shadow-cutover-call-site-map-l into feat/capability-manifest-and-selector (412e81d) <!-- sw-deliver:migration-with-parity-shadow-cutover-call-site-map-l -->
* merge phase documentation-emitter-propagation-freshness-m into feat/capability-manifest-and-selector (6dd263b) <!-- sw-deliver:documentation-emitter-propagation-freshness-m -->
* merge phase single-sourced-kernel-classification-canonical-chain-source-l into feat/kernel-classification-and-plan-validation (5b0fa22) <!-- sw-deliver:single-sourced-kernel-classification-canonical-chain-source-l -->
* merge phase guidelines-artifact-floor-harness-reuse-m into feat/kernel-classification-and-plan-validation (ef5794e) <!-- sw-deliver:guidelines-artifact-floor-harness-reuse-m -->
* merge phase plan-validation-gate-schemas-rejection-breaker-l into feat/kernel-classification-and-plan-validation (cb4ab30) <!-- sw-deliver:plan-validation-gate-schemas-rejection-breaker-l -->
* merge phase two-tier-persist-deterministic-step-driver-lifecycle-l into feat/kernel-classification-and-plan-validation (78eb9e0) <!-- sw-deliver:two-tier-persist-deterministic-step-driver-lifecycle-l -->
* merge phase orchestration-planpolicy-flag-definition-resume-semantics-m into feat/kernel-classification-and-plan-validation (ef45df3) <!-- sw-deliver:orchestration-planpolicy-flag-definition-resume-semantics-m -->
* merge phase safety-invariant-parity-fixtures-proposed-cross-cutting-m into feat/kernel-classification-and-plan-validation (d2f4d9e) <!-- sw-deliver:safety-invariant-parity-fixtures-proposed-cross-cutting-m -->
* merge phase docs-emitter-propagation-freshness-call-site-map-m into feat/kernel-classification-and-plan-validation (5151657) <!-- sw-deliver:docs-emitter-propagation-freshness-call-site-map-m -->
* merge phase dependency-gate-deliver-pilot-wiring-wire-only-e2e-m into feat/deliver-plan-policy-pilot (a6c254d) <!-- sw-deliver:dependency-gate-deliver-pilot-wiring-wire-only-e2e-m -->
* merge phase intra-phase-fan-out-no-nesting-decision-logging-m into feat/deliver-plan-policy-pilot (3ce9fd7) <!-- sw-deliver:intra-phase-fan-out-no-nesting-decision-logging-m -->
* merge phase driver-enforced-budgets-clean-halt-integrity-m into feat/deliver-plan-policy-pilot (be5a271) <!-- sw-deliver:driver-enforced-budgets-clean-halt-integrity-m -->
* merge phase benefit-metric-capture-decision-rule-m into feat/deliver-plan-policy-pilot (2ad6637) <!-- sw-deliver:benefit-metric-capture-decision-rule-m -->
* merge phase deliver-scoped-plan-surfacing-s into feat/deliver-plan-policy-pilot (56c64f9) <!-- sw-deliver:deliver-scoped-plan-surfacing-s -->
* merge phase docs-emitter-propagation-freshness-m into feat/deliver-plan-policy-pilot (49523b8) <!-- sw-deliver:docs-emitter-propagation-freshness-m -->
* merge phase host-adapter-rate-limit-foundation-l into feat/git-host-portability-and-workflow-standardization (e2696c2) <!-- sw-deliver:host-adapter-rate-limit-foundation-l -->
* merge phase git-workflow-skill-docs-branch-standardization-l into feat/git-host-portability-and-workflow-standardization (22f8b88) <!-- sw-deliver:git-workflow-skill-docs-branch-standardization-l -->
* merge phase gitlab-bitbucket-adapters-pr-automation-fixes-l into feat/git-host-portability-and-workflow-standardization (71fd1ad) <!-- sw-deliver:gitlab-bitbucket-adapters-pr-automation-fixes-l -->
* merge phase completeness-unification-conductor-terminal-clause-m into feat/deliver-terminal-finalization-robustness (671d2ba) <!-- sw-deliver:completeness-unification-conductor-terminal-clause-m -->
* merge phase phase-status-write-read-path-hardening-m into feat/deliver-terminal-finalization-robustness (9af6c42) <!-- sw-deliver:phase-status-write-read-path-hardening-m -->
* merge phase contributing-factor-resolution-m into feat/deliver-terminal-finalization-robustness (d6fc31e) <!-- sw-deliver:contributing-factor-resolution-m -->
* merge phase planning-unit-schema-validator-stub-enum-l into feat/planning-feedback-lifecycle (3de48dc) <!-- sw-deliver:planning-unit-schema-validator-stub-enum-l -->
* merge phase tokenizer-phase-a-adoption-on-legacy-docs-prds-paths-l into feat/planning-feedback-lifecycle (b7c520a) <!-- sw-deliver:tokenizer-phase-a-adoption-on-legacy-docs-prds-paths-l -->
* merge phase config-driven-path-resolution-helper-m into feat/planning-feedback-lifecycle (bb2d3e4) <!-- sw-deliver:config-driven-path-resolution-helper-m -->
* merge phase deterministic-dual-region-index-generator-region-integrity-hook-l into feat/planning-feedback-lifecycle (a143068) <!-- sw-deliver:deterministic-dual-region-index-generator-region-integrity-hook-l -->
* merge phase migration-tool-held-lock-redirect-map-verification-fixture-l into feat/planning-feedback-lifecycle (4e07f38) <!-- sw-deliver:migration-tool-held-lock-redirect-map-verification-fixture-l -->
* merge phase atomic-cutover-phase-b-relocation-supersession-privacy-projections-kill-criteria-l into feat/planning-feedback-lifecycle (e544b75) <!-- sw-deliver:atomic-cutover-phase-b-relocation-supersession-privacy-projections-kill-criteria-l -->
* merge phase documentation-currency-dist-propagation-no-regression-memory-guardrails-l into feat/planning-feedback-lifecycle (3ea0b85) <!-- sw-deliver:documentation-currency-dist-propagation-no-regression-memory-guardrails-l -->
* merge phase committed-in-flight-signal-writer-l into feat/planning-feedback-lifecycle (e5f9234) <!-- sw-deliver:committed-in-flight-signal-writer-l -->
* merge phase self-heal-staleness-ttl-escape-hatch-m into feat/planning-feedback-lifecycle (19a46ba) <!-- sw-deliver:self-heal-staleness-ttl-escape-hatch-m -->
* merge phase migration-bridge-backfill-s into feat/planning-feedback-lifecycle (c3e7c06) <!-- sw-deliver:migration-bridge-backfill-s -->
* merge phase shared-authoring-guard-preflight-handoff-route-m into feat/planning-feedback-lifecycle (be102df) <!-- sw-deliver:shared-authoring-guard-preflight-handoff-route-m -->
* merge phase completed-unit-immutability-l into feat/planning-feedback-lifecycle (2dc12d2) <!-- sw-deliver:completed-unit-immutability-l -->
* merge phase doc-impact-acceptance-criteria-m into feat/planning-feedback-lifecycle (181a0d1) <!-- sw-deliver:doc-impact-acceptance-criteria-m -->
* merge phase emitter-dist-parity-s into feat/planning-feedback-lifecycle (415a998) <!-- sw-deliver:emitter-dist-parity-s -->
* merge phase ship-single-flight-r1-r5-l into feat/delivery-conductor-concurrency-and-remediation-robustness (7152aa8) <!-- sw-deliver:ship-single-flight-r1-r5-l -->
* merge phase regression-remediation-routing-r6-r8-m into feat/delivery-conductor-concurrency-and-remediation-robustness (86b950f) <!-- sw-deliver:regression-remediation-routing-r6-r8-m -->
* merge phase terminal-status-integrity-recovery-r13-r17-l into feat/delivery-conductor-concurrency-and-remediation-robustness (d98d1da) <!-- sw-deliver:terminal-status-integrity-recovery-r13-r17-l -->
* merge phase parallel-merge-batch-safety-r9-r12-l into feat/delivery-conductor-concurrency-and-remediation-robustness (a7fa461) <!-- sw-deliver:parallel-merge-batch-safety-r9-r12-l -->
* merge phase cross-cutting-invariants-ci-enforcement-dogfood-r18-r22-m into feat/delivery-conductor-concurrency-and-remediation-robustness (c52e97e) <!-- sw-deliver:cross-cutting-invariants-ci-enforcement-dogfood-r18-r22-m -->
* merge phase lifecycle-enum-pure-graph-module-substrate-l into feat/planning-feedback-lifecycle (7f754e8) <!-- sw-deliver:lifecycle-enum-pure-graph-module-substrate-l -->
* merge phase deterministic-maintenance-reconciler-l into feat/planning-feedback-lifecycle (cf7628f) <!-- sw-deliver:deterministic-maintenance-reconciler-l -->
* merge phase scheduler-sw-deliver-dependency-gate-m into feat/planning-feedback-lifecycle (8038e93) <!-- sw-deliver:scheduler-sw-deliver-dependency-gate-m -->
* merge phase supersession-absorption-edge-effects-m into feat/planning-feedback-lifecycle (a1553a9) <!-- sw-deliver:supersession-absorption-edge-effects-m -->
* merge phase atomic-cutover-one-commit-with-031-phase-b-032-m into feat/planning-feedback-lifecycle (6e866b9) <!-- sw-deliver:atomic-cutover-one-commit-with-031-phase-b-032-m -->
* merge phase emitter-dist-parity-s into feat/planning-feedback-lifecycle (27b08e3) <!-- sw-deliver:emitter-dist-parity-s -->
* merge phase operator-doc-acceptance-criteria-033-owned-m into feat/planning-feedback-lifecycle (b1b168e) <!-- sw-deliver:operator-doc-acceptance-criteria-033-owned-m -->
* merge phase post-merge-index-reconcile-safety-completion-finalize-chokepoint-amendment-a1-m into feat/planning-feedback-lifecycle (9f2f1cc) <!-- sw-deliver:post-merge-index-reconcile-safety-completion-finalize-chokepoint-amendment-a1-m -->
* merge phase sot-manifest-copy-to-core-hardening-m into feat/build-chain-source-of-truth (2fcabd4) <!-- sw-deliver:sot-manifest-copy-to-core-hardening-m -->
* merge phase ci-verify-test-wiring-s into feat/build-chain-source-of-truth (f9e9195) <!-- sw-deliver:ci-verify-test-wiring-s -->
## [1.5.0](https://github.com/grdavies/shipwright/compare/v1.4.0...v1.5.0) (2026-06-25)


### Features

* caveman command loading (PRD 006) ([#65](https://github.com/grdavies/shipwright/issues/65)) ([b8145b2](https://github.com/grdavies/shipwright/commit/b8145b262eb523e20045706b8c8737d51269ac3f))
* prd 007 deliver autonomy hardening ([#67](https://github.com/grdavies/shipwright/issues/67)) ([e18ec99](https://github.com/grdavies/shipwright/commit/e18ec99c325f26972c156cbff0183c9577e60e49))

## [1.4.0](https://github.com/grdavies/shipwright/compare/v1.3.1...v1.4.0) (2026-06-25)


### Features

* native local review panel (PRD 005) ([#61](https://github.com/grdavies/shipwright/issues/61)) ([d986c3a](https://github.com/grdavies/shipwright/commit/d986c3a25b96eccf480f23aae98bba98b79605e2))


### Documentation

* reconcile PRD status and log PRD 005 completion ([#63](https://github.com/grdavies/shipwright/issues/63)) ([8d437c7](https://github.com/grdavies/shipwright/commit/8d437c79032d109975c9e60142dc5324dbadf68f))

## [1.3.1](https://github.com/grdavies/shipwright/compare/v1.3.0...v1.3.1) (2026-06-25)


### Documentation

* restructure README and migrate guides to docs/guides/ ([1297dc9](https://github.com/grdavies/shipwright/commit/1297dc9a8b36420145e2e37f02f280767a51ee2b))

## [1.3.0](https://github.com/grdavies/shipwright/compare/v1.2.2...v1.3.0) (2026-06-25)


### Features

* **wave-phase-orchestrator:** deliver phase-mode orchestrator (PRD 004) ([#57](https://github.com/grdavies/shipwright/issues/57)) ([87ba358](https://github.com/grdavies/shipwright/commit/87ba358b63af9bd6a184bad987a7779e1deb4715))

## [1.2.2](https://github.com/grdavies/shipwright/compare/v1.2.1...v1.2.2) (2026-06-25)


### Documentation

* freeze PRD 004, reconcile INDEX status, fix reconcile-status ([#41](https://github.com/grdavies/shipwright/issues/41)) ([07d853e](https://github.com/grdavies/shipwright/commit/07d853e6fba362a35e117622b55a95c48c3ead04))

## [1.2.1](https://github.com/grdavies/shipwright/compare/v1.2.0...v1.2.1) (2026-06-25)


### Documentation

* track PRDs in git and document /sw-deliver in README ([#39](https://github.com/grdavies/shipwright/issues/39)) ([addc08f](https://github.com/grdavies/shipwright/commit/addc08ffe3bb738c59ce228a6877dc6083ae6970))

## [1.2.0](https://github.com/grdavies/shipwright/compare/v1.1.0...v1.2.0) (2026-06-24)


### Features

* **onboarding:** first-run onboarding UX (PRD 002) ([ad196d7](https://github.com/grdavies/shipwright/commit/ad196d72b43f0538d61bb629cf7682b33b488b45))


### Documentation

* add user-facing README and documentation guides ([#28](https://github.com/grdavies/shipwright/issues/28)) ([f2d7bd0](https://github.com/grdavies/shipwright/commit/f2d7bd0a8433c491c514037f2ac2e9fb0761426f))

## [1.1.0](https://github.com/grdavies/shipwright/compare/v1.0.0...v1.1.0) (2026-06-24)


### Features

* rename install script and harden install experience ([#22](https://github.com/grdavies/shipwright/issues/22)) ([8e518da](https://github.com/grdavies/shipwright/commit/8e518dab9a791823ea3125dfdaf9ba3ade4a86d6))


### Bug Fixes

* **ci:** match BREAKING CHANGES section header only ([#26](https://github.com/grdavies/shipwright/issues/26)) ([1d656e3](https://github.com/grdavies/shipwright/commit/1d656e39242371ed56edb527c2d7c55ac6c80405))
* **ci:** scope breaking-release check to current changelog section ([#24](https://github.com/grdavies/shipwright/issues/24)) ([99b80ef](https://github.com/grdavies/shipwright/commit/99b80ef19489f801c7ab1e8b01909f365be2d335))

## [1.0.0](https://github.com/grdavies/shipwright/compare/v0.1.0...v1.0.0) (2026-06-24)


### ⚠ BREAKING CHANGES

* complete deferred internal rename to Shipwright conventions ([#20](https://github.com/grdavies/shipwright/issues/20))
* rename user surface from pf- to sw- ([#18](https://github.com/grdavies/shipwright/issues/18))

### Features

* complete deferred internal rename to Shipwright conventions ([#20](https://github.com/grdavies/shipwright/issues/20)) ([5e1d4b0](https://github.com/grdavies/shipwright/commit/5e1d4b0366cf9da5de0943ee7a6a40f7f00dbe50))
* rename user surface from pf- to sw- ([#18](https://github.com/grdavies/shipwright/issues/18)) ([6fbba47](https://github.com/grdavies/shipwright/commit/6fbba47640f452335fd5274a233269ad2b932d7d))

## [0.1.0](https://github.com/grdavies/shipwright/compare/v0.1.0...v0.1.0) (2026-06-24)

### Features

* initial shipwright plugin scaffold and multi-platform emitters
