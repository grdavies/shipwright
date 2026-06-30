---
id: gap-004-dispatch-binding-preflight-broken-bash-invokes-p
type: gap
status: open
title: Dispatch-binding preflight broken: bash invokes .py scripts, and interactive parent models are not in models.tiers
visibility: public
tags: [source:feedback, signal:feedback-dispatch-binding-bash-invocation-2026-06-30]
---

# Dispatch-binding preflight broken: bash invokes .py scripts, and interactive parent models are not in models.tiers

_Captured from feedback signal `feedback-dispatch-binding-bash-invocation-2026-06-30`._

## Two independent defects, both blocking every Task dispatch this session

This signal was reported as a single "tooling blocker" but is two stacked, independently-reproducing defects.
Either one alone fails dispatch preflight closed (`exit 20`); both were hit in this session.

### Defect A — `bash` invokes `.py` scripts (PRD 042 incomplete-migration regression, repo-wide)

`scripts/wave_preflight.py:cmd_dispatch` resolves the model/intensity for a delegated Task via:

```277:278:scripts/wave_preflight.py
model_cmd = ["bash", str(SCRIPT_DIR / "resolve-model-tier.py"), "--agent", agent]
intensity_cmd = ["bash", str(SCRIPT_DIR / "resolve-intensity.py"), "--agent", agent]
```

`resolve-model-tier.py` is a Python script (no shebang executed — invoked as an argv list, not `./script`).
Running it as `bash <file>.py` either errors immediately on Python syntax or — depending on shell quoting —
silently produces no parseable JSON, so `model_payload.get("modelId")` is empty and `cmd_dispatch` fails closed
with `cause: binding:no-model` (`exit 20`). This is exactly the `wave.py dispatch preflight` /
`dispatch-check.py` failure observed in this sandbox.

