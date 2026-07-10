prd: docs/prds/062-deliver-issue-store-hardening-and-loop-perf/062-prd-deliver-issue-store-hardening-and-loop-perf.md
status: not-started
# Tasks — PRD 062 Deliver issue-store hardening and loop performance

## Relevant Files

- `scripts/planning_materialize.py` — materialize-before-discover (R1)
- `scripts/planning_deliver_gate.py` — `--issue` / tasks- path normalize (R2)
- `scripts/dispatch_prompt.py` / deliver phase-ship prompt builders — intensity directive (R3)
- `scripts/docs-currency-gate.py` — slug fallback + readonly gap-backlog skip (R4)
- `scripts/wave_terminal.py` — terminal-pr-prepare recoverable/fatal (R5)
- `scripts/resolve_base_branch.py` — trunk base-capture from orch worktree (R6)
- `scripts/wave_deliver_loop.py` — drainMechanical + elapsedMs (R7, R9)
- phase status writers / `scripts/check_gate_lib.py` — slim prTestPlan + fail-closed load (R8)
- `scripts/cleanup_lib.py` — scoped inflight + terminal allowlist (R10, R11, TR6)
- `scripts/planning_request_budget.py` / query cache — critical revalidate + per-run isolation + maxCalls 750 (R12)
- `scripts/planning_unit_status.py` (+ discover/scheduler as needed) — vocab + facade (R13, R16)
- `.sw/config.schema.json`, workflow config examples — drain + budget defaults (R19, TR2, TR3)
- `core/skills/conductor/SKILL.md`, `core/commands/sw-deliver.md`, `core/commands/sw-cleanup.md` — docs (R19)
- `.sw/layout.md`, `README.md`, `docs/guides/workflows.md`, `docs/guides/configuration.md` — docs (R19)
- `scripts/unit_tests/` — harnesses R15 (a)–(k)

## Tasks

### 1. Correctness — issue-store deliver entry (R1–R3) — small

- [ ] 1.1 Materialize issue-store frozen task list before `discover_private_spec_units` in provision (R1)
  - **File:** `scripts/planning_materialize.py`
  - **Expected:** Issue-store provision succeeds when logical path absent until materialize; discover runs after materialize; file-store path unchanged
  - **R-IDs:** R1, R14
- [ ] 1.2 Strict leading `tasks-`+NNN normalize for `--issue` candidates; fail closed on ambiguous (R2)
  - **File:** `scripts/planning_deliver_gate.py`
  - **Expected:** `tasks-061-…` → `docs/prds/061-…/tasks-061-….md`; no double prefix; interior `tasks-` in slug does not mis-strip; already-normalized id stable
  - **R-IDs:** R2
- [ ] 1.3 Prepend `format_intensity_directive` on deliver phase-ship Task prompts (R3)
  - **File:** `scripts/dispatch_prompt.py`
  - **Expected:** First line matches intensity directive; dispatch-check no longer `binding:missing-intensity-directive` for phase-ship
  - **R-IDs:** R3
- [ ] 1.4 Harness: materialize-before-discover, tasks- normalize edges, intensity directive present (R15 a–c)
  - **File:** `scripts/unit_tests/`
  - **Expected:** Fixtures cover R15(a)(b)(c) including interior `tasks-` slug and already-normalized id
  - **R-IDs:** R15

### 2. Terminal — docs-currency and prepare degrade (R4–R5) — small

- [ ] 2.1 Docs-currency slug fallback `{NNN}-prd-{slug}` under issue-store (R4)
  - **File:** `scripts/docs-currency-gate.py`
  - **Expected:** Missing local INDEX / planning_index_issue miss resolves via slug; separate-project ship unblocked
  - **R-IDs:** R4
- [ ] 2.2 Skip gap-backlog integrity when readonly / separate-project shim (R4)
  - **File:** `scripts/docs-currency-gate.py`
  - **Expected:** `gap_backlog_is_readonly` (or equiv) skips integrity; non-readonly still checked
  - **R-IDs:** R4
- [ ] 2.3 Enumerate recoverable vs fatal classes; degrade with gate-visible notice; no unqualified green (R5)
  - **File:** `scripts/wave_terminal.py`
  - **Expected:** Recoverable continues to PR gate with structured notice in verdict; fatal remains fail-closed; no `sys.exit` abort before gate on recoverable
  - **R-IDs:** R5
