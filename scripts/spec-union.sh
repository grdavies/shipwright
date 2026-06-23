#!/usr/bin/env bash
# Precedence-aware PRD + amendments union resolver (R12).
# Bash 3.2 compatible (no associative arrays).
#
# Usage: spec-union.sh <prd-path>
set -euo pipefail

PRD="${1:-}"
[ -z "$PRD" ] && { echo '{"error":"usage: spec-union.sh <prd-path>"}' >&2; exit 2; }
[ -f "$PRD" ] || { echo "{\"error\":\"not found: $PRD\"}" >&2; exit 2; }

exec python3 - "$PRD" <<'PY'
import json, re, sys
from pathlib import Path

prd = Path(sys.argv[1])
amend_dir = prd.parent / "amendments"


def norm_rid(rid: str) -> str:
    return rid if rid.startswith("R") else f"R{rid}"


def parse_frontmatter_list(text, key):
    in_fm = False
    for line in text.splitlines():
        if line.strip() == "---":
            in_fm = not in_fm
            continue
        if in_fm and line.startswith(f"{key}:"):
            val = line.split(":", 1)[1].strip()
            val = val.strip("[]")
            return [norm_rid(x.strip()) for x in re.split(r",\s*", val) if x.strip()]
    return []


def extract_requirements(text):
    reqs = []
    seen = set()
    for line in text.splitlines():
        m = re.match(r"^- \*\*(R\d+)\*\*\s*(.*)$", line)
        if m:
            rid, body = m.group(1), m.group(2).strip()
            if rid not in seen:
                reqs.append((rid, body))
                seen.add(rid)
            continue
        m = re.match(r"^\*\*(R\d+)\*\*\s*(.*)$", line)
        if m and not line.startswith("- "):
            rid, body = m.group(1), m.group(2).strip()
            if rid not in seen:
                reqs.append((rid, body))
                seen.add(rid)
            continue
        m = re.match(r"^##\s+(R\d+)\b(?:\s*\((.*)\))?\s*$", line)
        if m:
            rid = m.group(1)
            body = (m.group(2) or "").strip()
            if rid not in seen:
                reqs.append((rid, body))
                seen.add(rid)
    return reqs


def amendment_sort_key(path: Path) -> int:
    m = re.search(r"A(\d+)", path.name)
    return int(m.group(1)) if m else 0


reqs = {}
retracted = []
superseded = {}

parent_text = prd.read_text()
for rid, text in extract_requirements(parent_text):
    reqs[rid] = {"text": text, "source": "parent"}

if amend_dir.is_dir():
    for amend in sorted(amend_dir.glob("A*.md"), key=amendment_sort_key):
        atext = amend.read_text()
        supersede_targets = parse_frontmatter_list(atext, "supersedes")

        for rid in parse_frontmatter_list(atext, "retracts"):
            retracted.append(rid)
            reqs.pop(rid, None)

        amend_reqs = extract_requirements(atext)
        target_set = set(supersede_targets)
        replacements = [r for r in amend_reqs if r[0] not in target_set]

        used_replacement_ids = set()
        for i, old in enumerate(supersede_targets):
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

out = {
    "requirements": [
        {"id": k, "text": v["text"], "source": v["source"]}
        for k, v in sorted(reqs.items(), key=lambda x: int(x[0][1:]))
    ],
    "retracted": retracted,
    "superseded": superseded,
}
print(json.dumps(out, ensure_ascii=False))
PY
