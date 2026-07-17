#!/usr/bin/env python3
"""Thin AGENTS.md contract checks (PRD 072 R7)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RULE_STORE_REL = Path(".cursor/sw-memory/rules")
ALLOWLIST_REL = Path(".cursor/sw-memory-rule-allowlist.json")
DEFAULT_AGENTS_REL = Path("AGENTS.md")

_POLICY_BULLET = re.compile(
    r"^\s*[-*]\s+(?:Prefer|Avoid|Never|Always|Keep|When|Do not|Don't)\b",
    re.I,
)
_POLICY_CODE_FENCE = re.compile(r"^```(?:bash|sh|python|py)\b", re.I)
_RULE_TABLE_ROW = re.compile(r"^\|\s*[^|]+\|\s*`([a-z][a-z0-9-]*)`\s*\|", re.MULTILINE)


def load_allowlist(root: Path) -> tuple[str, set[str] | None]:
    path = root / ALLOWLIST_REL
    if not path.is_file():
        return "absent", None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "corrupt", None
    if not isinstance(data, list):
        return "corrupt", None
    return "ok", {str(item) for item in data}


def substantive_policy_lines(text: str) -> list[str]:
    offenders: list[str] = []
    in_code = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            if _POLICY_CODE_FENCE.match(stripped):
                offenders.append(line)
            in_code = not in_code
            continue
        if in_code:
            continue
        if _POLICY_BULLET.match(line):
            offenders.append(line)
    return offenders


def referenced_rule_ids(text: str) -> set[str]:
    return {match.group(1) for match in _RULE_TABLE_ROW.finditer(text)}


def rule_path(root: Path, rule_id: str) -> Path:
    return root / RULE_STORE_REL / f"{rule_id}.md"


def audit_agents_md(root: Path, agents_rel: Path = DEFAULT_AGENTS_REL) -> dict[str, object]:
    agents_path = root / agents_rel
    if not agents_path.is_file():
        return {
            "ok": False,
            "agentsPath": str(agents_rel),
            "errors": ["agents file missing"],
        }

    text = agents_path.read_text(encoding="utf-8")
    offenders = substantive_policy_lines(text)
    rule_ids = sorted(referenced_rule_ids(text))
    allowlist_status, allowlist = load_allowlist(root)

    missing_rules: list[str] = []
    unlisted_rules: list[str] = []
    for rule_id in rule_ids:
        if not rule_path(root, rule_id).is_file():
            missing_rules.append(rule_id)
        elif allowlist_status == "ok" and allowlist is not None and rule_id not in allowlist:
            unlisted_rules.append(rule_id)

    errors: list[str] = []
    if offenders:
        errors.append("substantive standing policy body in AGENTS.md")
    if missing_rules:
        errors.append(f"missing rule files: {', '.join(missing_rules)}")
    if unlisted_rules:
        errors.append(f"rules not allowlisted: {', '.join(unlisted_rules)}")
    if not rule_ids:
        errors.append("no rule pointers declared")

    return {
        "ok": not errors,
        "agentsPath": str(agents_rel),
        "ruleIds": rule_ids,
        "substantiveLines": offenders,
        "allowlistStatus": allowlist_status,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit thin AGENTS.md standing-guidance contract")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--agents", type=Path, default=DEFAULT_AGENTS_REL)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = audit_agents_md(args.root.resolve(), args.agents)
    if args.json:
        print(json.dumps(result, indent=2))
    elif not result["ok"]:
        for err in result.get("errors", []):
            print(err, file=sys.stderr)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
