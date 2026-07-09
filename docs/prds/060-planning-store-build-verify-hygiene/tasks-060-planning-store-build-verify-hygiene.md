prd: docs/prds/060-planning-store-build-verify-hygiene/060-prd-planning-store-build-verify-hygiene.md
status: not-started
# Tasks — PRD 060 Planning-store, build-chain, and verify hygiene

## Relevant Files

- `scripts/planning_canonical.py` — `infer_artifact_type`, unresolved sentinel, `require_artifact_type` helper (R1–R3)
- `scripts/planning_store.py` — `IssueStoreBackend.put` type preference, `close_delivery_units` / snapshot resolution, alias + phase + schedule-less gap closure (R2–R7)
- `scripts/planning_artifact_handle.py` — opaque/path unit-id helpers used by callers (R1)
- `scripts/copy-to-core.py` — last-synced provenance refuse + fixture/CI-only `--force` (R11)
- `scripts/sw-generate-all.py` / generate entrypoints — sync allowlist step 1 (R12–R13)
- golden-manifest refresh entrypoint (existing generate/golden scripts) — sync allowlist step 2 (R12–R13)
- `scripts/wave_deliver.py` / deliver ledger — persist phase issue refs for R5 restart safety
- `scripts/planning_gap_capture.py` — override auto-gap filing + redaction (R8–R9)
- `scripts/shipwright-state.py` / verification-gate override bookkeeping (R8–R9)
- `core/skills/verification-gate/SKILL.md` — override auto-gap + test-freshness obligation (R8–R10)
- `core/commands/sw-ship.md`, `core/commands/sw-verify.md`, `core/commands/sw-commit.md`, `core/commands/sw-retrospective.md` — docs impact
- `core/skills/living-status/SKILL.md` — closure reporting surface
- `docs/guides/testing.md`, `docs/guides/workflows.md` / `docs/guides/commands.md` — sync entrypoint + harness isolation docs
- `.sw/layout.md` / `core/sw-reference/build-chain-sot.json` — sync entrypoint + SoT notes
- `scripts/unit_tests/` — meta/harness checks for shared config + baseline I/O (R14–R15)
- deprecated-surface manifest (new, plugin-maintained) — R10 enforcement input

## Tasks

### 1. `gap-105` — Opaque locator type hygiene (R1–R3)

- [x] 1.1 Make `infer_artifact_type` return an unresolved sentinel (not `"prd"`) for opaque `issue:<n>` locators (R1)
  - **File:** `scripts/planning_canonical.py`
  - **Expected:** `infer_artifact_type("issue:1")` is not `"prd"`; typed unresolved sentinel or error; unit tests cover opaque vs path shapes
  - **R-IDs:** R1
- [x] 1.2 Add `require_artifact_type` (or equivalent) and migrate every direct caller that assumes a concrete type (R1) (unit 1/2)
  - **File:** `scripts/planning_canonical.py`
  - **Expected:** Unresolved is handled explicitly outside `put`; regression coverage for lookup/search/backfill/discovery paths
  - **R-IDs:** R1
- [x] 1.3 Add `require_artifact_type` (or equivalent) and migrate every direct caller that assumes a concrete type (R1) (unit 2/2)
  - **File:** `scripts/planning_store.py`
  - **Expected:** Unresolved is handled explicitly outside `put`; regression coverage for lookup/search/backfill/discovery paths
  - **R-IDs:** R1
- [x] 1.4 Prefer artifact type from existing record → content/frontmatter → caller-provided → path-shape (non-opaque only) in `put` / label projection (R2)
  - **File:** `scripts/planning_store.py`
  - **Expected:** New-unit create via opaque locator succeeds when caller supplies explicit type; fail closed (never default `prd`) when none resolve
  - **R-IDs:** R2
- [x] 1.5 Regression fixture: re-put gap/tasks/brainstorm via `issue:<n>` never adds stray `sw:prd` (R3)
  - **File:** `scripts/unit_tests/planning/`
  - **Expected:** Label-set integrity asserted after write for non-PRD units
  - **R-IDs:** R3