**Root cause (git-blamed, dated *today*):** commit `bd9ab91e` ("fix(ci): repair Python ports and fixture
harness for PR #256", PRD 042 cross-platform-python-standardization) renamed `resolve-model-tier.sh` →
`resolve-model-tier.py` (and the intensity equivalent) but only changed the **filename string** at this call
site — it left the interpreter literal as `"bash"` instead of `sys.executable` / the resolved interpreter
probe (the correct pattern already exists at `wave.py`'s own `_python()` helper and at
`core/hooks/guardrail_core.py:75` / `scripts/verify-e2e.py:43,55`, both of which branch on `script.suffix`).

```315:321:scripts/wave_preflight.py (git show bd9ab91e^:scripts/wave_preflight.py vs current)
-    model_cmd = ["bash", str(SCRIPT_DIR / "resolve-model-tier.sh"), "--agent", agent]
-    intensity_cmd = ["bash", str(SCRIPT_DIR / "resolve-intensity.sh"), "--agent", agent]
+    model_cmd = ["bash", str(SCRIPT_DIR / "resolve-model-tier.py"), "--agent", agent]
+    intensity_cmd = ["bash", str(SCRIPT_DIR / "resolve-intensity.py"), "--agent", agent]
```

**This is not an isolated typo — it is a systemic, repo-wide pattern** from the same `.sh`→`.py` migration.
Every `.sh` file under `scripts/`/`core/hooks/` is gone (confirmed: zero matches for `find scripts core/hooks
-name "*.sh"`), but the following call sites still hardcode `"bash"` against what is now exclusively a `.py`
target, and are therefore equally broken today (verified by reading each, 2026-06-30):

| File:line | Target script | Reachable from |
|---|---|---|
| `scripts/wave_preflight.py:277,278` | `resolve-model-tier.py`, `resolve-intensity.py` | every `/sw-*` dispatch preflight (this signal) |
| `core/hooks/before_task_dispatch.py:163` | `resolve-model-tier.py` | the `preToolUse` Task-dispatch hook itself |
| `scripts/wave.py:43` (`_bash()` helper) → callers at `scripts/wave.py:70,71` | `tasks-currency-gate.py`, `docs-currency-gate.py` | `/sw-verify`, terminal-ship gate (R50) |
| `scripts/wave_terminal.py:570` | `docs-currency-gate.py` | terminal-ship hard-block gate (duplicate path to the row above) |
| `scripts/wave_deliver_loop.py:1010` | `resolve-base-branch.py` | deliver-loop base-branch capture |
| `scripts/wave_deliver_loop.py:1529` | `inflight-signal.py` | deliver-loop in-flight signal |
| `scripts/memory_decision_snapshot.py:48,67` | `memory-sot.py`, `memory-redact.py` | memory decision snapshot |
| `scripts/memory_sot_audit.py:38` | `memory-sot.py` | memory SOT audit |
| `scripts/planning_related.py:298` (`redact_untrusted_payload`) | `memory-redact.py` | planning-store untrusted-payload redaction |
| `scripts/sw-configure.py:20` | `detect-project-type.py` | `/sw-init`/`/sw-setup` project detection |
| `scripts/feedback-closure-gate.py:18` | `feedback-backlog.py` | feedback-closure gate |

**Not a stale finding — confirmed live on `origin/main` after `git fetch`:** `git show origin/main:scripts/wave_preflight.py`
still has lines 277–278 as `["bash", ...]` as of this session. PR #261 ("fix(worktree): restore provision guard
and Python-first script invocation", merged 2026-06-30T21:03) already fixed the *same defect class* but only
for one file (`wave_lifecycle.py`'s `assert_primary_off_target` callers) — confirming this is a recognized
pattern being patched piecemeal, one discovery at a time, rather than swept once across all sites.

### Defect B — parent-model-tier resolution fails closed for any interactive/chat session

Independent of Defect A: `scripts/dispatch-check.py:model_to_tier()` resolves a session's tier by an **exact
string match** of the parent model id against `.cursor/workflow.config.json` `models.tiers` values:

```40:44:scripts/dispatch-check.py
def model_to_tier(concrete: str):
    for tier_name, model in tiers.items():
        if model == concrete:
            return tier_name
    return None
```

Current `models.tiers` = `{cheap: composer-2.5-fast, build: composer-2.5, mid: gpt-5.5-medium, deep:
claude-opus-4-8-thinking-high}`. This session's actual parent model ("Sonnet 5") is not a value in that map by
construction — `models.tiers` enumerates which models *internal* command/skill/agent routing should use, not
every model a human might pick in the IDE. Any interactive session running on a model that happens not to
collide with one of those 4 strings gets `parent_rank = None` → fails closed with `cause: binding:no-model`,
`remediation: "resolve parent session to a concrete models.tiers id before dispatch"` — which is not actually
actionable from inside the chat session (the human picked the model in the IDE, not via `models.tiers`).

This combination (Defect A failing every dispatch mechanically, Defect B failing closed for any
non-`models.tiers` parent model even once A is fixed) made every attempted subagent dispatch in this session
fail, forcing inline execution of `/sw-doc-review` and `/sw-freeze` work that should have been delegated per
`rules/sw-subagent-dispatch.mdc`.

### Defect C — the R23 push chokepoint itself is broken (same root-cause commit)

While pushing this very signal's gap-capture commit, `scripts/git-push.py` (the **only** sanctioned push path
per the conductor skill's R23: "Push chokepoint — `scripts/git-push.py` only — secret-scan pre-push") crashed
before reaching `git push`:

```19:20:scripts/git-push.py
import secret_scan
secret_scan.main(["pre-push"])
```

```246:scripts/secret_scan.py
def main() -> int:
```

`secret_scan.main()` takes **zero** arguments; `git-push.py` calls it with a one-element list, raising
`TypeError: main() takes 0 positional arguments but 1 was given` on every invocation — `git-push.py` cannot
complete a push at all today, for any branch. This forces a fallback to raw `git push`, which **silently skips
the secret-scan pre-push check** R23 exists to enforce — the exact guardrail-bypass class R23 was written to
prevent, now unavoidable because the chokepoint script itself is broken.

**Same root cause as Defects A and B:** `git blame` on both the crashing call site
(`scripts/git-push.py:19-20`) and `wave_preflight.py:277-278` (Defect A) point to the **same commit**,
`bd9ab91e` ("feat(prd-42): deliver wave (#256)") — a single large squashed PRD-042 delivery commit that ported
multiple `.sh` entrypoints to Python in one pass (`git-push.sh`→`git-push.py` included) and introduced this
class of signature/interpreter mismatch in several of the newly-ported files simultaneously. `secret_scan.py`'s
own `main()` signature is unchanged since 2026-06-25 — only the caller in the newly-ported `git-push.py`
passes an argument it never accepted.

## Lineage

- Defects A and C are both regressions introduced by the **same commit**, `bd9ab91e` (PRD 042
  cross-platform-python-standardization, "complete") — the exact program whose purpose was eliminating
  shell/Python interpreter mismatches; the squashed delivery commit ported many `.sh` scripts to `.py` in one
  pass and several call sites/signatures did not get updated to match.
- Defect B is adjacent to PRD 012 (model-tier-runtime-binding) and PRD 024 A2 ("dispatch-binding parallel
  preflight and command tier" — GAP-039/GAP-040), both "complete". A2 already fixed the `--agent`-vs-`--command`
  precedence half of dispatch-binding; it does not address either the interpreter bug or the
  unregistered-parent-model case.

## Suggested remediation

1. **Defect A:** one sweep, not another one-off PR — replace every `["bash", str(script), ...]` invocation of a
   `.py` target in the table above with the same `script.suffix`-aware pattern already used by
   `core/hooks/guardrail_core.py` and `scripts/verify-e2e.py` (or `wave.py`'s own `interpreter.probe()` +
   `_python()` helper). Add a regression fixture that greps for `\["bash"` against any `.py` target under
   `scripts/`/`core/hooks/` and fails CI — this exact class of regression has now shipped twice (this defect,
   plus the independently-discovered `wave_lifecycle.py` instance fixed in PR #261) without a guard preventing
   a third.
2. **Defect B:** add an explicit fallback for an unregistered/interactive parent model rather than a hard
   `binding:no-model` fail — e.g. treat unknown parent models as the most permissive tier with a logged
   warning, or resolve via the platform's own concrete-model capability rather than requiring `models.tiers`
   membership. Needs an explicit decision (see Open Questions) since it changes the R9 model-tier-floor
   contract's failure mode.
3. ~~Natural amendment home for both: PRD 024 (already has A1 + A2 in this exact area).~~ Superseded — see
   "Resolution status" below: Defects A/C were fixed directly; a PRD 024 A3 for Defect B was drafted and then
   discarded (PRD 024 is `complete`, no active implementation vehicle — see gap-006 and the Open Questions
   routing note for the worked design that would have been A3's content).
4. **Defect C:** fix the `secret_scan.main(["pre-push"])` call to match the zero-arg signature (or give
   `secret_scan.main` an optional mode parameter if `git-push.py` needs to pass one) and add a regression
   fixture that actually invokes `scripts/git-push.py --dry-run`-equivalent (or imports + calls `main()`
   directly) so a broken push chokepoint fails CI immediately rather than being discovered manually mid-push.
   Given Defects A and C share one root-cause commit, consider auditing the rest of `bd9ab91e`'s squashed
   `.sh`→`.py` ports for further signature/interpreter mismatches in one pass rather than per-discovery PRs
   (PR #261 already fixed one such instance independently).

## Open Questions (Defect B)

1. What should `dispatch-check.py:model_to_tier()` do when the parent session's concrete model id is not a
   value in `models.tiers`? Candidates: (a) treat as the most permissive tier (`deep`) with a logged warning —
   simplest, but weakens the R9 floor for any unregistered model; (b) require an explicit
   `dispatch.unregisteredParentModelTier` config fallback, defaulting fail-closed (today's behavior) unless
   set — preserves R9 intent but needs a one-time operator config write; (c) resolve via the platform's own
   capability metadata for the concrete model id (if the host exposes one) rather than requiring static
   `models.tiers` membership — most correct, most implementation cost. Whichever fix is chosen should amend
   R9's failure-mode language explicitly, not just patch the code.
2. Should `models.tiers` be extended to enumerate *all* models a human might select interactively, or kept
   scoped to internal command/skill/agent routing only (today's design) with a separate fallback path for (1)?

**Worked design, not shipped (routing note):** a candidate fix was drafted in full (narrow the unconditional
`dispatch-check.py` fail to only fire for `sw-*-reviewer`/native-panel-bound dispatches that actually consume
`parent_rank`; add an explicit `dispatch.unregisteredParentModelTier` config fallback, default unset/fail-closed,
with an invalid-tier-value distinct fail cause) as a PRD 024 amendment, then discarded undrafted — PRD 024 is
`complete` in `INDEX.md` with no active implementation vehicle, and **gap-006** (filed alongside this one)
independently found that PRD 033's most recent amendment suffered exactly this fate (frozen, "complete", never
implemented). Per operator decision (2026-06-30 second `/sw-feedback` pass), this stays a gap-only finding —
not a PRD amendment — until there is an active implementation vehicle for it. The worked design above is
preserved here so a future fix does not have to re-derive it.

## Resolution status (2026-06-30, this branch)

Per operator routing decision, Defects A and C were fixed directly in this branch rather than deferred to a
separate PR, with regression fixtures. Defect B is **not** fixed here — it needs an explicit product decision
on the R9 model-tier-floor failure mode (see Open Questions below) and, per a later routing decision in this
same `/sw-feedback` pass, stays a gap-only finding rather than a PRD amendment (PRD 024 is `complete` with no
active implementation vehicle — see the Open Questions "Worked design, not shipped" note and gap-006).

### Defect A — fixed (11 call sites + a missed 12th found while fixing)

All 11 call sites in the table above were changed from `["bash", str(script), ...]` to
`[sys.executable, str(script), ...]`:

`scripts/wave_preflight.py`, `core/hooks/before_task_dispatch.py`, `scripts/wave.py` (the `_bash()` helper
itself was removed — no `.sh` callers remained, so the indirection was dead weight, not just a wrong
interpreter), `scripts/wave_terminal.py`, `scripts/wave_deliver_loop.py` (×2), `scripts/memory_decision_snapshot.py`
(×2), `scripts/memory_sot_audit.py`, `scripts/planning_related.py`, `scripts/sw-configure.py`,
`scripts/feedback-closure-gate.py`.

**A 12th, previously-undocumented defect was found fixing Defect A and had to be fixed in the same pass:**
`scripts/resolve-model-tier.py`'s `main()` unpacked `sys.argv[1:8]` as 7 *positional* arguments
(`tier_arg, command, skill, agent, delegate, config_path, defaults_path = sys.argv[1:8]`) — every real caller
in the table above invokes it with `--agent`/`--command`/`--skill` *flags*, not positional args, so fixing
Defect A's interpreter alone still left every call site failing with
`ValueError: not enough values to unpack`. Rewrote `main()` to use `argparse` (mirroring the already-correct
`resolve-intensity.py` sibling), with the same `--tier`/`--command`/`--skill`/`--agent`/`--delegate`/`--config`/
`--defaults` flags and the same command→skill→agent→tier precedence semantics — verified byte-identical
output for `--agent`, `--command`, `--skill`, and `--tier` calling patterns against the pre-fix logic.

**Verification:**
- `python3 scripts/wave.py dispatch preflight --dispatch-id <id> --agent <agent> --command <cmd> --skill <skill>`
  now returns `{"verdict": "pass", ..., "modelId": ..., "nonce": ...}` end-to-end (previously failed closed
  with `cause: binding:no-model`, `exit 20` — exactly the `missing-preflight-nonce` blocker this signal named).
- `core/hooks/before_task_dispatch.py:resolve_dispatch_model` (the `preToolUse` hook itself) verified directly
  — resolves a concrete `modelId`/`tier` instead of failing closed.
- Added `scripts/test/bash-py-invocation-guard.test`: extends the existing `scripts/zero-shell-guard.py`
  R41 guard with a new `find_bash_py_invocations` detector (regex for `["bash", ..., "<x>.py"]` argv-list
  literals) wired into its `main()` issue list, so this exact regression class fails CI going forward rather
  than being rediscovered piecemeal (as it already had been once, via PR #261, before this signal). The
  fixture both exercises the detector against a synthetic offender and asserts the real `scripts/`/`core/`
  trees are clean.
- `scripts/copy-to-core.py` was run to sync all fixes into the `core/scripts/` build-chain mirror (which has
  its own independent copies per `core/sw-reference/build-chain-sot.json` — `zero-shell-guard.py` scans both
  trees, and the mirror was still carrying every pre-fix `["bash", ...]` instance until synced).

### Defect C — fixed, and the actual call was wrong in a second way

Beyond the `TypeError` (zero-arg `secret_scan.main()` called with one arg), the original code also bypassed
the **canonical CLI chokepoint**: `scripts/secret-scan.py` (hyphenated) is the actual sanctioned entrypoint —
it subprocess-invokes `scripts/secret_scan.py` (underscore, the implementation module) itself and additionally
handles an `inflight-tuple` mode `secret_scan.py` does not. `git-push.py`'s original `import secret_scan;
secret_scan.main(["pre-push"])` both crashed *and* skipped the canonical entrypoint's extra handling even on a
hypothetical correct call. Fixed to subprocess-invoke `secret-scan.py` (hyphenated) via `sys.executable`,
matching every other script's invocation convention in this codebase.

**Verification:**
- `scripts/secret-scan.py pre-push` and `scripts/secret_scan.py pre-push` both run clean with exit 0 (no
  `TypeError`).
- A pre-existing repo test, `scripts/test/secret-scan-behavioral.test` (subtest `git-push-chain`, line 45:
  `grep -q 'secret-scan.py' "$PUSH" && ok git-push-chain || bad git-push-chain`), **was already failing on
  `origin/main`** before this fix (confirmed by running the full `scripts/test/_runner.py run-all-tests` suite
  against a clean `origin/main` worktree) — independent, pre-existing corroboration of this exact defect that
  nothing had connected to this signal before. It now passes with the fix.
- Added `scripts/test/git-push-secret-scan-chokepoint.test`: monkeypatches `subprocess.run` inside
  `git-push.py:main()` to simulate a failing secret-scan, and asserts (a) `main()` returns non-zero and
  (b) `git push` is never invoked — i.e. the chokepoint actually blocks the push rather than silently falling
  through, which is the failure mode this defect produced in practice.
- Ran the full `scripts/test/_runner.py run-all-tests` suite before and after on both this worktree and a
  disposable `origin/main` detached worktree: `git-push-chain` flips fail→pass; no other test changes state
  in either direction (the small set of other pre-existing failures —`completion-log-idempotent`,
  `wave-no-shell-dispatch`, four `gh invocation remains in ...`, five `missing-python-module: ...`,
  `prd-index-derive-shape`, `planning-index-reconcile-route` — reproduce identically on bare `origin/main`,
  confirmed unrelated to this signal and out of scope here).

### Defect B — not fixed here, stays gap-only pending an implementation vehicle

No code change in this branch and no PRD amendment. The fix changes the R9 model-tier-floor contract's
failure mode and needs an explicit decision, not a unilateral inline fix — see Open Questions for the worked
candidate design, preserved for whoever picks this up next.

