#!/usr/bin/env bash
# Precedence-aware frozen doc + amendments union resolver (R12).
# Supports PRD (R-IDs, parent/amendments/) and decision records (D-IDs, sibling .amendments/).
#
# Usage: spec-union.sh <doc-path>
set -euo pipefail

DOC="${1:-}"
[ -z "$DOC" ] && { echo '{"error":"usage: spec-union.sh <doc-path>"}' >&2; exit 2; }
[ -f "$DOC" ] || { echo "{\"error\":\"not found: $DOC\"}" >&2; exit 2; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

exec python3 - "$DOC" "$ROOT" <<'PY'
import json, re, sys
from pathlib import Path

doc = Path(sys.argv[1])
root = Path(sys.argv[2])
MAX_CHAIN_DEPTH = 20

ID_PATTERN = re.compile(r"^([RD])(\d+)$", re.I)


def norm_id(rid: str) -> str:
    rid = rid.strip()
    m = ID_PATTERN.match(rid)
    if m:
        return f"{m.group(1).upper()}{m.group(2)}"
    if rid.isdigit():
        return f"R{rid}"
    return rid


def id_sort_key(rid: str):
    m = ID_PATTERN.match(rid)
    if m:
        return (m.group(1).upper(), int(m.group(2)))
    return ("Z", rid)


def resolve_amend_dir(path: Path) -> Path:
    sibling = path.parent / f"{path.stem}.amendments"
    if sibling.is_dir():
        return sibling
    return path.parent / "amendments"


def parse_frontmatter_list(text, key):
    in_fm = False
    for line in text.splitlines():
        if line.strip() == "---":
            if not in_fm:
                in_fm = True
                continue
            break
        if in_fm and line.startswith(f"{key}:"):
            val = line.split(":", 1)[1].strip()
            val = val.strip("[]")
            return [norm_id(x.strip()) for x in re.split(r",\s*", val) if x.strip()]
    return []


def parse_frontmatter_scalar(text, key):
    in_fm = False
    for line in text.splitlines():
        if line.strip() == "---":
            if not in_fm:
                in_fm = True
                continue
            break
        if in_fm and line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip().strip('"').strip("'")
    return None


def extract_requirements(text):
    reqs = []
    seen = set()
    patterns = [
        re.compile(r"^- \*\*([RD]\d+)\*\*\s*(.*)$", re.I),
        re.compile(r"^\*\*([RD]\d+)\*\*\s*(.*)$", re.I),
        re.compile(r"^##\s+([RD]\d+)\b(?:\s*\((.*)\))?\s*$", re.I),
    ]
    for line in text.splitlines():
        for i, pat in enumerate(patterns):
            m = pat.match(line)
            if not m:
                continue
            if i == 1 and line.startswith("- "):
                continue
            rid = norm_id(m.group(1))
            body = (m.group(2) if m.lastindex >= 2 else "") or ""
            body = body.strip()
            if rid not in seen:
                reqs.append((rid, body))
                seen.add(rid)
            break
    return reqs


def amendment_sort_key(path: Path) -> int:
    m = re.search(r"A(\d+)", path.name)
    return int(m.group(1)) if m else 0


def resolve_terminal_replacement(replacement: str, visited_paths: set, depth: int = 0) -> str:
    if depth > MAX_CHAIN_DEPTH:
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
        atext = amend.read_text()
        rep_scalar = parse_frontmatter_scalar(atext, "replacement")
        for old in parse_frontmatter_list(atext, "supersedes"):
            if old.startswith("D") and rep_scalar:
                return resolve_terminal_replacement(rep_scalar, visited_paths, depth + 1)
    return replacement


reqs = {}
retracted = []
superseded = {}
record_superseded = {}

parent_text = doc.read_text()
parent_reqs = extract_requirements(parent_text)

if re.search(r"\*\*D\d+\*\*", parent_text, re.I) and not parent_reqs:
    print(json.dumps({"error": "D-ID extraction failed on non-empty decision doc"}))
    sys.exit(2)

for rid, text in parent_reqs:
    reqs[rid] = {"text": text, "source": "parent"}

amend_dir = resolve_amend_dir(doc)

if amend_dir.is_dir():
    for amend in sorted(amend_dir.glob("A*.md"), key=amendment_sort_key):
        atext = amend.read_text()
        supersede_targets = parse_frontmatter_list(atext, "supersedes")
        replacement_path = parse_frontmatter_scalar(atext, "replacement")

        for rid in parse_frontmatter_list(atext, "retracts"):
            retracted.append(rid)
            reqs.pop(rid, None)

        amend_reqs = extract_requirements(atext)
        amend_ids = {r[0] for r in amend_reqs}

        record_level = []
        prd_level = []
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
                except ValueError as e:
                    print(json.dumps({"error": str(e)}))
                    sys.exit(2)
                record_superseded[old] = {"replacement": terminal}
            else:
                record_superseded[old] = {"replacement": replacement_path or ""}

        target_set = set(prd_level)
        replacements = [r for r in amend_reqs if r[0] not in target_set]

        used_replacement_ids = set()
        for i, old in enumerate(prd_level):
            if i >= len(replacements):
                break
            new_id, new_text = replacements[i]
            superseded[old] = new_id
            reqs.pop(old, None)
            reqs[new_id] = {"text": new_text, "source": amend.name}
            used_replacement_ids.add(new_id)

        for rid, text in amend_reqs:
            if rid not in reqs:
                reqs[rid] = {"text": text, "source": amend.name}

if parent_reqs and all(r[0].startswith("D") for r in parent_reqs) and not reqs:
    covered = set(retracted) | set(record_superseded.keys())
    if not all(r[0] in covered for r in parent_reqs):
        print(json.dumps({"error": "empty union on non-empty decision doc"}))
        sys.exit(2)

out = {
    "requirements": [
        {"id": k, "text": v["text"], "source": v["source"]}
        for k, v in sorted(reqs.items(), key=lambda x: id_sort_key(x[0]))
    ],
    "retracted": retracted,
    "superseded": superseded,
}
if record_superseded:
    out["superseded"] = {**superseded, **record_superseded}

print(json.dumps(out, ensure_ascii=False))
PY
