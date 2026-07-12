#!/usr/bin/env python3
"""
# R16 no-regression (PRD 035): frozen immutability, traceability, and spec-rigor gates feed the delivery loop.
Pre-freeze spec-rigor gate (PRD 031)."""
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

import doc_format
import planning_artifact_handle as pah
import wave_deliver as wd
from phase_sizing import evaluate_freeze_gate, has_advisory_block
from _sw.cli import run_module_main

AMBIGUITY = re.compile(r"\b(TBD|TODO|FIXME|\?\?\?|to be determined)\b", re.I)


def _run(
    root: Path,
    artifact: str,
    body_path: str,
    tier: str,
    prd_path: str,
    *,
    unit_id: str | None = None,
    prd_unit_id: str | None = None,
) -> int:
    content, source = pah.resolve_artifact_text(root, body_path, unit_id=unit_id)
    if content is None:
        print(json.dumps({"verdict": "fail", "error": f"artifact not found: {body_path}", "artifact": artifact}))
        return 20
    text = content
    findings: list[dict] = []

    def add(gate: str, severity: str, message: str, rid: str | None = None) -> None:
        item = {"gate": gate, "severity": severity, "message": message}
        if rid:
            item["rid"] = rid
        findings.append(item)

    def section_body(name: str) -> str:
        m = re.search(rf"^##\s+{re.escape(name)}\s*$([\s\S]*?)(?=^##\s|\Z)", text, re.M | re.I)
        return m.group(1) if m else ""

    if artifact == "prd":
        rids: list[str] = []
        for rid, body in doc_format.extract_rd_bullets(text):
            if not rid.startswith("R"):
                continue
            rids.append(rid)
            if AMBIGUITY.search(body):
                add("checklist", "error", f"ambiguity marker in {rid}", rid)
            if len(body) < 12:
                add("checklist", "warn", f"requirement text very short in {rid}", rid)
        if not rids:
            add("checklist", "error", "no R-IDs found in Requirements bullets")
        for d in sorted({r for r in rids if rids.count(r) > 1}):
            add("checklist", "error", f"duplicate R-ID {d}", d)
        for sec in ("Overview", "Goals", "Non-Goals", "Requirements", "Testing Strategy"):
            if not re.search(rf"^##\s+{re.escape(sec)}\s*$", text, re.M | re.I):
                add("checklist", "error", f"missing section: {sec}")
        if tier == "full":
            oq = section_body("Open Questions")
            if oq.strip():
                for line in oq.splitlines():
                    s = line.strip()
                    if not s or s.startswith("#"):
                        continue
                    if s.lower() in ("none", "(none)", "n/a", "- none"):
                        continue
                    if re.match(r"^- \[[ xX]\]", s) or AMBIGUITY.search(s) or s.startswith("- "):
                        add("clarify", "error", f"unresolved open question: {s[:80]}")
        worst = "pass"
        if any(f["severity"] == "error" for f in findings):
            worst = "fail"
        elif any(f["severity"] == "warn" for f in findings):
            worst = "warn"
        print(json.dumps({"verdict": worst, "artifact": "prd", "tier": tier, "findings": findings}, ensure_ascii=False))
        return 0 if worst == "pass" else 10 if worst == "warn" else 20

    if artifact == "brainstorm":
        rids: list[str] = []
        for rid, body in doc_format.extract_rd_bullets(text):
            if not rid.startswith("R"):
                continue
            rids.append(rid)
            if AMBIGUITY.search(body):
                add("checklist", "error", f"ambiguity marker in {rid}", rid)
            if len(body) < 12:
                add("checklist", "warn", f"requirement text very short in {rid}", rid)
        if not rids:
            add("checklist", "error", "no R-IDs found in Requirements bullets")
        for d in sorted({r for r in rids if rids.count(r) > 1}):
            add("checklist", "error", f"duplicate R-ID {d}", d)
        prev_num = 0
        for rid in rids:
            try:
                num = int(rid[1:])
            except ValueError:
                add("checklist", "error", f"invalid R-ID {rid}", rid)
                continue
            if num <= prev_num:
                add(
                    "checklist",
                    "error",
                    f"R-ID {rid} breaks monotonic increase (previous was R{prev_num})",
                    rid,
                )
            prev_num = max(prev_num, num)
        for sec in (
            "Summary",
            "Problem Frame",
            "Key Decisions",
            "Requirements",
            "Success Criteria",
            "Scope Boundaries",
            "Open Questions",
        ):
            if not re.search(rf"^##\s+{re.escape(sec)}\s*$", text, re.M | re.I):
                add("checklist", "error", f"missing section: {sec}")
        worst = "pass"
        if any(f["severity"] == "error" for f in findings):
            worst = "fail"
        elif any(f["severity"] == "warn" for f in findings):
            worst = "warn"
        print(
            json.dumps(
                {"verdict": worst, "artifact": "brainstorm", "tier": tier, "findings": findings},
                ensure_ascii=False,
            )
        )
        return 0 if worst == "pass" else 10 if worst == "warn" else 20

    if artifact == "decision":
        dids: list[str] = []
        for did, body in doc_format.extract_rd_bullets(text):
            if not did.startswith("D"):
                continue
            dids.append(did)
            if AMBIGUITY.search(body):
                add("checklist", "error", f"ambiguity marker in {did}", did)
            if len(body) < 12:
                add("checklist", "warn", f"requirement text very short in {did}", did)
        if not dids:
            add("checklist", "error", "no D-IDs found in Decision bullets")
        for d in sorted({x for x in dids if dids.count(x) > 1}):
            add("checklist", "error", f"duplicate D-ID {d}", d)
        for sec in ("Context", "Decision", "Rationale", "Alternatives", "Consequences"):
            if not re.search(rf"^##\s+{re.escape(sec)}\s*$", text, re.M | re.I):
                add("checklist", "error", f"missing section: {sec}")
        worst = "pass"
        if any(f["severity"] == "error" for f in findings):
            worst = "fail"
        elif any(f["severity"] == "warn" for f in findings):
            worst = "warn"
        print(json.dumps({"verdict": worst, "artifact": "decision", "tier": tier, "findings": findings}, ensure_ascii=False))
        return 0 if worst == "pass" else 10 if worst == "warn" else 20

    if artifact == "tasks":
        if not prd_path:
            add("analyze", "error", "--prd required for tasks analyze")
            print(json.dumps({"verdict": "fail", "artifact": "tasks", "findings": findings}))
            return 20
        prd_file = pah.materialize_artifact_file(root, prd_path, unit_id=prd_unit_id)
        if prd_file is None:
            add("analyze", "error", "--prd required and must exist for tasks analyze")
            print(json.dumps({"verdict": "fail", "artifact": "tasks", "findings": findings}))
            return 20
        union = json.loads(
            subprocess.check_output([sys.executable, str(root / "scripts/spec-union.py"), str(prd_file)], text=True)
        )
        union_ids = [r["id"] for r in union.get("requirements", [])]
        if not re.search(r"^##\s+Traceability\s*$", text, re.M | re.I):
            add("analyze", "error", "missing ## Traceability section")
        if has_advisory_block(text):
            add("analyze", "error", "task list contains sizing advisory block — strip before freeze")
        if wd.parse_frontmatter(text).get("frozen", "").lower() == "true":
            task_list_path = Path(body_path)
            if not task_list_path.is_absolute():
                task_list_path = (root / task_list_path).resolve()
            if not task_list_path.is_file():
                materialized = pah.materialize_artifact_file(
                    root, body_path, unit_id=unit_id
                )
                if materialized is not None:
                    task_list_path = materialized
            if task_list_path.is_file():
                freeze_gate = evaluate_freeze_gate(root, task_list_path)
                if freeze_gate.get("verdict") == "block":
                    phases = ", ".join(
                        str(p) for p in freeze_gate.get("overThresholdPhases") or []
                    )
                    add(
                        "analyze",
                        "error",
                        f"sizing freeze gate blocked — over-threshold phase(s): {phases or 'unknown'}",
                        "R16",
                    )
            else:
                add(
                    "analyze",
                    "error",
                    "sizing freeze gate requires a resolvable task list path",
                    "R16",
                )
        phase_ids = sorted({p["id"] for p in doc_format.extract_phases(text)}, key=int)
        dep_rows_list = doc_format.extract_phase_dependencies(text)
        if dep_rows_list is None:
            add("analyze", "error", "missing ## Phase Dependencies section")
        else:
            dep_rows: dict[str, str] = {}
            for row in dep_rows_list:
                phase, depends = row["phase"], row["depends_on"]
                if phase in dep_rows:
                    add("analyze", "error", f"duplicate Phase Dependencies row for phase {phase}")
                dep_rows[phase] = depends
            phase_set = set(phase_ids)
            for pid in phase_ids:
                if pid not in dep_rows:
                    add("analyze", "error", f"Phase Dependencies missing row for phase {pid}")
            for phase, depends in dep_rows.items():
                if phase not in phase_set:
                    add("analyze", "error", f"Phase Dependencies row for unknown phase {phase}")
                raw = depends.strip().lower()
                if raw in ("none", "—", "-", ""):
                    continue
                for dep in re.findall(r"\d+", raw):
                    if dep not in phase_set:
                        add("analyze", "error", f"phase {phase} depends on unknown phase {dep}")
                    if dep == phase:
                        add("analyze", "error", f"phase {phase} cannot depend on itself")
        for rid in union_ids:
            if rid not in text:
                add("analyze", "error", f"R-ID {rid} from union not referenced in task list", rid)
        worst = "fail" if any(f["severity"] == "error" for f in findings) else "pass"
        print(json.dumps({"verdict": worst, "artifact": "tasks", "findings": findings, "unionRids": union_ids}, ensure_ascii=False))
        return 0 if worst == "pass" else 20

    print(json.dumps({"verdict": "fail", "error": f"unknown artifact: {artifact}"}))
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spec-rigor-check.py")
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--path", required=True)
    parser.add_argument("--tier", default="standard")
    parser.add_argument("--prd", default="")
    parser.add_argument("--unit-id", default="")
    parser.add_argument("--prd-unit-id", default="")
    args = parser.parse_args(argv)
    root = SCRIPT_DIR.parent
    return _run(
        root,
        args.artifact,
        args.path,
        args.tier,
        args.prd,
        unit_id=args.unit_id or None,
        prd_unit_id=args.prd_unit_id or None,
    )


if __name__ == "__main__":
    run_module_main(main)
