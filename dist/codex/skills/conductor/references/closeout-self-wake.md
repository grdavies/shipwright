# Terminal merge close-out self-wake (PRD 070)

While deliver state is `completed-pending-merge` after `/sw-retrospective --pre-merge`, the same
`DELIVER_WAKE_<run-id>` sentinel may drive **merge-boundary close-out** without a second operator command.
The conductor (or a background shell armed with `notify_on_output`) polls merged state and invokes:

```bash
RUN_ID="sw-deliver-070-automated-delivery-closeout"   # from scoped deliver state
python3 scripts/deliver_closeout.py self-wake-poll --run-id "$RUN_ID"
# or bounded loop:
python3 scripts/deliver_closeout.py self-wake --run-id "$RUN_ID"
```

**Disambiguation:** `run-id` selects the correct deliver among concurrent runs (`sw-deliver-<prd>-<slug>` from
`.cursor/sw-deliver-state.<slug>.json`). Close-out runs only when `completed-pending-merge` is set **and**
real merge detection succeeds — never on provisional signals.

**Idempotency:** correctness derives from the completeness audit; an optional close marker under
`.sw/deliver-closeout/close-markers/` is written only after audit-pass and re-verified on short-circuit. A
second trigger over the same delivery is a no-op; concurrent triggers converge to one fully-closed result.

**CI fallback:** when the session ends before merge, `.github/workflows/deliver-closeout.yml` on `main` push
invokes `scripts/closeout_ci.py` using the immutable PR mapping — the conductor self-wake and CI driver are
complementary layers, not duplicates.
