## Orchestrator adoption

| Orchestrator | Run durability | Adoption mode (PRD 024) | Status |
| --- | --- | --- | --- |
| `/sw-deliver` | **Durable** (PRD 007/013 run-state + crash-resume) | `full` when `planPolicy: proposed` | Pilot consumer (R34) — `deliver-loop` / `run` |
| `/sw-ship` | Phase-scoped (in-loop) | N/A (atomic chain) | Adopted (PRD 017) — SHIP-A1..A4 |
| `/sw-debug` | **Episodic** (session scratch; no crash-resume) | `full` | Adopted (PRD 017 + 024) — DBG-A1..A2 |
| `/sw-doc` | **Durable** (docs worktree → `/sw-deliver` handoff) | **`consistency-only` default** (R36c); `full` when variance probe shows latitude | Adopted (PRD 017 + 024) — DOC-A1..A2 |
| `/sw-feedback` | **Episodic** (session scratch; no crash-resume) | `full` | Adopted (PRD 017 + 024) — FB-A1..A2 |

**Durability (R37):** `durable` orchestrators may persist deliver/doc handoff run-state; `episodic`
debug/feedback validate at entry, surface R21 into `.cursor/sw-*-runs/<id>/episodic-run-summary.json`, and
abandon scratch on terminal halt — never deliver-scoped crash-resume.
