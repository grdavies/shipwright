#!/usr/bin/env python3
"""PR/merge template render + required-field validation (PRD 026 R26)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
TEMPLATE_DIR = ROOT / "core" / "sw-reference" / "templates"

REQUIRED_MARKER = re.compile(r"<!--\s*required:(\w+)\s*-->")


def template_path(name: str) -> Path:
    mapping = {
        "pr-body": "pr-body.md",
        "merge-commit": "merge-commit.md",
    }
    fname = mapping.get(name, f"{name}.md")
    path = TEMPLATE_DIR / fname
    if not path.is_file():
        raise FileNotFoundError(f"template not found: {name}")
    return path


def required_fields(template_text: str) -> list[str]:
    return REQUIRED_MARKER.findall(template_text)


def render_template(name: str, context: dict[str, str]) -> str:
    text = template_path(name).read_text(encoding="utf-8")
    for key, val in context.items():
        text = text.replace("{{" + key + "}}", val)
    return text


def validate_body(name: str, body: str) -> dict:
    tpl = template_path(name).read_text(encoding="utf-8")
    missing: list[str] = []
    for field in required_fields(tpl):
        marker = f"<!-- required:{field} -->"
        if marker not in body:
            missing.append(field)
            continue
        section = body.split(marker, 1)[1]
        content = section.split("##", 1)[0].strip()
        content = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL).strip()
        if not content or content.startswith("{{"):
            missing.append(field)
    verdict = "pass" if not missing else "fail"
    return {"verdict": verdict, "template": name, "missing": missing}


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: git_template_lib.py {render|validate|required} <name> ...", file=sys.stderr)
        sys.exit(2)
    cmd = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else ""
    if cmd == "required":
        print(json.dumps(required_fields(template_path(name).read_text(encoding="utf-8"))))
        sys.exit(0)
    if cmd == "render":
        ctx_json = "{}"
        if "--context-json" in sys.argv:
            ctx_json = sys.argv[sys.argv.index("--context-json") + 1]
        ctx = json.loads(ctx_json)
        print(render_template(name, {k: str(v) for k, v in ctx.items()}))
        sys.exit(0)
    if cmd == "validate":
        if "--body" in sys.argv:
            body = sys.argv[sys.argv.index("--body") + 1]
        elif "--body-file" in sys.argv:
            body = Path(sys.argv[sys.argv.index("--body-file") + 1]).read_text(encoding="utf-8")
        else:
            body = sys.stdin.read()
        result = validate_body(name, body)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["verdict"] == "pass" else 3)
    print(f"unknown command: {cmd}", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
