# RCA fan-out mode (PRD 064 R1/R2)

Opt-in multi-hypothesis investigation. **Default remains single-context** shared discipline.

## Config (`rca.fanout`)

| Key | Default | Meaning |
| --- | --- | --- |
| `enabled` | `false` | Master switch — off keeps today's single-context loop |
| `min_hypotheses` | `3` | Fan-out when initial pass yields fewer ranked hypotheses |
| `ambiguity_trigger` | `true` | Fan-out when ambiguity markers fire (D5) |
| `max_width` | `4` | Cap parallel generators (hard max 4 slots) |

Resolve live config:

```bash
python3 scripts/rca_fanout.py config --root .
```

## D5 gating

Fan-out runs only when `enabled: true` **and** at least one gate fires:

1. **Ambiguity trigger** — explicit `ambiguous: true`, user report without repro, multiple error signatures, or conflicting evidence classes.
2. **Below `min_hypotheses`** — single-context pass produced too few hypotheses.
3. **Multi-evidence-class** — two or more non-empty partitions among logs/diff/data/config.

Otherwise stay on single-context shared discipline.

```bash
python3 scripts/rca_fanout.py should-fanout --signal /path/to/signal.json
```

## Generator phase (R1)

At most four clean-context generators partition evidence:

| Slot | Evidence |
| --- | --- |
| `logs` | Stack traces, log excerpts, Sentry breadcrumbs |
| `diff` | Recent deploy/diff context |
| `data` | Runtime/metrics/query signals |
| `config` | Env, workflow config, related files |

Plan partitions:

```bash
python3 scripts/rca_fanout.py plan --signal /path/to/signal.json
```

Dispatch one fresh `sw-rca-hypothesis-generator` Task per generator (`readonly: true`, cheap tier). **Generators never share context.**

Brief per generator:

```bash
python3 scripts/rca_fanout.py generator-brief --plan /tmp/plan.json --generator-id gen-1
```

Synthesize merged hypotheses:

```bash
python3 scripts/rca_fanout.py synthesize --results /tmp/generator-results.json
```

## Refuter phase (R2)

Each synthesized survivor routes to a **separate** `sw-rca-hypothesis-refuter` Task before any route decision. Refuters receive only the hypothesis + redacted signal summary — **never** generator transcripts (generation and judging never share a context).

```bash
python3 scripts/rca_fanout.py refuter-brief --hypothesis /tmp/hyp.json --signal-summary /tmp/summary.json
python3 scripts/rca_fanout.py evaluate --hypotheses /tmp/hyps.json --refutations /tmp/refutations.json
```

A hypothesis **survives** only when the refuter returns `verdict: survives` **and** `causalChainComplete: true` (causal-chain gate). Route decisions use `evaluate` output `topSurvivor`.

## Status artifact

Persist fan-out state under `.cursor/sw-debug-runs/<runId>/rca-fanout.status.json` when invoked from `/sw-debug` or stabilize RCA surfaces.
