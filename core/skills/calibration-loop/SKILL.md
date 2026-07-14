---
name: calibration-loop
description: Converge on an ambiguous preference through concrete either/or instances instead of re-asking the same abstract question. Use when brainstorm divergence is unsure, a doc-review disposition is disputed, or feedback scope classification is ambiguous. Does not resolve unrelated ambiguity or bypass human confirmation on the converged rule.
---
# Calibration loop

A reusable convergence primitive for genuine either/or ambiguity — not a general Q&A loop. Presents one
concrete instance per turn, restates the inferred principle, and stops on stability.

**Model tier:** cheap — resolve via `python3 scripts/resolve-model-tier.py --skill calibration-loop`.

## When to use

Only when a prior attempt to resolve a preference/disposition abstractly has already failed (the operator
said "unsure", two reviewers disagree, or scope classification is genuinely ambiguous) — never as a first
resort over a direct question.

## Fixed verdict set

Every turn presents one **concrete** either/or instance (a specific example, not the abstract question again)
and accepts exactly one of a fixed vocabulary:

| Verdict | Meaning |
| --- | --- |
| `A` | This instance resolves toward option A |
| `B` | This instance resolves toward option B |
| `either` | Genuinely indifferent on this instance (informative — narrows the principle to "doesn't matter here") |
| `neither` | Instance is malformed or off-tension — discard, generate a better one |
| `more-info` | Operator needs one clarifying fact before verdicting this instance — answer, then re-present the same instance |

Never accept free text as the primary channel — free text is allowed only as an annotation alongside one of
the five verdicts above, never as a substitute for one.

## Procedure

1. **Frame the tension** — restate the two poles (A vs B) in one sentence from the blocked artifact
   (divergence stance pair, disputed disposition, ambiguous-scope routing).
2. **Present one concrete instance** — a specific, realistic case that would force a choice between A and B.
   Never present the abstract question a second time.
3. **Accept a verdict** from the fixed set above.
4. **Restate the inferred principle** — after each verdict, state the working rule in one sentence ("so:
   when X, prefer A; when Y, prefer B") and ask for a quick confirm/correct on the restatement, not a new
   open question.
5. **Adapt toward unexplored seams** — the next instance MUST probe a boundary the current principle has not
   yet been tested against (not a near-duplicate of the last instance). Track covered vs. unexplored seams
   explicitly in scratch notes for the run.
6. **Stop on stability** — converge when either:
   - two consecutive instances confirm the same restated principle with no correction, or
   - a hard cap of 5 instances is reached (whichever first). On cap-out without stability, record
     `converged: false` and escalate to explicit human decision — never silently pick a side.
7. **Write the converged rule into the blocked artifact** — the calling consumer (brainstorm, doc-review,
   feedback) persists the final principle at its own persistence point (see **Consumers** below); this skill
   never writes on its own — it returns the converged principle + verdict trail to the caller.

## Consumers (wired now)

| Consumer | Trigger | Where the converged rule lands |
| --- | --- | --- |
| `/sw-brainstorm` divergence (unsure routing) | Operator "unsure" between ~2 viable stances | Requirements doc **Key Decisions** — chosen stance + converged principle |
| `/sw-doc-review` disposition disputes | Synthesizer/reviewer disagreement on `safe_auto` vs `gated_auto`/`manual` for a finding class | Review-round synthesis notes; principle informs the disposition for that finding and future same-class findings in the run |
| `/sw-feedback` ambiguous-scope classification | Signal cannot be cleanly classed `gap-capture` vs `brainstorm` (or `substantial` vs `trivial`) | Route record (`skills/feedback/references/route-record.md`) — converged principle recorded alongside the route decision |

## Guardrails

- Never a substitute for a direct, answerable question — only for genuine either/or ambiguity after a first
  abstract attempt.
- Never accept the same instance twice in a row as "resolved" — each turn must probe a new seam.
- Cap-out (`converged: false`) always escalates to explicit human decision; never auto-resolves silently.
- This skill informs the blocked artifact — it does not itself freeze, merge, or dispatch anything.
