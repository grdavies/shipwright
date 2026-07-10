id: tasks-061-planning-store-interface-architecture
type: tasks
status: draft
title: Tasks — PRD 061 Planning-store interface architecture
visibility: public
prd: docs/prds/061-planning-store-interface-architecture/061-prd-planning-store-interface-architecture.md
# Tasks — PRD 061 Planning-store interface architecture

## Relevant Files

- `scripts/planning_store.py`
- `scripts/planning_hierarchy.py`
- `scripts/planning_progress.py`
- `scripts/planning_gap_capture.py`
- `scripts/planning_canonical.py`
- `scripts/wave_living_docs.py`
- `scripts/docs-currency-gate.py`
- `scripts/reconcile_lib.py`
- `scripts/_sw/completion_log.py`
- `core/providers/issues/CAPABILITIES.md`
- `core/sw-reference/planning-deliver-parity-matrix.md`
- `core/sw-reference/config.schema.json`
- `README.md`

## Tasks

### 1. `facade-living-doc-ban` — Facade + living-doc write ban (MVP) (R1–R5, R2a, R3a)

- [ ] 1.1 Define facade API and IssuesClient allowlist; fail closed on workflow bypass (R1, R2, R2a)
  - **File:** `scripts/planning_store.py`
  - **Expected:** Documented facade ops; static/import conformance fails when workflow scripts import IssuesClient directly
  - **R-IDs:** R1, R2, R2a
- [ ] 1.2 Route living-docs/completion/reconcile writers behind facade; doctor fails on dirty banned-path mutations (R3, R4, R5)
  - **File:** `scripts/wave_living_docs.py`
  - **Expected:** No new COMPLETION-LOG/INDEX/GAP-BACKLOG mutations under issue-store; living-status reads store evidence
  - **R-IDs:** R3, R4, R5
- [ ] 1.3 Doctor + completion_log/reconcile_lib fail-closed on dirty banned writes (R3)
  - **File:** `scripts/planning_store.py`
  - **Expected:** Doctor pass on legacy tracked clean tree; fail on dirty banned-path write
  - **R-IDs:** R3
- [ ] 1.4 Ship R3a cleanup command with legacy vs newly-written classification (R3a)
  - **File:** `scripts/planning_store.py`
  - **Expected:** Idempotent cleanup counts; code-repo scope under separate-project
  - **R-IDs:** R3a

### 2. `progress-no-phase-mint` — Progress model + no phase mint (MVP) (R6–R9, R8a, R24)

- [ ] 2.1 Remove default GitHub per-phase issue mint; parent progress via facade (R6, R7, R8)
  - **File:** `scripts/planning_hierarchy.py`
  - **Expected:** Multi-phase provision creates no phase peer issues by default
  - **R-IDs:** R6, R7, R8
- [ ] 2.2 Wire planning_progress to facade parent updates; opt-in hierarchy off (R6, R8)
  - **File:** `scripts/planning_progress.py`
  - **Expected:** Phase done updates parent labels/checkboxes; no issue_create for phases
  - **R-IDs:** R6, R8
- [ ] 2.3 Migrate in-flight minted phase issues; align 060/gap-112 closure (R8a)
  - **File:** `scripts/planning_store.py`
  - **Expected:** Pre-061 minted phases closed/relabeled; no orphans after complete
  - **R-IDs:** R8a
- [ ] 2.4 Once-per-run hierarchy/projection apply with cached reads (R9)
  - **File:** `scripts/planning_progress.py`
  - **Expected:** Second provision no-op; cached read budget held
  - **R-IDs:** R9
- [ ] 2.5 Include tasks/progress in discover/graph surfaces (R24)
  - **File:** `scripts/planning_discover.py`
  - **Expected:** Tasks units visible to discover/graph queries
  - **R-IDs:** R24

### 3. `github-projects-matrix` — GitHub Projects v2 + matrix (R10–R15, R11a, R11b, R29a)

- [x] 3.1 Implement Projects v2 client + config/schema/scopes/budgets (R11, R11a)
  - **File:** `scripts/planning_store.py`
  - **Expected:** Idempotent upsert; missing scope → projection-unavailable degrade (not deliver hard-fail)
  - **R-IDs:** R11, R11a
- [x] 3.2 CAPABILITIES + config.schema + example for Projects projection (R11a, R10)
  - **File:** `core/providers/issues/CAPABILITIES.md`
  - **Expected:** Required `project` scope and discovery keys documented
  - **R-IDs:** R11a, R10