- [ ] 2.4 Harness: slug fallback, readonly skip, recoverable continue + fatal fail-closed (R15 d–e)
  - **File:** `scripts/unit_tests/`
  - **Expected:** R15(d)(e) covered
  - **R-IDs:** R15

### 3. Perf — base-capture, drain, slim status, timing (R6–R9) — medium

- [x] 3.1 Trunk base-capture from repo-root/primary or explicit trunk ref without leaving feat/* (R6)
  - **File:** `scripts/resolve_base_branch.py`
  - **Expected:** Orch worktree on `<type>/<slug>` captures trunk SHA; ambiguous/unsafe still fail-closed; no work-branch-head spin
  - **R-IDs:** R6
- [x] 3.2 Implement `deliver.loop.drainMechanical` (default true) with no-progress + max-steps halt semantics (R7, TR2)
  - **File:** `scripts/wave_deliver_loop.py`
  - **Expected:** Drain until awaitAgent/awaitInFlight/halt; identical signature N× → stall halt not pass; max-steps still-mechanical → blocked; exceptions → JSON halt; false restores one-step
  - **R-IDs:** R7
- [x] 3.3 Schema/example for `deliver.loop.drainMechanical` (TR2)
  - **File:** `.sw/config.schema.json`
  - **Expected:** Boolean default true documented; examples updated
  - **R-IDs:** R7, R19
- [x] 3.4 Slim `prTestPlan.manifest` out of status.json; cleanup-safe path/hash; check-gate fail-closed on miss/mismatch (R8)
  - **File:** `scripts/check_gate_lib.py`
  - **Expected:** status.json slim; full manifest on demand; missing/hash mismatch fail-closed; happy-path verdict unchanged
  - **R-IDs:** R8
- [x] 3.5 Wire status writers to externalized manifest location (R8)
  - **File:** `scripts/`
  - **Expected:** Writers emit path/hash only; location outside auto-cleaned worktrees or protected
  - **R-IDs:** R8
- [x] 3.6 Append `elapsedMs` (optional subprocess times) on driver-transition / execute_mechanical without secrets (R9)
  - **File:** `scripts/wave_deliver_loop.py`
  - **Expected:** Log events include elapsedMs; no secret-bearing argv; gate semantics unchanged
  - **R-IDs:** R9
- [x] 3.7 Harness: drain true/false + no-progress/max-steps; slim manifest miss/mismatch; elapsedMs present (R15 f–g)
  - **File:** `scripts/unit_tests/`
  - **Expected:** R15(f)(g) covered
  - **R-IDs:** R15

### 4. Ops/contract — cleanup, budget isolation, status vocab, facade (R10–R13, R16) — medium

- [x] 4.1 Scope cleanup inflight to run/worktree; protect all non-terminal verdicts (R10)
  - **File:** `scripts/cleanup_lib.py`
  - **Expected:** Unrelated running scoped state does not block terminal orch cleanup; blocked/halted/watching protected
  - **R-IDs:** R10
- [x] 4.2 Terminal-class-only dry-run; terminal verdict allowlist for `cleanup.autonomy: auto` (R11, TR6)
  - **File:** `scripts/cleanup_lib.py`
  - **Expected:** Shared allowlist constant; resumable halt → hygiene note no candidates; auto only allowlisted terminal
  - **R-IDs:** R11
- [x] 4.3 Per-run request-budget ledger isolation + github maxCalls 750 (R12, TR3)
  - **File:** `scripts/planning_request_budget.py`
  - **Expected:** Parallel charges do not clobber; fail-closed exhaustion enforceable; default 750
  - **R-IDs:** R12
- [x] 4.4 Critical status ops bypass/revalidate cache; non-critical TTL cache OK (R12)
  - **File:** `scripts/planning_request_budget.py`
  - **Expected:** critical=True does not serve stale-within-TTL as authoritative; bulk non-critical may cache
  - **R-IDs:** R12
- [x] 4.5 Canonical four-state vocab; unknown/unauthorized non-terminal; auth errors fail-closed (R13)
  - **File:** `scripts/planning_unit_status.py`
  - **Expected:** Gates never treat unknown as complete; docs/tests do not require identical cross-backend strings
  - **R-IDs:** R13
- [x] 4.6 Route touched status/budget/discover/scheduler issue access via planning_store facade; lint clean (R16)
  - **File:** `scripts/planning_unit_status.py`
  - **Expected:** `lint-facade-imports` clean for newly touched scripts; 061 baseline dependency honored
  - **R-IDs:** R16
- [x] 4.7 Harness: halted-awaiting-human protected; terminal allowlist auto; parallel ledger; unknown never green-lights; facade lint (R15 h–k)
  - **File:** `scripts/unit_tests/`
  - **Expected:** R15(h)(i)(j)(k) covered
  - **R-IDs:** R15

### 5. Docs, merge policy, metrics, release completeness (R17–R20, R19) — small

- [x] 5.1 Document R17 merge policy in deliver/conductor surfaces (R17)
  - **File:** `core/commands/sw-deliver.md`
  - **Expected:** Correctness+terminal (R1–R5) green before merging perf/ops unless exception logged
  - **R-IDs:** R17
- [x] 5.2 Record R18 success metrics in PRD completion / verify notes path (R18)
  - **File:** `core/skills/conductor/SKILL.md`
  - **Expected:** Four operator metrics listed as release acceptance checks
  - **R-IDs:** R18
- [x] 5.3 Update conductor skill for drain + elapsedMs (R19)
  - **File:** `core/skills/conductor/SKILL.md`
  - **Expected:** drainMechanical default true/false, termination conditions, max-steps/no-progress, elapsedMs
  - **R-IDs:** R19
- [x] 5.4 Update sw-deliver + sw-cleanup commands (R19)
  - **File:** `core/commands/sw-cleanup.md`
  - **Expected:** Scoped inflight, terminal-class dry-run, allowlist auto-delete documented
  - **R-IDs:** R19
- [x] 5.5 Update sw-deliver for materialize/`--issue`/drain (R19)
  - **File:** `core/commands/sw-deliver.md`
  - **Expected:** R1/R2/R7 operator-facing behavior documented
  - **R-IDs:** R19
- [x] 5.6 Update config schema examples + layout for slim status, budget 750, drain (R19)
  - **File:** `.sw/layout.md`
  - **Expected:** Slim manifest ownership, elapsedMs, scoped cleanup, query cache semantics documented
  - **R-IDs:** R19
- [x] 5.7 Update README + guides for status reference-map and new knobs (R19)
  - **File:** `docs/guides/configuration.md`
  - **Expected:** Four-state + unknown non-terminal; drain; maxCalls 750; cleanup autonomy
  - **R-IDs:** R19
- [x] 5.8 Release completeness checklist tying R1–R19 (R20)
  - **File:** `scripts/unit_tests/`
  - **Expected:** Meta check or completion note that unit not complete until R1–R19 satisfied
  - **R-IDs:** R20

## Phase Dependencies

| Phase | Depends on |
| --- | --- |
| 1 | none |
| 2 | none |
| 3 | 1, 2 |
| 4 | 1, 2 |
| 5 | 1, 2, 3, 4 |

## Execute-tier granularity

> Frozen artifact (PRD 055 R17). Generated by `python3 scripts/tasks_generate.py apply-granularity` before `/sw-freeze`.

```json
{
  "generatedBy": "tasks_generate.py",
  "refSplits": [],
  "splitPreflight": {
    "costEstimate": {
      "estimate": 81,
      "mergeGates": 9,
      "projectedWaves": 9
    },
    "notices": [
      "phase 1: scopeUnderDeclared (12 implied path(s) not in **File:** lines)",
      "phase 2: scopeUnderDeclared (12 implied path(s) not in **File:** lines)",
      "phase 3: scopeUnderDeclared (20 implied path(s) not in **File:** lines)",
      "phase 4: scopeUnderDeclared (18 implied path(s) not in **File:** lines)",
      "phase 5: scopeUnderDeclared (18 implied path(s) not in **File:** lines)"
    ],
    "phaseCount": 5,
    "splitSuggestions": [
      {
        "externalEdges": [
          {
            "from": "1d",
            "kind": "split-fan-out",
            "to": "3"
          },
          {
            "from": "1d",
            "kind": "split-fan-out",
            "to": "4"
          },
          {
            "from": "1d",
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
          },
          {
            "from": "1c",
            "kind": "serial",
            "to": "1d"
          }
        ],
        "phase": "1",
        "preflight": {
          "baselineMaxWaveWidth": 2,
          "baselinePhaseCount": 5,
          "maxWaveWidth": 4,
          "notices": [
            "contention: phases 1d and 2 serialized (scripts/unit_tests/)",
            "contention: phases 3 and 4 serialized (scripts/unit_tests/)",
            "contention injected 2 edge(s)"
          ],
          "parallelCeiling": 10,
          "projectedPhaseCount": 8,
          "verdict": "pass",
          "waves": [
            [
              "1a",
              "1b",
              "1c",
              "1d"
            ],
            [
              "2"
            ],
            [
              "3"
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
              "scripts/dispatch_prompt.py"
            ],
            "id": "1a"
          },
          {
            "files": [
              "scripts/planning_deliver_gate.py"
            ],
            "id": "1b"
          },
          {
            "files": [
              "scripts/planning_materialize.py"
            ],
            "id": "1c"
          },
          {
            "files": [
              "scripts/unit_tests/"
            ],
            "id": "1d"
          }
        ]
      },
      {
        "externalEdges": [
          {
            "from": "2c",
            "kind": "split-fan-out",
            "to": "3"
          },
          {
            "from": "2c",
            "kind": "split-fan-out",
            "to": "4"
          },
          {
            "from": "2c",
            "kind": "split-fan-out",
            "to": "5"
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
          }
        ],
        "phase": "2",
        "preflight": {
          "baselineMaxWaveWidth": 2,
          "baselinePhaseCount": 5,
          "maxWaveWidth": 3,
          "notices": [
            "contention: phases 1 and 2b serialized (scripts/unit_tests/)",
            "contention: phases 3 and 4 serialized (scripts/unit_tests/)",
            "contention injected 2 edge(s)"
          ],
          "parallelCeiling": 10,
          "projectedPhaseCount": 7,
          "verdict": "pass",
          "waves": [
            [
              "1",
              "2a",
              "2c"
            ],
            [
              "3",
              "2b"
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
              "scripts/docs-currency-gate.py"
            ],
            "id": "2a"
          },
          {
            "files": [
              "scripts/unit_tests/"
            ],
            "id": "2b"
          },
          {
            "files": [
              "scripts/wave_terminal.py"
            ],
            "id": "2c"
          }
        ]
      },
      {
        "externalEdges": [
          {
            "from": "1",
            "kind": "split-fan-in",
            "to": "3a"
          },
          {
            "from": "2",
            "kind": "split-fan-in",
            "to": "3a"
          },
          {
            "from": "3f",
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
          },
          {
            "from": "3c",
            "kind": "serial",
            "to": "3d"
          },
          {
            "from": "3d",
            "kind": "serial",
            "to": "3e"
          },
          {
            "from": "3e",
            "kind": "serial",
            "to": "3f"
          }
        ],
        "phase": "3",
        "preflight": {
          "baselineMaxWaveWidth": 2,
          "baselinePhaseCount": 5,
          "maxWaveWidth": 5,
          "notices": [
            "contention: phases 1 and 2 serialized (scripts/unit_tests/)",
            "contention: phases 1 and 3e serialized (scripts/unit_tests/)",
            "contention: phases 2 and 3e serialized (scripts/unit_tests/)",
            "contention injected 3 edge(s)"
          ],
          "parallelCeiling": 10,
          "projectedPhaseCount": 10,
          "verdict": "pass",
          "waves": [
            [
              "1",
              "3b",
              "3c",
              "3d",
              "3f"
            ],
            [
              "2"
            ],
            [
              "4",
              "3a",
              "3e"
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
              ".sw/config.schema.json"
            ],
            "id": "3a"
          },
          {
            "files": [
              "scripts/"
            ],
            "id": "3b"
          },
          {
            "files": [
              "scripts/check_gate_lib.py"
            ],
            "id": "3c"
          },
          {
            "files": [
              "scripts/resolve_base_branch.py"
            ],
            "id": "3d"
          },
          {
            "files": [
              "scripts/unit_tests/"
            ],
            "id": "3e"
          },
          {
            "files": [
              "scripts/wave_deliver_loop.py"
            ],
            "id": "3f"
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
            "from": "2",
            "kind": "split-fan-in",
            "to": "4a"
          },
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
          "baselineMaxWaveWidth": 2,
          "baselinePhaseCount": 5,
          "maxWaveWidth": 3,
          "notices": [
            "contention: phases 1 and 2 serialized (scripts/unit_tests/)",
            "contention: phases 1 and 4d serialized (scripts/unit_tests/)",
            "contention: phases 2 and 4d serialized (scripts/unit_tests/)",
            "contention injected 3 edge(s)"
          ],
          "parallelCeiling": 10,
          "projectedPhaseCount": 8,
          "verdict": "pass",
          "waves": [
            [
              "1",
              "4b",
              "4c"
            ],
            [
              "2"
            ],
            [
              "3",
              "4a",
              "4d"
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
              "scripts/cleanup_lib.py"
            ],
            "id": "4a"
          },
          {
            "files": [
              "scripts/planning_request_budget.py"
            ],
            "id": "4b"
          },
          {
            "files": [
              "scripts/planning_unit_status.py"
            ],
            "id": "4c"
          },
          {
            "files": [
              "scripts/unit_tests/"
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
          }
        ],
        "phase": "5",
        "preflight": {
          "baselineMaxWaveWidth": 2,
          "baselinePhaseCount": 5,
          "maxWaveWidth": 3,
          "notices": [
            "contention: phases 1 and 2 serialized (scripts/unit_tests/)",
            "contention: phases 1 and 5d serialized (scripts/unit_tests/)",
            "contention: phases 2 and 5d serialized (scripts/unit_tests/)",
            "contention: phases 3 and 4 serialized (scripts/unit_tests/)",
            "contention injected 4 edge(s)"
          ],
          "parallelCeiling": 10,
          "projectedPhaseCount": 8,
          "verdict": "pass",
          "waves": [
            [
              "1",
              "5b",
              "5c"
            ],
            [
              "2"
            ],
            [
              "3",
              "5d"
            ],
            [
              "4"
            ],
            [
              "5a"
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
              "core/commands/sw-cleanup.md",
              "core/commands/sw-deliver.md",
              "core/skills/conductor/SKILL.md"
            ],
            "id": "5b"
          },
          {
            "files": [
              "docs/guides/configuration.md"
            ],
            "id": "5c"
          },
          {
            "files": [
              "scripts/unit_tests/"
            ],
            "id": "5d"
          }
        ]
      }
    ]
  },
  "taskList": "/tmp/sw-prd062/tasks.md",
  "version": 1
}
```

## Traceability

| R-ID | Task | Test scenario | ZOMBIES checklist |
| --- | --- | --- | --- |
| R1 | 1.1, 1.4 | materialize-before-discover | Z, O, I, E |
| R2 | 1.2, 1.4 | tasks-normalize-strict | O, B, I, E |
| R3 | 1.3, 1.4 | phase-ship-intensity-directive | O, I, E |
| R4 | 2.1, 2.2, 2.4 | docs-currency-slug-readonly | Z, O, I, E |
| R5 | 2.3, 2.4 | terminal-prepare-recoverable-fatal | O, I, E, S |
| R6 | 3.1 | base-capture-orch-worktree | O, B, I, E |
| R7 | 3.2, 3.3, 3.7 | drain-mechanical-no-progress | O, M, B, I, E, S |
| R8 | 3.4, 3.5, 3.7 | slim-manifest-fail-closed | Z, O, I, E |
| R9 | 3.6, 3.7 | elapsedMs-driver-transition | O, I |
| R10 | 4.1, 4.7 | cleanup-scoped-inflight | O, M, I, E, S |
| R11 | 4.2, 4.7 | cleanup-terminal-allowlist | O, I, E, S |
| R12 | 4.3, 4.4, 4.7 | budget-isolation-critical-fresh | O, M, B, I, E, S |
| R13 | 4.5, 4.7 | status-vocab-unknown-nonterminal | O, I, E, S |
| R14 | 1.1, 3.2 | file-store-parity-shared-knobs | O, I |
| R15 | 1.4, 2.4, 3.7, 4.7 | harness-matrix-a-through-k | Z, O, M, B, I, E, S |
| R16 | 4.6, 4.7 | facade-lint-touched-scripts | O, I, E |
| R17 | 5.1 | merge-policy-r1-r5-before-perf | O, I, S |
| R18 | 5.2 | operator-success-metrics | O, I |
| R19 | 5.3–5.7 | docs-currency-surfaces | O, I |
| R20 | 5.8 | single-release-completeness | O, I, S |

## Notes

- Soft-priority dispatch allows phases 1∥2 and 3∥4 when contention permits; R17 merge policy is encoded as phase 3/4 depending on 1+2.
- Per-run budget ledger isolation is in scope (doc-review P1); do not defer.
- Living INDEX/GAP-BACKLOG updates remain living-doc gate owned — not phase 5.