### 2. `gap-112` — Post-deliver / post-merge closure completeness (R4–R7)

- [x] 2.1 Resolve PRD unit-id aliases (`<n>-prd-<slug>` and legacy `<n>-<slug>`) in closure entrypoints (R4)
  - **File:** `scripts/planning_store.py`
  - **Expected:** Both alias forms close the same PRD issue when present; idempotent re-close
  - **R-IDs:** R4
- [x] 2.2 Close done phase sub-issues using deliver-ledger refs with live issue-store fallback (R5) (unit 1/2)
  - **File:** `scripts/planning_store.py`
  - **Expected:** Phase issues with `sw:phase:N:done` (or equivalent) close; fixtures do not depend on in-memory hierarchy alone
  - **R-IDs:** R5
- [x] 2.3 Close done phase sub-issues using deliver-ledger refs with live issue-store fallback (R5) (unit 2/2)
  - **File:** `scripts/wave_deliver.py`
  - **Expected:** Phase issues with `sw:phase:N:done` (or equivalent) close; fixtures do not depend on in-memory hierarchy alone
  - **R-IDs:** R5
- [x] 2.4 Include schedule-less absorbed/delivered gaps via delivery-grade evidence only; skip related-only gaps with reason (R6)
  - **File:** `scripts/planning_store.py`
  - **Expected:** Delivery-grade gaps close without `sw:schedule:prd:<n>`; related-only / Non-Goal-linked open gap skipped with R7 reason
  - **R-IDs:** R6
- [x] 2.5 Emit dry-run and applied closure reports with `resumeCommand` when expected units remain open (R7) (unit 1/2)
  - **File:** `core/commands/sw-retrospective.md`
  - **Expected:** Report lists considered/closed/skipped/skip reason; resume command present when incomplete
  - **R-IDs:** R7

- [x] 2.6 Emit dry-run and applied closure reports with `resumeCommand` when expected units remain open (R7) (unit 2/2)
  - **File:** `scripts/planning_store.py`
  - **Expected:** Report lists considered/closed/skipped/skip reason; resume command present when incomplete
  - **R-IDs:** R7

### 3. `gap-096` + `gap-100` — Build-chain SoT sync and freshness (R11–R13)

- [ ] 3.1 Detect core-side divergence via last-synced provenance; refuse discard of manual `core/sw-reference/` edits (R11)
  - **File:** `scripts/copy-to-core.py`
  - **Expected:** Refuse when core changed since last sync and changes absent from `.sw/`; print `.sw/` remediation; normal forward-sync succeeds without `--force`
  - **R-IDs:** R11
- [ ] 3.2 Restrict `--force` to fixture/CI-only escape (explicit, logged); refresh last-synced on success and force (R11) (unit 1/2)
  - **File:** `.sw/layout.md`
  - **Expected:** Operator docs do not present `--force` as real-repo workflow; provenance location documented
  - **R-IDs:** R11
- [ ] 3.3 Restrict `--force` to fixture/CI-only escape (explicit, logged); refresh last-synced on success and force (R11) (unit 2/2)
  - **File:** `scripts/copy-to-core.py`
  - **Expected:** Operator docs do not present `--force` as real-repo workflow; provenance location documented
  - **R-IDs:** R11
- [ ] 3.4 Add single sync entrypoint running allowlist generate → golden-manifest refresh → copy-to-core (R12)
  - **File:** `scripts/`
  - **Expected:** Exact allowlist order; structured success/failure with remediation commands per failure mode
  - **R-IDs:** R12
- [ ] 3.5 Fail-closed harness/CI freshness checks emit exact remediation invocations (R13) (unit 1/2)
  - **File:** `scripts/`
  - **Expected:** Skipped generate/golden/copy-to-core fails with exact remediation, not vague “run generate”
  - **R-IDs:** R13