- [x] 3.3 PO browse acceptance walkthrough + R29a cutover gate (R11b, R29a)
  - **File:** `docs/guides/workflows.md`
  - **Expected:** Four R11 questions answerable from Projects UI; living-doc ban gated
  - **R-IDs:** R11b, R29a
- [x] 3.4 Publish operator projection matrix + parity updates (R10, R12, R13, R14, R15)
  - **File:** `core/sw-reference/planning-deliver-parity-matrix.md`
  - **Expected:** Rows for github/jira/gitlab-target/in-repo-public/none + linear/notion patterns
  - **R-IDs:** R10, R12, R13, R14, R15

### 4. `gap-enrichment-frontmatter` — Gap enrichment + frontmatter hybrid (R17–R22, R17a)

- [ ] 4.1 Durable gap draft inbox + authoritative enrichment gate + feedback auto-fill (R17, R17a)
  - **File:** `scripts/planning_gap_capture.py`
  - **Expected:** Stub put fails; Problem+Context required; Related/Next auto-fill for feedback
  - **R-IDs:** R17, R17a
- [ ] 4.2 Hybrid frontmatter operator bodies + lazy migrate/backfill (R20, R21)
  - **File:** `scripts/planning_canonical.py`
  - **Expected:** Operator body without raw YAML; get retains canonical; backfill idempotent
  - **R-IDs:** R20, R21
- [ ] 4.3 Expand structural projection keys within budgets (R22)
  - **File:** `scripts/planning_canonical.py`
  - **Expected:** tags/blocks/extends/supersedes projected without type corruption
  - **R-IDs:** R22

### 5. `inbound-comments-native-ids` — Inbound comments + native ids (R18, R19)

- [ ] 5.1 Facade inbound comment sync for authoring/deliver (R18)
  - **File:** `scripts/planning_store.py`
  - **Expected:** Fixture comments readable via facade into authoring consumer
  - **R-IDs:** R18
- [ ] 5.2 Namespaced native unit ids + legacy compatibility map (R19)
  - **File:** `scripts/planning_store.py`
  - **Expected:** New units use `gh:<n>` (or equiv); legacy sequential ids resolve; no bare `061` collision
  - **R-IDs:** R19

### 6. `amend-docs-gap-prereq` — Amend/decisions + docs + gap pre-req write-back (R16, R23, R26–R29)

- [ ] 6.1 Route amend/decisions through facade under issue-store (R23)
  - **File:** `core/commands/sw-amend.md`
  - **Expected:** Amend/decision put leaves no code-repo docs body under issue-store
  - **R-IDs:** R23
- [ ] 6.2 Remediate skills/commands/README/config/parity docs (R28)
  - **File:** `README.md`
  - **Expected:** R28 surfaces updated; no local living-doc mutation instructions under issue-store
  - **R-IDs:** R28
- [ ] 6.3 Write-back gap-078/079 depends on 061; resolve 077/104/109 when green; enforce 060 gate (R16, R26, R27, R29)
  - **File:** `scripts/planning_store.py`
  - **Expected:** gap-078/079 frontmatter depends includes 061; absorbed gaps close only after checks
  - **R-IDs:** R16, R26, R27, R29

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 2 |
| 4 | 1 |
| 5 | 1 |
| 6 | 3, 4, 5 |

## Execute-tier granularity

> Frozen artifact (PRD 055 R17). Generated by `python3 scripts/tasks_generate.py apply-granularity` before `/sw-freeze`.

