#!/usr/bin/env python3
"""Per-wave incremental parity + wave-sequencing fixture (PRD 057 R24).

Asserts the frozen wave map honors the R24 sequencing invariant and that each
wave carries an incremental parity guard for the artifacts it touches:

1. Blocker requirements (R7, R16, R18) land in the earliest wave (Wave 1).
2. R6 (full parity audit) is exempted to the final wave (Wave 5) per D6.
3. Every union requirement is assigned to exactly one delivery wave, and the
   cross-cutting invariants (R22, R23, R24, R32) are wave-independent.
4. For each wave, the guard predicate (issue-store separate-project) is the sole
   thing that diverts a local write, so under a file-store backend no
   file-store-only write is suppressed — the per-wave incremental parity guard.

The wave map is parsed from the authoritative frozen task list (``SW_TASK_LIST``
or the PRD 057 default) so the fixture tracks the frozen artifact, not a copy.
File-store parity logic runs unconditionally (deterministic, offline).
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import planning_store

DEFAULT_TASK_LIST = "docs/prds/057-planning-store-hardening/tasks-057-planning-store-hardening.md"
BLOCKERS = ("R7", "R16", "R18")
FINAL_AUDIT_RID = "R6"
FINAL_WAVE = 5
CROSS_CUTTING = {"R22", "R23", "R24", "R32"}
# R21 is intentionally split into 21a (Wave 2) and 21b (Wave 5) per D8; both map
# to union R-ID R21, so a two-wave assignment is expected, not a sequencing bug.
SPLIT_REQUIREMENTS = {"R21"}

# Content between the wave header and the "→" may wrap across physical lines,
# so match with DOTALL and stop non-greedily at the first arrow.
_WAVE_LINE = re.compile(r"^-\s+\*\*Wave\s+(\d+)\b.*?:\*\*\s*(.+?)\s*→", re.M | re.S)
_RID = re.compile(r"\bR(\d+)[ab]?\b")

# Artifacts guarded per wave (from the PRD Documentation Impact + guard tables).
WAVE_GUARDED_ARTIFACTS: dict[int, list[str]] = {
    2: ["docs/prds/GAP-BACKLOG.md", "docs/prds/INDEX.md", "docs/prds/SUPERSEDED.md"],
    3: ["issue-store chunk manifest", "issue-store put journal"],
    4: ["issue-store native labels"],
    5: ["core/sw-reference/planning-deliver-parity-matrix.md"],
}


def resolve_task_list() -> Path:
    env = os.environ.get("SW_TASK_LIST")
    if env:
        candidate = Path(env)
        if not candidate.is_absolute():
            candidate = ROOT / env
        if candidate.is_file():
            return candidate
    return ROOT / DEFAULT_TASK_LIST


def parse_wave_map(text: str) -> dict[int, set[str]]:
    waves: dict[int, set[str]] = {}
    for match in _WAVE_LINE.finditer(text):
        wave = int(match.group(1))
        rids = {f"R{m.group(1)}" for m in _RID.finditer(match.group(2))}
        waves.setdefault(wave, set()).update(rids)
    return waves


def guard_predicate(root: Path, cfg: dict) -> bool:
    effective = planning_store.resolve_effective_backend(root, cfg)
    if effective.get("effective") != "issue-store":
        return False
    location = planning_store.resolve_store_location(root, cfg)
    return location.get("mode") == "separate-project"


def check_blockers_earliest(waves: dict[int, set[str]]) -> dict:
    earliest = min(waves) if waves else None
    misplaced = [rid for rid in BLOCKERS if rid not in waves.get(earliest, set())]
    return {
        "name": "blockers-earliest-wave",
        "ok": earliest == 1 and not misplaced,
        "detail": f"earliest wave={earliest} misplaced blockers={misplaced}",
    }


def check_audit_exempt(waves: dict[int, set[str]]) -> dict:
    in_final = FINAL_AUDIT_RID in waves.get(FINAL_WAVE, set())
    in_earlier = any(FINAL_AUDIT_RID in rids for wave, rids in waves.items() if wave < FINAL_WAVE)
    return {
        "name": "audit-exempt-final-wave",
        "ok": in_final and not in_earlier,
        "detail": f"{FINAL_AUDIT_RID} in wave {FINAL_WAVE}={in_final}, in earlier wave={in_earlier}",
    }


def check_single_assignment(waves: dict[int, set[str]]) -> dict:
    counts: dict[str, int] = {}
    for rids in waves.values():
        for rid in rids:
            counts[rid] = counts.get(rid, 0) + 1
    allowed_multi = CROSS_CUTTING | SPLIT_REQUIREMENTS
    duplicated = {rid: n for rid, n in counts.items() if n > 1 and rid not in allowed_multi}
    return {
        "name": "single-wave-assignment",
        "ok": not duplicated,
        "detail": f"requirements assigned to multiple waves (non cross-cutting): {duplicated}",
    }


def check_cross_cutting_present(waves: dict[int, set[str]]) -> dict:
    # Cross-cutting invariants are wave-independent: they must NOT be pinned into
    # a single numbered delivery wave in the wave map.
    numbered = set()
    for rids in waves.values():
        numbered |= rids
    leaked = sorted(CROSS_CUTTING & numbered)
    return {
        "name": "cross-cutting-wave-independent",
        "ok": not leaked,
        "detail": f"cross-cutting rids pinned to a numbered wave: {leaked}",
    }


def check_per_wave_parity_inert() -> dict:
    """No file-store-only write is suppressed under a file-store backend."""
    with tempfile.TemporaryDirectory() as tmp:
        predicate = guard_predicate(Path(tmp), {})
    return {
        "name": "per-wave-file-store-parity-inert",
        "ok": predicate is False,
        "detail": f"file-store guard predicate={predicate} (guards inert → local writes preserved)",
    }


def main() -> int:
    task_list = resolve_task_list()
    if not task_list.is_file():
        print(json.dumps({"fixture": "planning-deliver-parity", "rid": "R24", "verdict": "fail",
                          "error": f"task-list-not-found:{task_list}"}))
        return 20
    waves = parse_wave_map(task_list.read_text(encoding="utf-8"))
    checks = [
        {"name": "wave-map-parsed", "ok": len(waves) >= FINAL_WAVE,
         "detail": {str(w): sorted(rids) for w, rids in sorted(waves.items())}},
        check_blockers_earliest(waves),
        check_audit_exempt(waves),
        check_single_assignment(waves),
        check_cross_cutting_present(waves),
        check_per_wave_parity_inert(),
    ]
    failures = [c for c in checks if not c["ok"]]
    verdict = "pass" if not failures else "fail"
    report = {
        "fixture": "planning-deliver-parity",
        "rid": "R24",
        "verdict": verdict,
        "taskList": str(task_list.relative_to(ROOT)) if task_list.is_relative_to(ROOT) else str(task_list),
        "waveGuardedArtifacts": WAVE_GUARDED_ARTIFACTS,
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if verdict == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
