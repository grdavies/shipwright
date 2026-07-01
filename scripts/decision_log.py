#!/usr/bin/env python3
"""Parse, validate, and redact PR decision-log provenance (PRD 039 R14/R31)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
SCHEMA_PATH = ROOT / "core" / "sw-reference" / "decision-log.schema.json"
DECISION_LOG_HEADING = re.compile(r"^##\s+Decision log\s*$", re.MULTILINE | re.IGNORECASE)
JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.MULTILINE)

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main


def extract_block(body: str) -> str | None:
    if not body:
        return None
    m = DECISION_LOG_HEADING.search(body)
    if not m:
        return None
    tail = body[m.end() :]
    nxt = re.search(r"^##\s+", tail, re.MULTILINE)
    section = tail[: nxt.start()] if nxt else tail
    fm = JSON_FENCE.search(section)
    if fm:
        return fm.group(1).strip()
    stripped = re.sub(r"<!--.*?-->", "", section, flags=re.DOTALL).strip()
    return stripped or None


def _basic_validate(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("intent", "alternativesRuledOut", "highRiskAreas", "taskRefs"):
        val = record.get(key)
        if key == "intent":
            if not isinstance(val, str) or not val.strip():
                errors.append(f"missing:{key}")
            continue
        if not isinstance(val, list) or not val or not all(isinstance(x, str) and x.strip() for x in val):
            errors.append(f"missing:{key}")
    return errors


def validate_record(record: dict[str, Any]) -> dict[str, Any]:
    errors = _basic_validate(record)
    if errors:
        return {"verdict": "fail", "reason": "schema-invalid", "errors": errors}
    try:
        import jsonschema

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(record, schema)
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001 — surface validation failures
        return {"verdict": "fail", "reason": "schema-invalid", "errors": [str(exc)]}
    return {"verdict": "pass", "record": record}


def redact_text(text: str) -> tuple[str, dict[str, Any]]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "memory-redact.py")],
        input=text,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return text, {"verdict": "fail", "reason": "redaction-error", "stderr": proc.stderr.strip()}
    out = proc.stdout
    if out != text:
        return out, {"verdict": "fail", "reason": "redaction-required"}
    return out, {"verdict": "pass"}


def parse_body(body: str) -> dict[str, Any]:
    raw = extract_block(body)
    if raw is None:
        return {"verdict": "fail", "reason": "missing-decision-log"}
    try:
        record = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {"verdict": "fail", "reason": "invalid-json", "detail": str(exc)}
    if not isinstance(record, dict):
        return {"verdict": "fail", "reason": "invalid-json"}
    validated = validate_record(record)
    if validated.get("verdict") != "pass":
        return validated
    redacted_json, red_meta = redact_text(json.dumps(record, ensure_ascii=False))
    if red_meta.get("verdict") == "fail":
        return {"verdict": "fail", "reason": red_meta.get("reason", "redaction-failed"), "redaction": red_meta}
    try:
        record = json.loads(redacted_json)
    except json.JSONDecodeError:
        record = validated["record"]
    return {"verdict": "pass", "record": record, "redaction": red_meta}


def ship_require(body: str) -> dict[str, Any]:
    """Fail-closed helper for /sw-ship when decision log is missing or invalid."""
    result = parse_body(body)
    if result.get("verdict") != "pass":
        result["shipBlocked"] = True
        result["recommendedAction"] = "Add a schema-valid ## Decision log JSON block to the PR body"
    else:
        result["shipBlocked"] = False
    return result


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args or args[0] in ("-h", "--help"):
        print("usage: decision_log.py {parse|validate|ship-require} [--body-file PATH]", file=sys.stderr)
        return 2
    cmd = args[0]
    body = ""
    if "--body-file" in args:
        body = Path(args[args.index("--body-file") + 1]).read_text(encoding="utf-8")
    elif "--body" in args:
        body = args[args.index("--body") + 1]
    else:
        body = sys.stdin.read()

    if cmd == "validate":
        try:
            record = json.loads(body)
        except json.JSONDecodeError:
            print(json.dumps({"verdict": "fail", "reason": "invalid-json"}))
            return 20
        print(json.dumps(validate_record(record if isinstance(record, dict) else {})))
        return 0 if validate_record(record if isinstance(record, dict) else {}).get("verdict") == "pass" else 20

    if cmd == "parse":
        print(json.dumps(parse_body(body)))
        return 0 if parse_body(body).get("verdict") == "pass" else 20

    if cmd == "ship-require":
        print(json.dumps(ship_require(body)))
        return 0 if not ship_require(body).get("shipBlocked") else 20

    print(json.dumps({"verdict": "fail", "reason": "unknown-command"}))
    return 2


if __name__ == "__main__":
    run_module_main(main)
