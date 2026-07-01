# ZOMBIES test-list-first (PRD 039 R11)

Use the **ZOMBIES** mnemonic when authoring tests before implementation:

| Letter | Case | Prompt |
| --- | --- | --- |
| **Z** | Zero | Empty / null / missing inputs |
| **O** | One | Single minimal valid instance |
| **M** | Many | Multiple items, batch, collection |
| **B** | Boundaries | Edges, limits, off-by-one |
| **I** | Interfaces | Public contract, errors, idempotency |
| **E** | Exceptions | Failure modes, validation errors |
| **S** | State | Stateful transitions, persistence |

## Traceability checklist

When a task row lists a **named test scenario**, the traceability table MUST include a non-empty
**ZOMBIES checklist** (comma-separated cases or bullet list in the fourth column). `/sw-execute` runs
`python3 scripts/zombies_gate.py` before TDD red when `testScenario` is bound.

## Gate

```bash
python3 scripts/zombies_gate.py --record /tmp/sw-traceability.record.json
```

Exit `20` when `testScenario` is set but `zombiesChecklist` is empty.
