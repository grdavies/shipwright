#!/usr/bin/env python3
"""PRD 039 phase-4 decision-log / provenance fixtures."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from _sw.vendor_paths import repo_root

SCRIPT_DIR = Path(__file__).resolve().parent
_SCRIPTS_ROOT = SCRIPT_DIR.parents[1]
_TEST_DIR = _SCRIPTS_ROOT / "test"
ROOT = repo_root(__file__)
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))

from decision_log import parse_body, ship_require, validate_record


def ok(msg: str) -> None:
    print(f"OK  {msg}")


def bad(msg: str) -> int:
    print(f"FAIL {msg}")
    return 1


def sample_body(extra: str = "") -> str:
    record = {
        "intent": "Implement provenance capture for ship",
        "alternativesRuledOut": ["Store only in git notes"],
        "highRiskAreas": ["gate promotion", "redaction chokepoint"],
        "taskRefs": ["4.2"],
    }
    return f"""## Summary
<!-- required:summary -->

summary text

## Decision log
<!-- required:decision-log -->

```json
{json.dumps(record)}
```
{extra}
"""


def main() -> int:
    fail = 0
    good = validate_record(
        {
            "intent": "x",
            "alternativesRuledOut": ["a"],
            "highRiskAreas": ["b"],
            "taskRefs": ["c"],
        }
    )
    if good.get("verdict") == "pass":
        ok("decision-log schema-valid record passes")
    else:
        fail = bad(f"schema-valid: {good}") or fail

    parsed = parse_body(sample_body())
    if parsed.get("verdict") == "pass":
        ok("PR body decision log parses and redacts")
    else:
        fail = bad(f"parse body: {parsed}") or fail

    secret_body = sample_body().replace(
        "Implement provenance capture for ship",
        "Token ghp_1234567890123456789012345678901234567890 leaked",
    )
    blocked = parse_body(secret_body)
    if blocked.get("verdict") == "fail" and blocked.get("reason") == "redaction-required":
        ok("redaction fail-closed on sensitive decision-log content")
    else:
        fail = bad(f"redaction fail-closed: {blocked}") or fail

    missing = ship_require("## Summary\n\nno decision log\n")
    if missing.get("shipBlocked"):
        ok("missing decision log fails ship helper")
    else:
        fail = bad(f"missing ship: {missing}") or fail

    tpl = ROOT / "core/sw-reference/templates/pr-body.md"
    if "<!-- required:decision-log -->" in tpl.read_text(encoding="utf-8"):
        ok("pr-body template includes decision log marker")
    else:
        fail = bad("pr-body template marker") or fail

    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/git_template_lib.py"), "validate", "pr-body", "--body", sample_body()],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        result = json.loads(proc.stdout)
        if result.get("verdict") == "pass":
            ok("git_template_lib validates decision log field")
        else:
            fail = bad(f"template validate: {result}") or fail
    else:
        fail = bad(f"git_template_lib exit {proc.returncode}: {proc.stderr}") or fail

    return fail


if __name__ == "__main__":
    raise SystemExit(main())
