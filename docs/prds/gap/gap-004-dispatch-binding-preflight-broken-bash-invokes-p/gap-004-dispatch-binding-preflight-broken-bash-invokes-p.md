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
3. Natural amendment home for both: PRD 024 (already has A1 + A2 in this exact area) — a new A3, since A2's own
   "GAP-040" framing ("command-vs-agent split is residual") is the same family of dispatch-binding defect.
4. **Defect C:** fix the `secret_scan.main(["pre-push"])` call to match the zero-arg signature (or give
   `secret_scan.main` an optional mode parameter if `git-push.py` needs to pass one) and add a regression
   fixture that actually invokes `scripts/git-push.py --dry-run`-equivalent (or imports + calls `main()`
   directly) so a broken push chokepoint fails CI immediately rather than being discovered manually mid-push.
   Given Defects A and C share one root-cause commit, consider auditing the rest of `bd9ab91e`'s squashed
   `.sh`→`.py` ports for further signature/interpreter mismatches in one pass rather than per-discovery PRs
   (PR #261 already fixed one such instance independently).