```json
{
  "generatedBy": "tasks_generate.py",
  "refSplits": [],
  "splitPreflight": {
    "costEstimate": {
      "estimate": 49,
      "mergeGates": 7,
      "projectedWaves": 7
    },
    "notices": [
      "phase 1: scopeUnderDeclared (11 implied path(s) not in **File:** lines)",
      "phase 2: scopeUnderDeclared (13 implied path(s) not in **File:** lines)",
      "phase 3: scopeUnderDeclared (12 implied path(s) not in **File:** lines)",
      "phase 4: scopeUnderDeclared (10 implied path(s) not in **File:** lines)",
      "phase 5: scopeUnderDeclared (9 implied path(s) not in **File:** lines)",
      "phase 6: scopeUnderDeclared (20 implied path(s) not in **File:** lines)"
    ],
    "phaseCount": 6,
    "splitSuggestions": [
      {
        "externalEdges": [
          {
            "from": "1b",
            "kind": "split-fan-out",
            "to": "2"
          },
          {
            "from": "1b",
            "kind": "split-fan-out",
            "to": "4"
          },
          {
            "from": "1b",
            "kind": "split-fan-out",
            "to": "5"
          }
        ],
        "internalEdges": [
          {
            "from": "1a",
            "kind": "serial",
            "to": "1b"
          }
        ],
        "phase": "1",
        "preflight": {
          "baselineMaxWaveWidth": 3,
          "baselinePhaseCount": 6,
          "maxWaveWidth": 2,
          "notices": [
            "contention: phases 2 and 5 serialized (scripts/planning_store.py)",
            "contention injected 1 edge(s)"
          ],
          "parallelCeiling": 10,
          "projectedPhaseCount": 7,
          "verdict": "pass",
          "waves": [
            [
              "1a",
              "1b"
            ],
            [
              "2",
              "4"
            ],
            [
              "3",
              "5"
            ],
            [
              "6"
            ]
          ]
        },
        "rejected": false,
        "units": [
          {
            "files": [
              "scripts/planning_store.py"
            ],
            "id": "1a"
          },
          {
            "files": [
              "scripts/wave_living_docs.py"
            ],
            "id": "1b"
          }
        ]
      },
      {
        "externalEdges": [
          {
            "from": "1",
            "kind": "split-fan-in",
            "to": "2a"
          },
          {
            "from": "2d",
            "kind": "split-fan-out",
            "to": "3"
          }
        ],
        "internalEdges": [
          {
            "from": "2a",
            "kind": "serial",
            "to": "2b"
          },
          {
            "from": "2b",
            "kind": "serial",
            "to": "2c"
          },
          {
            "from": "2c",
            "kind": "serial",
            "to": "2d"
          }
        ],
        "phase": "2",
        "preflight": {
          "baselineMaxWaveWidth": 3,
          "baselinePhaseCount": 6,
          "maxWaveWidth": 3,
          "notices": [
            "contention: phases 1 and 2d serialized (scripts/planning_store.py)",
            "contention: phases 3 and 5 serialized (scripts/planning_store.py)",
            "contention injected 2 edge(s)"
          ],
          "parallelCeiling": 10,
          "projectedPhaseCount": 9,
          "verdict": "pass",
          "waves": [
            [
              "1",
              "2b",
              "2c"
            ],
            [
              "4",
              "2a",
              "2d"
            ],
            [
              "3"
            ],
            [
              "5"
            ],
            [
              "6"
            ]
          ]
        },
        "rejected": false,
        "units": [
          {
            "files": [
              "scripts/planning_discover.py"
            ],
            "id": "2a"
          },
          {
            "files": [
              "scripts/planning_hierarchy.py"
            ],
            "id": "2b"
          },
          {
            "files": [
              "scripts/planning_progress.py"
            ],
            "id": "2c"
          },
          {
            "files": [
              "scripts/planning_store.py"
            ],
            "id": "2d"
          }
        ]
      },
      {
        "externalEdges": [
          {
            "from": "2",
            "kind": "split-fan-in",
            "to": "3a"
          },
          {
            "from": "3c",
            "kind": "split-fan-out",
            "to": "6"
          }
        ],
        "internalEdges": [
          {
            "from": "3a",
            "kind": "serial",
            "to": "3b"
          },
          {
            "from": "3b",
            "kind": "serial",
            "to": "3c"
          }
        ],
        "phase": "3",
        "preflight": {
          "maxWaveWidth": 3,
          "notices": [
            "contention: phases 1 and 3c serialized (scripts/planning_store.py)",
            "contention: phases 2 and 5 serialized (scripts/planning_store.py)",
            "contention: phases 3a and 6 serialized (core/**)",
            "contention injected 3 edge(s)"
          ],
          "reason": "width-1 collapse",
          "verdict": "reject"
        },
        "reason": "width-1 collapse",
        "rejected": true,
        "units": [
          {
            "files": [
              "core/providers/issues/CAPABILITIES.md",
              "core/sw-reference/planning-deliver-parity-matrix.md"
            ],
            "id": "3a"
          },
          {
            "files": [
              "docs/guides/workflows.md"
            ],
            "id": "3b"
          },
          {
            "files": [
              "scripts/planning_store.py"
            ],
            "id": "3c"
          }
        ]
      },
      {
        "externalEdges": [
          {
            "from": "1",
            "kind": "split-fan-in",
            "to": "4a"
          },
          {
            "from": "4b",
            "kind": "split-fan-out",
            "to": "6"
          }
        ],
        "internalEdges": [
          {
            "from": "4a",
            "kind": "serial",
            "to": "4b"
          }
        ],
        "phase": "4",
        "preflight": {
          "maxWaveWidth": 2,
          "notices": [
            "contention: phases 2 and 5 serialized (scripts/planning_store.py)",
            "contention injected 1 edge(s)"
          ],
          "reason": "width-1 collapse",
          "verdict": "reject"
        },
        "reason": "width-1 collapse",
        "rejected": true,
        "units": [
          {
            "files": [
              "scripts/planning_canonical.py"
            ],
            "id": "4a"
          },
          {
            "files": [
              "scripts/planning_gap_capture.py"
            ],
            "id": "4b"
          }
        ]
      },
      {
        "externalEdges": [
          {
            "from": "3",
            "kind": "split-fan-in",
            "to": "6a"
          },
          {
            "from": "4",
            "kind": "split-fan-in",
            "to": "6a"
          },
          {
            "from": "5",
            "kind": "split-fan-in",
            "to": "6a"
          }
        ],
        "internalEdges": [
          {
            "from": "6a",
            "kind": "serial",
            "to": "6b"
          },
          {
            "from": "6b",
            "kind": "serial",
            "to": "6c"
          }
        ],
        "phase": "6",
        "preflight": {
          "maxWaveWidth": 3,
          "notices": [
            "contention: phases 1 and 6c serialized (scripts/planning_store.py)",
            "contention: phases 2 and 5 serialized (scripts/planning_store.py)",
            "contention injected 2 edge(s)"
          ],
          "reason": "width-1 collapse",
          "verdict": "reject"
        },
        "reason": "width-1 collapse",
        "rejected": true,
        "units": [
          {
            "files": [
              "README.md"
            ],
            "id": "6a"
          },
          {
            "files": [
              "core/commands/sw-amend.md"
            ],
            "id": "6b"
          },
          {
            "files": [
              "scripts/planning_store.py"
            ],
            "id": "6c"
          }
        ]
      }
    ]
  },
  "taskList": ".cursor/planning-materialized/tasks-061-planning-store-interface-architecture.md",
  "version": 1
}
```