- [ ] 3.6 Fail-closed harness/CI freshness checks emit exact remediation invocations (R13) (unit 2/2)
  - **File:** `scripts/unit_tests/`
  - **Expected:** Skipped generate/golden/copy-to-core fails with exact remediation, not vague “run generate”
  - **R-IDs:** R13

### 4. `gap-081` + `gap-099` — Verify override follow-up and harness isolation (R8–R10, R14–R15)

- [ ] 4.1 On verify/ship override of `no-baseline` / `unattributed`, auto-file durable follow-up gap via gap-capture (R8) (unit 1/2)
  - **File:** `core/skills/verification-gate/SKILL.md`
  - **Expected:** Override alone insufficient to forget failure; gap references redacted override evidence
  - **R-IDs:** R8
- [ ] 4.2 On verify/ship override of `no-baseline` / `unattributed`, auto-file durable follow-up gap via gap-capture (R8) (unit 2/2)
  - **File:** `scripts/planning_gap_capture.py`
  - **Expected:** Override alone insufficient to forget failure; gap references redacted override evidence
  - **R-IDs:** R8
- [ ] 4.3 Idempotent cross-run reuse by deterministic failure signature; surface create-vs-reuse + unit id (R9)
  - **File:** `scripts/planning_gap_capture.py`
  - **Expected:** Signature uses stable ids only (class + normalized path/unit + PR/commit); excludes timestamps/run IDs/raw logs
  - **R-IDs:** R9
- [ ] 4.4 Add explicit deprecated-surface manifest + fail-closed test-freshness check (plugin harness scope) (R10)
  - **File:** `scripts/`
  - **Expected:** Enforcement evaluates only explicit manifest/annotations — not repo-wide API inference
  - **R-IDs:** R10
- [ ] 4.5 Meta/harness: fail shared mutable `workflow.config.json` only when fixture also does baseline I/O (R14)
  - **File:** `scripts/unit_tests/`
  - **Expected:** Shared config + baseline read/write fails; read-only shared config without baseline I/O passes (optional opt-out annotation)
  - **R-IDs:** R14
- [ ] 4.6 Own verify baselines per phase/run at caller-owned canonical paths (R15)
  - **File:** `scripts/unit_tests/`
  - **Expected:** Concurrent or sequential phases cannot clobber each other’s baseline evidence
  - **R-IDs:** R15

### 5. Docs, skill remediation, and gap resolve wiring (R16–R17)

- [ ] 5.1 Update documentation-impact surfaces for sync entrypoint, refuse semantics, override auto-gap, and closure completeness (R16) (unit 1/5)
  - **File:** `.sw/layout.md`
  - **Expected:** Operators can find allowlist, fixture/CI-only `--force`, closure dry-run/apply, and override create/reuse behavior without tribal knowledge
  - **R-IDs:** R16
- [ ] 5.2 Update documentation-impact surfaces for sync entrypoint, refuse semantics, override auto-gap, and closure completeness (R16) (unit 2/5)
  - **File:** `core/commands/sw-commit.md`, `core/commands/sw-retrospective.md`, `core/commands/sw-ship.md`, `core/commands/sw-verify.md`
  - **Expected:** Operators can find allowlist, fixture/CI-only `--force`, closure dry-run/apply, and override create/reuse behavior without tribal knowledge
  - **R-IDs:** R16
- [ ] 5.3 Update documentation-impact surfaces for sync entrypoint, refuse semantics, override auto-gap, and closure completeness (R16) (unit 3/5)
  - **File:** `core/skills/living-status/SKILL.md`
  - **Expected:** Operators can find allowlist, fixture/CI-only `--force`, closure dry-run/apply, and override create/reuse behavior without tribal knowledge
  - **R-IDs:** R16
- [ ] 5.4 Update documentation-impact surfaces for sync entrypoint, refuse semantics, override auto-gap, and closure completeness (R16) (unit 4/5)
  - **File:** `core/skills/verification-gate/SKILL.md`
  - **Expected:** Operators can find allowlist, fixture/CI-only `--force`, closure dry-run/apply, and override create/reuse behavior without tribal knowledge
  - **R-IDs:** R16
