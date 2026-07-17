## Self-wake sentinel (R8, R9)

For time-gated external waits (terminal-PR CI, long `checks.watch` polls), arm a **uniquely named**
background shell with `notify_on_output` so the conductor resumes without a user message.

**Run id** (stable per deliver run): `sw-deliver-<prd_number>-<target.slug>` from the scoped
`.cursor/sw-deliver-state.<slug>.json` (e.g. `sw-deliver-009-autonomous-orchestration-conductor`).

### Terminal-PR CI wait

After `/sw-pr` on the feature branch:

```bash
RUN_ID="sw-deliver-009-autonomous-orchestration-conductor"   # from state
PR=$(python3 scripts/host.py resolve-pr-for-branch)
python3 scripts/host.py checks --number "$PR"
echo "DELIVER_WAKE_${RUN_ID} {\"phase\":\"terminal-ci\",\"prd\":\"009\"}"
```

### Phase-mode dispatch-ship CI wait (PRD 063 R3)

For phase-PR CI (not terminal), use a **phase-unique** sentinel so concurrent phases do not collide:

```bash
PHASE_SLUG="<phase-slug>"   # from SW_PHASE_SLUG / deliver state
echo "DELIVER_WAKE_${RUN_ID}_${PHASE_SLUG} {\"phaseId\":\"<id>\",\"phaseSlug\":\"${PHASE_SLUG}\"}"
```

Arm with `notify_on_output` matching `^DELIVER_WAKE_${RUN_ID}_${PHASE_SLUG}`. Never reuse terminal-only `DELIVER_WAKE_${RUN_ID}` for in-wave phase CI.

Arm terminal `DELIVER_WAKE_${RUN_ID}` with `notify_on_output`; reuse `checks.watch` poll/max knobs. Close-out fast-path (PRD 070): [closeout-self-wake.md](closeout-self-wake.md).

### Teardown (R9)

On any terminal halt (`verdict: complete|blocked|rejected`) or human stop:

- Cancel/kill background shells tagged with `DELIVER_WAKE_<run-id>` and any deliver heartbeats for that run id.
- Never leave orphaned watchers holding tokens after the run ends.