## Traceability

| R-ID | Task | Named test scenario | ZOMBIES |
| --- | --- | --- | --- |
| R1 | 1.1 | facade-bypass-fail-closed | Z |
| R2 | 1.1 | facade-api-surface | Z |
| R2a | 1.1 | allowlist-static-import | Z |
| R3 | 1.2, 1.3 | doctor-dirty-banned-path | Z |
| R3a | 1.4 | cleanup-idempotent | Z |
| R4 | 1.2 | living-status-store-evidence | Z |
| R5 | 1.2 | completion-store-events | Z |
| R6 | 2.1, 2.2 | no-default-phase-issues | Z |
| R7 | 2.1 | degrade-single-notice | Z |
| R8 | 2.1, 2.2 | opt-in-hierarchy-off | Z |
| R8a | 2.3 | orphan-phase-migration | Z |
| R9 | 2.4 | once-per-run-apply | Z |
| R10 | 3.2, 3.4 | matrix-docs-present | Z |
| R11 | 3.1 | projects-v2-upsert | Z |
| R11a | 3.1, 3.2 | projects-missing-scope-degrade | Z |
| R11b | 3.3 | po-browse-four-questions | Z |
| R12 | 3.4 | jira-matrix-row | Z |
| R13 | 3.4 | gitlab-target-row | Z |
| R14 | 3.4, 6.3 | linear-pattern-recorded | Z |
| R15 | 3.4, 6.3 | notion-pattern-recorded | Z |
| R16 | 6.3 | gap-078-079-depends-061 | Z |
| R17 | 4.1 | gap-put-requires-problem-context | Z |
| R17a | 4.1 | feedback-autofill-related-next | Z |
| R18 | 5.1 | inbound-comments-facade | Z |
| R19 | 5.2 | namespaced-native-ids | Z |
| R20 | 4.2 | operator-body-no-raw-yaml | Z |
| R21 | 4.2 | frontmatter-backfill-idempotent | Z |
| R22 | 4.3 | structural-keys-projected | Z |
| R23 | 6.1 | amend-decision-store-only | Z |
| R24 | 2.5 | tasks-in-discover | Z |
| R25 | 1.1, 3.1 | conformance-harness-floor | Z |
| R26 | 6.3 | depends-060-not-absorb-060-gaps | Z |
| R27 | 6.3 | absorb-077-104-109-resolve | Z |
| R28 | 6.2 | docs-surface-remediation | Z |
| R29 | 6.3 | rollout-after-060-r1-r7 | Z |
| R29a | 3.3 | cutover-gate-with-projects | Z |

## Notes

- MVP architecture acceptance = Phases 1–2 green; full PRD = Phases 1–6.
- Do not implement Linear/Notion live clients; do not absorb 060 gaps 105/096/100/081/099/112.
- Letter-suffixed R-IDs are normative; include them in task Expected/R-IDs even if union lists parents only.