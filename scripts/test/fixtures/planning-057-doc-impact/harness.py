#!/usr/bin/env python3
"""Documentation-impact co-landing fixture (PRD 057 R32).

Parses the PRD 057 "Documentation Impact" table into a
requirement → (doc paths, waves) map and enforces the co-landing invariant:
a behavior change for a requirement MUST land alongside its paired doc-surface
update in the same change set / wave.

Checks:
1. The Documentation Impact table parses into a non-empty requirement map, and
   each mapped requirement carries at least one doc path and a wave.
2. Spot-checked known pairings resolve (R7 → CAPABILITIES.md / gitlab-issues.md,
   R18 → models-tiering.md, R1 → feedback / living-status / configuration).
3. ``co_landing_violations`` is self-tested: a change set that touches a
   requirement's behavior without its doc path is a violation; touching the doc
   clears it.
4. Phase-1 co-landing proof: the cross-cutting scaffolding this phase adds
   (spec-union / traceability-check no-restatement gate + the three new
   fixtures) is present, so R22/R23/R24/R32 behavior and its paired artifacts
   co-land.

Runs fully offline and deterministically.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]

DEFAULT_PRD = "docs/prds/057-planning-store-hardening/057-prd-planning-store-hardening.md"

_RID = re.compile(r"\bR(\d+)\b")
_WAVE_NUM = re.compile(r"\b([1-5])\b")
_PATH = re.compile(r"`([^`]+)`")
_PATH_LIKE = re.compile(r"[\w./-]+\.(?:md|mdc|json|py)\b")

SPOT_CHECKS = {
    "R7": ["CAPABILITIES.md", "gitlab-issues.md"],
    "R18": ["models-tiering.md"],
    "R1": ["feedback", "living-status"],
}

PHASE1_ARTIFACTS = [
    "scripts/spec-union.py",
    "scripts/traceability-check.py",
    "scripts/spec_union_056.py",
    "scripts/test/fixtures/planning-file-store-parity/harness.py",
    "scripts/test/fixtures/planning-deliver-parity/wave_incremental.py",
    "scripts/test/fixtures/planning-057-doc-impact/harness.py",
]


def extract_doc_impact_section(text: str) -> str:
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("## documentation impact"):
            start = i + 1
            break
    if start is None:
        return ""
    body: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        body.append(line)
    return "\n".join(body)


def parse_doc_impact(text: str) -> dict[str, dict[str, list]]:
    """requirement id → {"docPaths": [...], "waves": [...]}"""
    section = extract_doc_impact_section(text)
    mapping: dict[str, dict[str, set]] = {}
    for line in section.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        artifact, _update, requirement, wave = cells[0], cells[1], cells[-2], cells[-1]
        if artifact in ("Artifact", "---", ":---") or set(artifact) <= {"-", ":", " "}:
            continue
        rids = [f"R{m.group(1)}" for m in _RID.finditer(requirement)]
        if not rids:
            continue
        paths = set(_PATH.findall(artifact))
        paths |= set(_PATH_LIKE.findall(artifact))
        # keep only path-like tokens (drop line-ref backtick fragments)
        paths = {p for p in paths if "/" in p or p.endswith((".md", ".mdc", ".json", ".py"))}
        waves = {int(m.group(1)) for m in _WAVE_NUM.finditer(wave)}
        for rid in rids:
            entry = mapping.setdefault(rid, {"docPaths": set(), "waves": set()})
            entry["docPaths"] |= paths
            entry["waves"] |= waves
    return {rid: {"docPaths": sorted(v["docPaths"]), "waves": sorted(v["waves"])} for rid, v in mapping.items()}


def co_landing_violations(changed_paths: set[str], active_requirements: list[str],
                          doc_map: dict[str, dict[str, list]]) -> list[dict]:
    """A requirement whose behavior changed but whose doc paths did not = violation."""
    violations: list[dict] = []
    for rid in active_requirements:
        entry = doc_map.get(rid)
        if not entry or not entry["docPaths"]:
            continue
        touched_doc = any(
            any(changed.endswith(doc) or doc in changed for changed in changed_paths)
            for doc in entry["docPaths"]
        )
        if not touched_doc:
            violations.append({"rid": rid, "expectedDocs": entry["docPaths"]})
    return violations


def check_map_wellformed(doc_map: dict) -> dict:
    empty = [rid for rid, v in doc_map.items() if not v["docPaths"] or not v["waves"]]
    return {
        "name": "doc-impact-map-wellformed",
        "ok": bool(doc_map) and not empty,
        "detail": f"requirements mapped={len(doc_map)} without paths/waves={empty}",
    }


def check_spot_pairings(doc_map: dict) -> dict:
    misses: dict[str, list] = {}
    for rid, needles in SPOT_CHECKS.items():
        joined = " ".join(doc_map.get(rid, {}).get("docPaths", []))
        missing = [n for n in needles if n not in joined]
        if missing:
            misses[rid] = missing
    return {"name": "spot-check-pairings", "ok": not misses, "detail": misses}


def check_co_landing_selftest(doc_map: dict) -> dict:
    # Use R18 → models-tiering.md as the probe pairing.
    behavior = {"scripts/resolve-model-tier.py"}
    missing_doc = co_landing_violations(behavior, ["R18"], doc_map)
    with_doc = co_landing_violations(
        behavior | {"core/sw-reference/models-tiering.md"}, ["R18"], doc_map
    )
    ok = len(missing_doc) == 1 and len(with_doc) == 0
    return {
        "name": "co-landing-selftest",
        "ok": ok,
        "detail": f"missing-doc violations={len(missing_doc)} with-doc violations={len(with_doc)}",
    }


def check_phase1_colanding() -> dict:
    missing = [p for p in PHASE1_ARTIFACTS if not (ROOT / p).is_file()]
    gated = []
    for script in ("scripts/spec-union.py", "scripts/traceability-check.py"):
        path = ROOT / script
        if not path.is_file() or "--no-restate-056" not in path.read_text(encoding="utf-8"):
            gated.append(script)
    return {
        "name": "phase1-scaffolding-colanded",
        "ok": not missing and not gated,
        "detail": f"missing artifacts={missing} missing-056-gate={gated}",
    }


def main() -> int:
    prd_path = ROOT / DEFAULT_PRD
    if not prd_path.is_file():
        print(json.dumps({"fixture": "planning-057-doc-impact", "rid": "R32",
                          "verdict": "fail", "error": f"prd-not-found:{prd_path}"}))
        return 20
    doc_map = parse_doc_impact(prd_path.read_text(encoding="utf-8"))
    checks = [
        check_map_wellformed(doc_map),
        check_spot_pairings(doc_map),
        check_co_landing_selftest(doc_map),
        check_phase1_colanding(),
    ]
    failures = [c for c in checks if not c["ok"]]
    verdict = "pass" if not failures else "fail"
    report = {
        "fixture": "planning-057-doc-impact",
        "rid": "R32",
        "verdict": verdict,
        "requirementDocMap": doc_map,
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if verdict == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