- [ ] 5.5 Update documentation-impact surfaces for sync entrypoint, refuse semantics, override auto-gap, and closure completeness (R16) (unit 5/5)
  - **File:** `docs/guides/testing.md`
  - **Expected:** Operators can find allowlist, fixture/CI-only `--force`, closure dry-run/apply, and override create/reuse behavior without tribal knowledge
  - **R-IDs:** R16
- [ ] 5.6 Wire absorbed-gap resolve only after phase acceptance checks; document independent phase-merge completion rule (R16, R17)
  - **File:** `core/commands/sw-retrospective.md`
  - **Expected:** Each absorbed gap resolves after its phase acceptance; PRD complete only when last phase lands; phases 1–2 prioritized under contention
  - **R-IDs:** R16, R17

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | none |
| 3 | none |
| 4 | none |
| 5 | 1, 2, 3, 4 |

## Execute-tier granularity

> Frozen artifact (PRD 055 R17). Generated by `python3 scripts/tasks_generate.py apply-granularity` before `/sw-freeze`.

```json
{
  "generatedBy": "tasks_generate.py",
  "refSplits": [
    {
      "childRefs": [
        "1.2",
        "1.3"
      ],
      "files": [
        "scripts/planning_canonical.py",
        "scripts/planning_store.py"
      ],
      "overThreshold": false,
      "parentRef": "1.2",
      "phase": "1",
      "separableSets": [
        [
          "scripts/planning_canonical.py"
        ],
        [
          "scripts/planning_store.py"
        ]
      ],
      "serialEdges": [],
      "targetSets": [
        [
          "scripts/planning_canonical.py"
        ],
        [
          "scripts/planning_store.py"
        ]
      ]
    },
    {
      "childRefs": [
        "2.2",
        "2.3"
      ],
      "files": [
        "scripts/planning_store.py",
        "scripts/wave_deliver.py"
      ],
      "overThreshold": false,
      "parentRef": "2.2",
      "phase": "2",
      "separableSets": [
        [
          "scripts/planning_store.py"
        ],
        [
          "scripts/wave_deliver.py"
        ]
      ],
      "serialEdges": [],
      "targetSets": [
        [
          "scripts/planning_store.py"
        ],
        [
          "scripts/wave_deliver.py"
        ]
      ]
    },
    {
      "childRefs": [
        "2.5",
        "2.6"
      ],
      "files": [
        "core/commands/sw-retrospective.md",
        "scripts/planning_store.py"
      ],
      "overThreshold": false,
      "parentRef": "2.4",
      "phase": "2",
      "separableSets": [
        [
          "core/commands/sw-retrospective.md"
        ],
        [
          "scripts/planning_store.py"
        ]
      ],
      "serialEdges": [],
      "targetSets": [
        [
          "core/commands/sw-retrospective.md"
        ],
        [
          "scripts/planning_store.py"
        ]
      ]
    },
    {
      "childRefs": [
        "3.2",
        "3.3"
      ],
      "files": [
        ".sw/layout.md",
        "scripts/copy-to-core.py"
      ],
      "overThreshold": false,
      "parentRef": "3.2",
      "phase": "3",
      "separableSets": [
        [
          ".sw/layout.md"
        ],
        [
          "scripts/copy-to-core.py"
        ]
      ],
      "serialEdges": [],
      "targetSets": [
        [
          ".sw/layout.md"
        ],
        [
          "scripts/copy-to-core.py"
        ]
      ]
    },
    {
      "childRefs": [
        "3.5",
        "3.6"
      ],
      "files": [
        "scripts/",
        "scripts/unit_tests/"
      ],
      "overThreshold": false,
      "parentRef": "3.4",
      "phase": "3",
      "separableSets": [
        [
          "scripts/"
        ],
        [
          "scripts/unit_tests/"
        ]
      ],
      "serialEdges": [],
      "targetSets": [
        [
          "scripts/"
        ],
        [
          "scripts/unit_tests/"
        ]
      ]
    },
    {
      "childRefs": [
        "4.1",
        "4.2"
      ],
      "files": [
        "core/skills/verification-gate/SKILL.md",
        "scripts/planning_gap_capture.py"
      ],
      "overThreshold": false,
      "parentRef": "4.1",
      "phase": "4",
      "separableSets": [
        [
          "core/skills/verification-gate/SKILL.md"
        ],
        [
          "scripts/planning_gap_capture.py"
        ]
      ],
      "serialEdges": [],
      "targetSets": [
        [
          "core/skills/verification-gate/SKILL.md"
        ],
        [
          "scripts/planning_gap_capture.py"
        ]
      ]
    },
    {
      "childRefs": [
        "5.1",
        "5.2",
        "5.3",
        "5.4",
        "5.5"
      ],
      "files": [
        ".sw/layout.md",
        "core/commands/sw-commit.md",
        "core/commands/sw-retrospective.md",
        "core/commands/sw-ship.md",
        "core/commands/sw-verify.md",
        "core/skills/living-status/SKILL.md",
        "core/skills/verification-gate/SKILL.md",
        "docs/guides/testing.md"
      ],
      "overThreshold": true,
      "parentRef": "5.1",
      "phase": "5",
      "separableSets": [
        [
          ".sw/layout.md"
        ],
        [
          "core/commands/sw-commit.md",
          "core/commands/sw-retrospective.md",
          "core/commands/sw-ship.md",
          "core/commands/sw-verify.md",
          "core/skills/living-status/SKILL.md",
          "core/skills/verification-gate/SKILL.md"
        ],
        [
          "docs/guides/testing.md"
        ]
      ],
      "serialEdges": [],
      "targetSets": [
        [
          ".sw/layout.md"
        ],
        [
          "core/commands/sw-commit.md",
          "core/commands/sw-retrospective.md",
          "core/commands/sw-ship.md",
          "core/commands/sw-verify.md"
        ],
        [
          "core/skills/living-status/SKILL.md"
        ],
        [
          "core/skills/verification-gate/SKILL.md"
        ],
        [
          "docs/guides/testing.md"
        ]
      ]
    }
  ],
  "splitPreflight": {
    "costEstimate": {
      "estimate": 36,
      "mergeGates": 6,
      "projectedWaves": 6
    },
    "notices": [
      "phase 1: scopeUnderDeclared (14 implied path(s) not in **File:** lines)",
      "phase 2: scopeUnderDeclared (18 implied path(s) not in **File:** lines)",
      "phase 3: scopeUnderDeclared (28 implied path(s) not in **File:** lines)",
      "phase 4: scopeUnderDeclared (30 implied path(s) not in **File:** lines)",
      "phase 5: scopeUnderDeclared (21 implied path(s) not in **File:** lines)"
    ],
    "phaseCount": 5,
    "splitSuggestions": [
      {
        "externalEdges": [
          {
            "from": "1c",
            "kind": "split-fan-out",
            "to": "5"
          }
        ],
        "internalEdges": [
          {
            "from": "1a",
            "kind": "serial",
            "to": "1b"
          },
          {
            "from": "1b",
            "kind": "serial",
            "to": "1c"
          }
        ],
        "phase": "1",
        "preflight": {
          "baselineMaxWaveWidth": 4,
          "baselinePhaseCount": 5,
          "maxWaveWidth": 4,
          "notices": [
            "contention: phases 2 and 4 serialized (core/**)",
            "contention: phases 1c and 2 serialized (scripts/planning_store.py)",
            "contention injected 2 edge(s)"
          ],
          "parallelCeiling": 10,
          "projectedPhaseCount": 7,
          "verdict": "pass",
          "waves": [
            [
              "3",
              "1a",
              "1b",
              "1c"
            ],
            [
              "2"
            ],
            [
              "4"
            ],
            [
              "5"
            ]
          ]
        },
        "rejected": false,
        "units": [
          {
            "files": [
              "lookup/search/backfill/discovery callers"
            ],
            "id": "1a"
          },
          {
            "files": [
              "scripts/planning_canonical.py"
            ],
            "id": "1b"
          },
          {
            "files": [
              "scripts/planning_store.py"
            ],
            "id": "1c"
          }
        ]
      },
      {
        "externalEdges": [
          {
            "from": "2b",
            "kind": "split-fan-out",
            "to": "5"
          }
        ],
        "internalEdges": [
          {
            "from": "2a",
            "kind": "serial",
            "to": "2b"
          }
        ],
        "phase": "2",
        "preflight": {
          "maxWaveWidth": 3,
          "notices": [
            "contention: phases 1 and 2b serialized (scripts/planning_store.py)",
            "contention: phases 2a and 4 serialized (core/**)",
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
              "core/commands/sw-retrospective.md"
            ],
            "id": "2a"
          },
          {
            "files": [
              "scripts/planning_store.py"
            ],
            "id": "2b"
          }
        ]
      },
      {
        "externalEdges": [
          {
            "from": "3c",
            "kind": "split-fan-out",
            "to": "5"
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
          "baselineMaxWaveWidth": 4,
          "baselinePhaseCount": 5,
          "maxWaveWidth": 3,
          "notices": [
            "contention: phases 1 and 2 serialized (scripts/planning_store.py)",
            "contention: phases 2 and 4 serialized (core/**)",
            "contention: phases 2 and 3a serialized (core/**)",
            "contention: phases 3a and 4 serialized (core/**)",
            "contention injected 4 edge(s)"
          ],
          "parallelCeiling": 10,
          "projectedPhaseCount": 7,
          "verdict": "pass",
          "waves": [
            [
              "1",
              "3b",
              "3c"
            ],
            [
              "2"
            ],
            [
              "3a"
            ],
            [
              "4"
            ],
            [
              "5"
            ]
          ]
        },
        "rejected": false,
        "units": [
          {
            "files": [
              "core/agents",
              "core/commands",
              "core/providers",
              "core/rules",
              "core/scripts",
              "core/skills",
              "core/sw-reference",
              "dist/claude-code",
              "dist/cursor",
              "scripts/test/fixtures/parity/cursor-golden.manifest"
            ],
            "id": "3a"
          },
          {
            "files": [
              "generate/golden/copy-to-core callers"
            ],
            "id": "3b"
          },
          {
            "files": [
              "scripts/copy-to-core.py"
            ],
            "id": "3c"
          }
        ]
      },
      {
        "externalEdges": [
          {
            "from": "4d",
            "kind": "split-fan-out",
            "to": "5"
          }
        ],
        "internalEdges": [
          {
            "from": "4a",
            "kind": "serial",
            "to": "4b"
          },
          {
            "from": "4b",
            "kind": "serial",
            "to": "4c"
          },
          {
            "from": "4c",
            "kind": "serial",
            "to": "4d"
          }
        ],
        "phase": "4",
        "preflight": {
          "baselineMaxWaveWidth": 4,
          "baselinePhaseCount": 5,
          "maxWaveWidth": 5,
          "notices": [
            "contention: phases 1 and 2 serialized (scripts/planning_store.py)",
            "contention: phases 2 and 4a serialized (core/**)",
            "contention injected 2 edge(s)"
          ],
          "parallelCeiling": 10,
          "projectedPhaseCount": 8,
          "verdict": "pass",
          "waves": [
            [
              "1",
              "3",
              "4b",
              "4c",
              "4d"
            ],
            [
              "2"
            ],
            [
              "5",
              "4a"
            ]
          ]
        },
        "rejected": false,
        "units": [
          {
            "files": [
              "core/skills/verification-gate/SKILL.md"
            ],
            "id": "4a"
          },
          {
            "files": [
              "scripts/planning_gap_capture.py"
            ],
            "id": "4b"
          },
          {
            "files": [
              "ship/verify override bookkeeping"
            ],
            "id": "4c"
          },
          {
            "files": [
              "verify/ship skill docs"
            ],
            "id": "4d"
          }
        ]
      },
      {
        "externalEdges": [
          {
            "from": "1",
            "kind": "split-fan-in",
            "to": "5a"
          },
          {
            "from": "2",
            "kind": "split-fan-in",
            "to": "5a"
          },
          {
            "from": "3",
            "kind": "split-fan-in",
            "to": "5a"
          },
          {
            "from": "4",
            "kind": "split-fan-in",
            "to": "5a"
          }
        ],
        "internalEdges": [
          {
            "from": "5a",
            "kind": "serial",
            "to": "5b"
          },
          {
            "from": "5b",
            "kind": "serial",
            "to": "5c"
          },
          {
            "from": "5c",
            "kind": "serial",
            "to": "5d"
          },
          {
            "from": "5d",
            "kind": "serial",
            "to": "5e"
          }
        ],
        "phase": "5",
        "preflight": {
          "baselineMaxWaveWidth": 4,
          "baselinePhaseCount": 5,
          "maxWaveWidth": 5,
          "notices": [
            "contention: phases 1 and 2 serialized (scripts/planning_store.py)",
            "contention: phases 2 and 4 serialized (core/**)",
            "contention: phases 2 and 5c serialized (core/**)",
            "contention: phases 4 and 5c serialized (core/**)",
            "contention injected 4 edge(s)"
          ],
          "parallelCeiling": 10,
          "projectedPhaseCount": 9,
          "verdict": "pass",
          "waves": [
            [
              "1",
              "3",
              "5b",
              "5d",
              "5e"
            ],
            [
              "2"
            ],
            [
              "4"
            ],
            [
              "5a",
              "5c"
            ]
          ]
        },
        "rejected": false,
        "units": [
          {
            "files": [
              ".sw/layout.md"
            ],
            "id": "5a"
          },
          {
            "files": [
              "applicable workflow/command guides"
            ],
            "id": "5b"
          },
          {
            "files": [
              "core/agents",
              "core/commands",
              "core/commands/sw-commit.md",
              "core/commands/sw-retrospective.md",
              "core/commands/sw-ship.md",
              "core/commands/sw-verify.md",
              "core/providers",
              "core/rules",
              "core/scripts",
              "core/skills",
              "core/skills/living-status/SKILL.md",
              "core/skills/verification-gate/SKILL.md",
              "core/sw-reference",
              "dist/claude-code",
              "dist/cursor",
              "scripts/test/fixtures/parity/cursor-golden.manifest"
            ],
            "id": "5c"
          },
          {
            "files": [
              "deliver/retrospective handoff prose"
            ],
            "id": "5d"
          },
          {
            "files": [
              "docs/guides/testing.md"
            ],
            "id": "5e"
          }
        ]
      }
    ]
  },
  "taskList": "/tmp/sw-doc-060/tasks-060.md",
  "version": 1
}
```

