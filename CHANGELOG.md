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
