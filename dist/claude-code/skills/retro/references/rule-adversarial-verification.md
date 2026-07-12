# Rule adversarial verification (PRD 064 R7)

Before any **rule-class** promotion candidate reaches the human gate:

1. Build evidence bundle (redacted retro narrative + related diff excerpts).
2. **Verifier** — `sw-rule-verifier` Task (`readonly: true`, cheap tier):

```bash
python3 scripts/rule_verification.py verifier-brief --rule /tmp/rule.json --evidence /tmp/evidence.json
```

3. **Skeptic** — `sw-rule-skeptic` Task on verifier output only (no raw transcript):

```bash
python3 scripts/rule_verification.py skeptic-brief --rule /tmp/rule.json --verifier-result /tmp/verifier.json
```

4. **Evaluate** — promotion readiness is advisory; human confirmation remains required:

```bash
python3 scripts/rule_verification.py evaluate --verifier-result /tmp/verifier.json --skeptic-result /tmp/skeptic.json --out /tmp/rule-verification.json
```

`promotionReady: true` means the candidate may be presented for human promotion — never auto-promoted.
