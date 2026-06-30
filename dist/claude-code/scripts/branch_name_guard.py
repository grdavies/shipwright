"""Branch-name conformance guard (PRD 007 R22/R23/R25/R27)."""
from __future__ import annotations
import json, re, sys
from pathlib import Path
FALLBACK_TYPES = "feat fix perf revert docs chore refactor test"

def load_types(root: Path) -> str:
    cfg = root / "release-please-config.json"
    if not cfg.is_file():
        return FALLBACK_TYPES
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        types = []
        for pkg in data.get("packages", {}).values():
            for sec in pkg.get("changelog-sections", []):
                t = sec.get("type")
                if t and t not in types:
                    types.append(t)
        return " ".join(types) if types else FALLBACK_TYPES
    except (json.JSONDecodeError, OSError):
        return FALLBACK_TYPES

def types_alternation(root: Path) -> str:
    return load_types(root).replace(" ", "|")

def slugify(raw: str) -> str:
    text = re.sub(r"^[A-Za-z]+/", "", raw).lower()
    text = re.sub(r"[^a-z0-9._/-]+", "-", text)
    return text.strip("-/")

def derive(raw: str, branch_type: str = "feat") -> str:
    slug = slugify(raw) or "work"
    return f"{branch_type}/{slug}"

def validate(root: Path, branch: str) -> tuple[int, str]:
    alt = types_alternation(root)
    if re.match(rf"^({alt})/[a-z0-9][a-z0-9._/-]*$", branch):
        return 0, json.dumps({"verdict": "pass", "branch": branch}) + "\n"
    payload = {"verdict": "fail", "branch": branch, "allowedTypes": load_types(root),
               "remediation": f"use <type>/<slug> with a release-please type, e.g. {derive(branch)}"}
    return 3, json.dumps(payload) + "\n"

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(__file__).resolve().parent.parent
    if not args:
        print("usage: branch-name-guard {types|validate|derive}", file=sys.stderr); return 2
    cmd = args[0]
    rest = args[1:]
    if cmd == "types": print(load_types(root)); return 0
    if cmd == "validate":
        if not rest: print("usage: validate <branch>", file=sys.stderr); return 2
        code, out = validate(root, rest[0]); (sys.stdout if code==0 else sys.stderr).write(out); return code
    if cmd == "derive":
        if not rest: print("usage: derive <name> [type]", file=sys.stderr); return 2
        print(derive(rest[0], rest[1] if len(rest)>1 else "feat")); return 0
    print("usage: branch-name-guard {types|validate|derive}", file=sys.stderr); return 2
