#!/usr/bin/env python3
"""Precedence-aware frozen doc + amendments union resolver (R12)."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import spec_union_056
from _sw.cli import run_module_main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spec-union.py")
    parser.add_argument("doc")
    parser.add_argument(
        "--no-restate-056",
        action="store_true",
        help="Gate: fail when a union R-ID restates PRD 056 union R1-R20 text (R22).",
    )
    parser.add_argument(
        "--union-056-source",
        default=None,
        help="Local PRD 056 union doc override for the no-restatement gate (fixtures/offline).",
    )
    parser.add_argument(
        "--restate-ratio",
        type=float,
        default=spec_union_056.RESTATEMENT_RATIO,
        help="Similarity threshold (0-1) for the no-restatement gate.",
    )
    args = parser.parse_args(argv)
    root = SCRIPT_DIR.parent
    doc = Path(args.doc)
    if not doc.is_file():
        print(json.dumps({"error": f"not found: {doc}"}))
        return 2
    norm = root / "scripts" / "doc-format-normalize.py"
    if norm.is_file():
        proc = subprocess.run(
            [sys.executable, str(norm), "--check", str(doc)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            print(proc.stdout or proc.stderr)
            return 20
    sys.path.insert(0, str(root / "scripts"))
    import doc_format

    max_chain_depth = 20

    def id_sort_key(rid: str):
        return doc_format.id_sort_key(rid)

    def resolve_amend_dir(path: Path) -> Path:
        sibling = path.parent / f"{path.stem}.amendments"
        if sibling.is_dir():
            return sibling
        return path.parent / "amendments"

    def amendment_sort_key(path: Path) -> int:
        m = re.search(r"A(\d+)", path.name)
        return int(m.group(1)) if m else 0

    def resolve_terminal_replacement(replacement: str, visited_paths: set, depth: int = 0) -> str:
        if depth > max_chain_depth:
            raise ValueError("supersede chain exceeds max depth")
        rep_path = Path(replacement)
        if not rep_path.is_absolute():
            rep_path = root / rep_path
        if not rep_path.is_file() and "/" in replacement and not replacement.startswith("docs/"):
            legacy = root / "docs" / replacement
            if legacy.is_file():
                rep_path = legacy
        if not rep_path.is_file():
            return replacement
        key = str(rep_path.resolve())
        if key in visited_paths:
            raise ValueError(f"supersede chain cycle at {replacement}")
        visited_paths.add(key)
        amend_dir = resolve_amend_dir(rep_path)
        if not amend_dir.is_dir():
            return replacement
        for amend in sorted(amend_dir.glob("A*.md"), key=amendment_sort_key):
            atext = amend.read_text(encoding="utf-8")
            rep_scalar = doc_format.parse_frontmatter_scalar(atext, "replacement")
            directives = doc_format.parse_frontmatter_directives(atext)
            for old in directives.get("supersedes", []):
                if old.startswith("D") and rep_scalar:
                    return resolve_terminal_replacement(rep_scalar, visited_paths, depth + 1)
        return replacement

    reqs: dict[str, dict[str, str]] = {}
    retracted: list[str] = []
    superseded: dict[str, str] = {}
    record_superseded: dict[str, dict[str, str]] = {}

    parent_text = doc.read_text(encoding="utf-8")
    parent_reqs = doc_format.extract_rd_bullets(parent_text)

    if re.search(r"\*\*D\d+\*\*", parent_text, re.I) and not parent_reqs:
        print(json.dumps({"error": "D-ID extraction failed on non-empty decision doc"}))
        return 2

    for rid, text in parent_reqs:
        reqs[rid] = {"text": text, "source": "parent"}

    amend_dir = resolve_amend_dir(doc)
    if amend_dir.is_dir():
        for amend in sorted(amend_dir.glob("A*.md"), key=amendment_sort_key):
            atext = amend.read_text(encoding="utf-8")
            directives = doc_format.parse_frontmatter_directives(atext)
            supersede_targets = directives.get("supersedes", [])
            replacement_path = doc_format.parse_frontmatter_scalar(atext, "replacement")

            for rid in directives.get("retracts", []):
                retracted.append(rid)
                reqs.pop(rid, None)

            amend_reqs = doc_format.extract_rd_bullets(atext)
            amend_ids = {r[0] for r in amend_reqs}
            record_level: list[str] = []
            prd_level: list[str] = []
            for old in supersede_targets:
                if old.startswith("D") and old not in amend_ids:
                    record_level.append(old)
                else:
                    prd_level.append(old)

            for old in record_level:
                reqs.pop(old, None)
                if replacement_path:
                    try:
                        terminal = resolve_terminal_replacement(replacement_path, set())
                    except ValueError as exc:
                        print(json.dumps({"error": str(exc)}))
                        return 2
                    record_superseded[old] = {"replacement": terminal}
                else:
                    record_superseded[old] = {"replacement": replacement_path or ""}

            target_set = set(prd_level)
            replacements = [r for r in amend_reqs if r[0] not in target_set]
            for i, old in enumerate(prd_level):
                if i >= len(replacements):
                    break
                new_id, new_text = replacements[i]
                superseded[old] = new_id
                reqs.pop(old, None)
                reqs[new_id] = {"text": new_text, "source": amend.name}

            for rid, text in amend_reqs:
                if rid not in reqs:
                    reqs[rid] = {"text": text, "source": amend.name}

    if parent_reqs and all(r[0].startswith("D") for r in parent_reqs) and not reqs:
        covered = set(retracted) | set(record_superseded.keys())
        if not all(r[0] in covered for r in parent_reqs):
            print(json.dumps({"error": "empty union on non-empty decision doc"}))
            return 2

    out: dict = {
        "requirements": [
            {"id": k, "text": v["text"], "source": v["source"]}
            for k, v in sorted(reqs.items(), key=lambda x: id_sort_key(x[0]))
        ],
        "retracted": retracted,
        "superseded": superseded,
    }
    if record_superseded:
        out["superseded"] = {**superseded, **record_superseded}

    rc = 0
    if args.no_restate_056:
        gate = spec_union_056.evaluate(
            out["requirements"],
            root,
            source=args.union_056_source,
            ratio=args.restate_ratio,
        )
        out["restatement056"] = gate
        if gate["verdict"] == "restated":
            rc = 20

    print(json.dumps(out, ensure_ascii=False))
    return rc


if __name__ == "__main__":
    run_module_main(main)
