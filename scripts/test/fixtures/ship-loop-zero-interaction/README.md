# Ship-loop zero-interaction fixture (PRD 065 R17)

Hermetic bar for turn-independent `/sw-deliver` phase-mode shipping: the durable driver
(`wave_deliver_loop.py`) drains mechanical `dispatch-ship` steps inline and surfaces
`awaitAgent: true` only when `ship_loop.py` reaches an agent-classified chain step.

## Layout

| Path | Role |
| --- | --- |
| `frozen-task-list.md` | Minimal two-phase frozen list with `## Phase Dependencies` |
| `phase-a/` | Single mechanical step chain smoke (verify + gap-check only) |
| `phase-b/` | Agent-step handoff (`sw-execute`) with forged/missing outcome fixtures |

## Running locally

From repository root (harness mode):

```bash
export SW_HARNESS=1 SW_PHASE_MODE=1
python3 scripts/ship_loop.py . run --phase fixture-phase-a
python3 scripts/ship_loop.py . drive-tick --phase fixture-phase-a
```

Pytest coverage lives in `scripts/unit_tests/test_ship_loop_zero_interaction.py`.

## Zero-interaction contract

- Mechanical steps never emit `awaitAgent`.
- Agent steps emit `awaitAgent: true` with a binding outcome artifact path.
- Forged or head-mismatched outcome artifacts refuse `consume-outcome` and block `merge-ready-green`.
