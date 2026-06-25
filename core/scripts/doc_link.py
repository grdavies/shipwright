#!/usr/bin/env python3
"""Brainstorm↔PRD frontmatter traceability (PRD 009 A1 — R52–R55)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

EXIT_PASS = 0
EXIT_FAIL = 20
EXIT_ERROR = 2

BRAINSTORM_KEYS = ("brainstorm", "source_brainstorm")
PRD_KEYS = ("prd",)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def split_frontmatter(content: str) -> tuple[dict[str, str], str]:
    if not content.startswith("---"):
        return {}, content
    end = content.find("\n---", 3)
    if end == -1:
        return {}, content
    block = content[3:end].strip()
    fm: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        fm[key.strip()] = val.strip()
    return fm, content[end + 4 :].lstrip("\n")


def join_frontmatter(fm: dict[str, str], body: str) -> str:
    lines = ["---"]
    for key in sorted(fm.keys()):
        lines.append(f"{key}: {fm[key]}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines) + body.lstrip("\n")


def parse_link_paths(raw: str | None) -> list[str]:
    if not raw:
        return []
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [p.strip().strip("'\"") for p in inner.split(",") if p.strip()]
    return [raw]


def is_truthy_frozen(fm: dict[str, str]) -> bool:
    return str(fm.get("frozen", "")).lower() in ("true", "yes", "1")


def resolve_repo_path(root: Path, rel: str) -> Path | None:
    rel = rel.strip().strip("'\"")
    if not rel or rel.startswith("http"):
        return None
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def brainstorm_backref(fm: dict[str, str]) -> str | None:
    for key in BRAINSTORM_KEYS:
        if fm.get(key):
            return fm[key]
    return None


def prd_forward_refs(fm: dict[str, str]) -> list[str]:
    out: list[str] = []
    for key in PRD_KEYS:
        out.extend(parse_link_paths(fm.get(key)))
    return out


def infer_tier(path: Path, tier: str | None) -> str:
    if tier in ("full", "standard"):
        return tier
    return "full"


def check_prd(root: Path, path: Path, tier: str) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    fm, _ = split_frontmatter(text)
    findings: list[dict[str, str]] = []

    back = brainstorm_backref(fm)
    if tier == "full":
        if not back:
            findings.append(
                {
                    "code": "missing-brainstorm-backref",
                    "message": "Full-tier PRD requires brainstorm: (or legacy source_brainstorm:) in frontmatter",
                }
            )
        else:
            for rel in parse_link_paths(back):
                if resolve_repo_path(root, rel) is None:
                    findings.append(
                        {
                            "code": "dangling-brainstorm-backref",
                            "message": f"brainstorm back-reference does not resolve: {rel}",
                        }
                    )

    for rel in prd_forward_refs(fm):
        if resolve_repo_path(root, rel) is None:
            findings.append(
                {
                    "code": "dangling-prd-forwardref",
                    "message": f"prd forward reference does not resolve: {rel}",
                }
            )

    verdict = "pass" if not findings else "fail"
    return {"verdict": verdict, "artifact": "prd", "path": str(path), "tier": tier, "findings": findings}


def check_brainstorm(root: Path, path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    fm, _ = split_frontmatter(text)
    findings: list[dict[str, str]] = []

    for rel in prd_forward_refs(fm):
        if resolve_repo_path(root, rel) is None:
            findings.append(
                {
                    "code": "dangling-prd-forwardref",
                    "message": f"prd forward reference does not resolve: {rel}",
                }
            )

    back = brainstorm_backref(fm)
    if back and resolve_repo_path(root, back) is None:
        findings.append(
            {
                "code": "dangling-brainstorm-selfref",
                "message": f"brainstorm self-reference does not resolve: {back}",
            }
        )

    verdict = "pass" if not findings else "fail"
    return {"verdict": verdict, "artifact": "brainstorm", "path": str(path), "findings": findings}


def check_artifact(root: Path, path: Path, tier: str | None = None) -> dict[str, Any]:
    rel = str(path)
    if "docs/brainstorms/" in rel.replace("\\", "/"):
        return check_brainstorm(root, path)
    if "/prd-" in path.name or rel.endswith("-prd.md"):
        return check_prd(root, path, infer_tier(path, tier))
    if "docs/prds/" in rel.replace("\\", "/") and "prd" in path.name:
        return check_prd(root, path, infer_tier(path, tier))
    return {"verdict": "pass", "path": rel, "note": "not a PRD/brainstorm — skipped"}


def rel_from_root(root: Path, path: Path) -> str:
    path = path.resolve()
    root = root.resolve()
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def write_backref(root: Path, brainstorm: Path, prd: Path) -> dict[str, Any]:
    prd = prd.resolve()
    brainstorm = brainstorm.resolve()
    bs_rel = rel_from_root(root, brainstorm)
    text = prd.read_text(encoding="utf-8")
    fm, body = split_frontmatter(text)
    fm["brainstorm"] = bs_rel
    fm.pop("source_brainstorm", None)
    prd.write_text(join_frontmatter(fm, body), encoding="utf-8")
    return {"verdict": "pass", "action": "write-backref", "prd": rel_from_root(root, prd), "brainstorm": bs_rel}


def write_forwardref(root: Path, brainstorm: Path, prd: Path) -> dict[str, Any]:
    prd = prd.resolve()
    brainstorm = brainstorm.resolve()
    prd_rel = rel_from_root(root, prd)
    text = brainstorm.read_text(encoding="utf-8")
    fm, body = split_frontmatter(text)
    if is_truthy_frozen(fm):
        return {
            "verdict": "pass",
            "action": "write-forwardref",
            "skipped": True,
            "reason": "brainstorm frozen — PRD back-reference is authoritative",
        }
    existing = prd_forward_refs(fm)
    if prd_rel not in existing:
        existing.append(prd_rel)
    if len(existing) == 1:
        fm["prd"] = existing[0]
    else:
        fm["prd"] = "[" + ", ".join(existing) + "]"
    brainstorm.write_text(join_frontmatter(fm, body), encoding="utf-8")
    return {
        "verdict": "pass",
        "action": "write-forwardref",
        "brainstorm": rel_from_root(root, brainstorm),
        "prd": prd_rel,
    }


def emit(obj: dict[str, Any], code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def main() -> None:
    args = sys.argv[1:]
    if not args:
        emit({"verdict": "fail", "error": "usage: doc_link.py check|write-backref|write-forwardref ..."}, EXIT_ERROR)

    cmd = args[0]
    root = repo_root()

    def kv(flag: str) -> str | None:
        if flag in args:
            i = args.index(flag)
            return args[i + 1] if i + 1 < len(args) else None
        return None

    if cmd == "check":
        path_s = kv("--path")
        if not path_s:
            emit({"verdict": "fail", "error": "--path required"}, EXIT_ERROR)
        root_override = kv("--root")
        if root_override:
            root = Path(root_override).resolve()
        path = (root / path_s).resolve() if not Path(path_s).is_absolute() else Path(path_s)
        if not path.is_file():
            emit({"verdict": "fail", "error": f"not found: {path}"}, EXIT_ERROR)
        tier = kv("--tier")
        result = check_artifact(root, path, tier)
        code = EXIT_PASS if result.get("verdict") == "pass" else EXIT_FAIL
        emit(result, code)

    if cmd == "write-backref":
        bs = kv("--brainstorm")
        prd = kv("--prd")
        if not bs or not prd:
            emit({"verdict": "fail", "error": "--brainstorm and --prd required"}, EXIT_ERROR)
        root_override = kv("--root")
        if root_override:
            root = Path(root_override).resolve()
        emit(write_backref(root, Path(bs), Path(prd)))

    if cmd == "write-forwardref":
        bs = kv("--brainstorm")
        prd = kv("--prd")
        if not bs or not prd:
            emit({"verdict": "fail", "error": "--brainstorm and --prd required"}, EXIT_ERROR)
        root_override = kv("--root")
        if root_override:
            root = Path(root_override).resolve()
        emit(write_forwardref(root, Path(bs), Path(prd)))

    emit({"verdict": "fail", "error": f"unknown command: {cmd}"}, EXIT_ERROR)


if __name__ == "__main__":
    main()