## Traceability

| R-ID | Task ref | Test scenario | ZOMBIES |
|------|----------|----------------|---------|
| R1 | 1.1, 1.2, 1.3 | Opaque `issue:N` unresolved; path shapes still infer; callers handle unresolved outside put | Zero: empty locator rejected · One/Many: single opaque id, batch of callers · Boundary: `issue:0` / malformed · Interface: `infer_artifact_type` / `require_artifact_type` · Exceptional: caller ignores unresolved |
| R2 | 1.4 | Type preference order; new-unit opaque create with explicit type; fail closed when none resolve | Zero: no type sources → fail · One/Many: each preference source wins alone · Boundary: opaque vs path · Interface: `IssueStoreBackend.put` · Exceptional: conflicting frontmatter vs record |
| R3 | 1.5 | Re-put gap/tasks/brainstorm via `issue:<n>` preserves type labels (no `sw:prd`) | Zero: unit with minimal labels · One/Many: gap, tasks, brainstorm · Boundary: PRD put still gets `sw:prd` · Interface: put label projection · Exceptional: concurrent label edit |
| R4 | 2.1 | Alias forms close same PRD; idempotent re-close | Zero: only one alias present · One/Many: both aliases · Boundary: unknown alias skipped · Interface: `close_delivery_units` · Exceptional: already closed |
| R5 | 2.2, 2.3 | Done phase issues close from ledger; live fallback when ledger absent | Zero: no phase issues · One/Many: multiple done phases · Boundary: open phase not closed · Interface: ledger + issue-store fallback · Exceptional: missing parent link |
| R6 | 2.4 | Schedule-less delivery-grade gaps close; related-only skipped with reason | Zero: no gaps · One/Many: mixed evidence grades · Boundary: INDEX-only association · Interface: closure snapshot · Exceptional: Non-Goal-linked open gap |
| R7 | 2.5, 2.6 | Dry-run vs applied reports; `resumeCommand` when incomplete | Zero: nothing to close · One/Many: multi-unit report · Boundary: all skipped · Interface: JSON emit · Exceptional: partial apply failure |
| R8 | 4.1, 4.2 | Override of `no-baseline`/`unattributed` files follow-up gap | Zero: no override path · One/Many: both classes · Boundary: non-override inconclusive · Interface: verification-gate / gap-capture · Exceptional: redaction strips secrets |
| R9 | 4.3 | Same signature reuses gap across runs; output shows create vs reuse + unit id | Zero: first create · One/Many: stabilize/CI retries · Boundary: different signature creates new · Interface: signature helper · Exceptional: volatile fields excluded |
| R10 | 4.4 | Deprecated-surface manifest check fails closed on stale tests | Zero: empty manifest · One/Many: multiple surfaces · Boundary: annotated disable allowed · Interface: freshness check · Exceptional: non-plugin paths ignored |
| R11 | 3.1, 3.2, 3.3 | Refuse core-only divergence; forward-sync ok; `--force` fixture/CI-only | Zero: identical trees · One/Many: multi-file divergence · Boundary: `.sw/` newer · Interface: `copy-to-core` · Exceptional: missing provenance treated fail-closed |
| R12 | 3.4 | Sync entrypoint runs generate → golden → copy-to-core only | Zero: already fresh · One/Many: each step failure · Boundary: orphan inside copy-to-core · Interface: sync CLI · Exceptional: partial mid-chain stop |
| R13 | 3.5, 3.6 | Freshness checks emit exact remediation commands | Zero: green workspace · One/Many: each drift class · Boundary: orphan block · Interface: harness/CI · Exceptional: vague message forbidden |
| R14 | 4.5 | Shared config + baseline I/O fails meta; read-only shared config passes | Zero: isolated configs · One/Many: multi-phase fixtures · Boundary: opt-out annotation · Interface: meta check · Exceptional: false positive avoided |
| R15 | 4.6 | Per-phase/run baselines do not clobber | Zero: single phase · One/Many: concurrent phases · Boundary: sequential reuse of path fails · Interface: harness helpers · Exceptional: missing caller path |
| R16 | 5.1, 5.2, 5.3, 5.4, 5.5, 5.6 | Docs list sync/override/closure; gaps resolve after phase acceptance | Zero: no absorbed gaps · One/Many: six gaps · Boundary: phase green but acceptance incomplete · Interface: retrospective / living-status · Exceptional: premature resolve blocked |
| R17 | 5.6 | Independent phase merges; PRD complete on last land; prioritize 1–2 under contention | Zero: single phase PRD N/A · One/Many: five phases · Boundary: early phase merge while later open · Interface: deliver/retrospective prose · Exceptional: contention reorders to 1–2 first |

## Notes

- Phase PRs MAY merge independently when green (R17); prefer phases 1–2 under contention.
- Absorbed gaps: `gap-105`, `gap-112`, `gap-096`, `gap-100`, `gap-081`, `gap-099` — resolve only after the owning phase acceptance checks pass (R16).
- Issue-store separate-project: do not write planning bodies under `docs/prds/` in the code repo; persist via `planning_store.put`.