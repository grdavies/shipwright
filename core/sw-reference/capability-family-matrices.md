# Capability family matrices

Documentation-only projection of kernel and registry capability families (PRD 270 R8).
Generated from `core/sw-reference/kernel-classification.json` and `core/sw-reference/capability-registry.json` via `scripts/capability_docs.py` — do not edit by hand.

## Model tiers

| Tier | Commands | Agents | Skills |
| --- | ---: | ---: | ---: |
| `cheap` | 22 | 7 | 13 |
| `build` | 6 | 8 | 6 |
| `mid` | 7 | 10 | 5 |
| `deep` | 4 | 4 | 3 |

## Graph node kinds

| Kind | Shadow policy |
| --- | --- |
| `barrier` | read-only |
| `command` | mutating |
| `convergence-loop` | mutating |
| `gate` | read-only |
| `router` | read-only |
| `transform` | read-only |
| `verifier` | read-only |

## Artifact schemas

| Schema | API version | Path |
| --- | --- | --- |
| `workflow-graph` | `shipwright.dev/v1alpha1` | `scripts/graph/schema/workflow_graph.schema.json` |
| `node-spec` | `shipwright.dev/v1alpha1` | `scripts/graph/schema/node_spec.schema.json` |

## Command catalog

| Step | Phase type | Required |
| --- | --- | --- |
| `enrich` | `debug` | no |
| `memory-prework` | `debug` | yes |
| `normalize` | `debug` | yes |
| `rca` | `debug` | yes |
| `rca-human-decision-halt` | `debug` | yes |
| `record` | `debug` | yes |
| `route` | `debug` | yes |
| `route-confirm-halt` | `debug` | yes |
| `triage` | `debug` | yes |
| `afterTasks-checkpoint` | `doc` | yes |
| `doc-review-halt-gated-auto` | `doc` | no |
| `doc-review-halt-manual` | `doc` | no |
| `spec-rigor` | `doc` | yes |
| `sw-brainstorm` | `doc` | no |
| `sw-doc-review` | `doc` | yes |
| `sw-freeze` | `doc` | yes |
| `sw-prd` | `doc` | yes |
| `sw-tasks` | `doc` | yes |
| `sw-triage` | `doc` | yes |
| `execute-fan-out` | `execute` | yes |
| `execute-integrate` | `execute` | yes |
| `execute-plan-validate` | `execute` | yes |
| `execute-terminal-gate` | `execute` | yes |
| `dedup` | `feedback` | yes |
| `handoff` | `feedback` | yes |
| `hook-trigger-halt` | `feedback` | no |
| `human-confirm-halt` | `feedback` | yes |
| `redact` | `feedback` | yes |
| `gap-check` | `ship` | no |
| `sw-commit` | `ship` | yes |
| `sw-execute` | `ship` | yes |
| `sw-pr` | `ship` | yes |
| `sw-ready` | `ship` | yes |
| `sw-review` | `ship` | no |
| `sw-simplify` | `ship` | no |
| `sw-stabilize` | `ship` | yes |
| `sw-tmp-clean` | `ship` | yes |
| `sw-tmp-init` | `ship` | yes |
| `sw-verify` | `ship` | yes |
| `sw-watch-ci` | `ship` | yes |

## Workflow template versions

Library version: **1**
 (`.sw/workflows`).

| Template | Library version | Path |
| --- | ---: | --- |
| `lock` | 1 | `.sw/workflows/lock.json` |

## Registry families (planning + issues)

See `CAPABILITIES.md` for shipped/deferred rows derived from `capability-registry.json`.

- `issues.providers`: `github-issues`, `jira`, `gitlab-issues`, `linear`, `none`
- `planning-store.backends`: `in-repo-public`, `local-synced`, `memory`, `issue-store`, `private-repo`, `encryption-at-rest`
- `workflow.detectorCoverage`: 
- `workflow.detectors`: `workflow.detector.migration`, `workflow.detector.auth`, `workflow.detector.api`, `workflow.detector.supply-chain`
- `workflow.requiredCapabilities`: `workflow.capability.migration-validation`, `workflow.capability.security-auth-review`, `workflow.capability.api-compatibility`, `workflow.capability.dependency-supply-chain`, `workflow.capability.standard-review`
