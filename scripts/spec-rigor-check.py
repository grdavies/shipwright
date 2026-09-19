#!/usr/bin/env python3
"""
# R16 no-regression (PRD 035): frozen immutability, traceability, and spec-rigor gates feed the delivery loop.
Pre-freeze spec-rigor gate (PRD 031)."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import doc_format
import planning_artifact_handle as pah
from repository_context import POSTURE_PLUGIN_SELF, resolve_repository_posture

# PRD 358 R7 — R/D bullet grammar is single-sourced in doc_format (spec-rigor and
# doc-format-normalize must not duplicate those patterns).
import wave_deliver as wd
from phase_sizing import evaluate_freeze_gate, has_advisory_block
from _sw.cli import run_module_main

# Layered ambiguity matcher (PRD 361 phase 1 / PRD 364 R5–R6) — precedence: allowlist,
# unresolved phrase / ???, vocab-restricted punctuation wrap, Title-case named state,
# slash-taxonomy (lowercase), else hard markers.
_SLASH_TAXONOMY_LOWERCASE = re.compile(
    r"(?<![A-Za-z0-9/])(?:[a-z][a-z0-9]*/)+[a-z][a-z0-9]*(?![A-Za-z0-9/])"
)
_TITLE_CASE_NAMED_STATE = re.compile(
    r"\b(?:Todo|Idea|Note|Draft|Pending|Done|Blocked|Backlog)\b"
)
_TRIPLE_QUESTION = re.compile(r"\?\?\?")
_UNRESOLVED_PHRASE = re.compile(r"\bto be determined\b", re.I)
_CASUAL_LOWER_MARKER = re.compile(r"\b(todo|tbd|fixme)\b")
_HARD_AMBIGUITY_MARKER = re.compile(r"\b(TBD|TODO|FIXME)\b", re.I)
# PRD 364 R5 — wraps are colliding unfinished-work vocabulary only (not any-word).
_COLON_WRAP = re.compile(r"\b(TODO|TBD|FIXME)\s*:", re.I)
_BRACKET_WRAP = re.compile(r"\[(TODO|TBD|FIXME)\]", re.I)
_FRONTMATTER_BLOCK = re.compile(r"\A---\s*\n([\s\S]*?)\n---\s*(?:\n|$)", re.M)
_FLOW_LIST = re.compile(r"^\[(.*)\]$", re.S)


def _parse_flow_string_list(raw: str) -> list[str] | None:
    """Parse YAML flow-style string list (`[a, b]`); None when not that shape."""
    match = _FLOW_LIST.match(raw.strip())
    if not match:
        return None
    inner = match.group(1).strip()
    if not inner:
        return []
    items: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    escaped = False
    for ch in inner:
        if quote:
            if escaped:
                buf.append(ch)
                escaped = False
                continue
            if ch == "\\" and quote == '"':
                escaped = True
                continue
            if ch == quote:
                quote = None
                continue
            buf.append(ch)
            continue
        if ch in ("'", '"'):
            quote = ch
            continue
        if ch == ",":
            items.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    items.append("".join(buf).strip())
    if quote is not None:
        return None
    return [item for item in items if item != ""]


def _reviewed_literals_from_value(value: object) -> tuple[frozenset[str] | None, str | None]:
    """Normalize reviewedLiterals to an exact-string allowlist. Fail closed on bad shapes."""
    if value is None:
        return frozenset(), None
    if isinstance(value, str):
        flow = _parse_flow_string_list(value)
        if flow is None:
            return None, "reviewedLiterals must be a YAML list of strings"
        value = flow
    if not isinstance(value, list):
        return None, "reviewedLiterals must be a YAML list of strings"
    if not value:
        return frozenset(), None
    allow: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            return None, "reviewedLiterals must be a YAML list of strings"
        allow.append(item)
    return frozenset(allow), None


def _reviewed_literals_allowlist(text: str) -> tuple[frozenset[str], str | None]:
    """Parse optional frontmatter reviewedLiterals (list-capable; not planning_bundle)."""
    from yaml_structured import safe_load

    match = _FRONTMATTER_BLOCK.match(text)
    if not match:
        return frozenset(), None
    try:
        fm = safe_load(match.group(1))
    except Exception:
        return frozenset(), None
    if not isinstance(fm, dict) or "reviewedLiterals" not in fm:
        return frozenset(), None
    allow, err = _reviewed_literals_from_value(fm.get("reviewedLiterals"))
    if err:
        return frozenset(), err
    return allow or frozenset(), None


def _decision_log_covers_reviewed_literals(text: str, allowlist: frozenset[str]) -> bool:
    """R5: non-empty reviewedLiterals requires Decision Log naming those tokens."""
    if not allowlist:
        return True
    m = re.search(r"^##\s+Decision Log\s*$([\s\S]*?)(?=^##\s|\Z)", text, re.M | re.I)
    if not m:
        return False
    log = m.group(1)
    if not log.strip():
        return False
    return all(token in log for token in allowlist)


def _allowlisted(fragment: str, allowlist: frozenset[str]) -> bool:
    return fragment in allowlist


def text_has_ambiguity_marker(body: str, allowlist: frozenset[str] | None = None) -> bool:
    """Return True when layered matcher finds a blocking ambiguity marker in body.

    Precedence (PRD 361 / PRD 364 R6): allowlist, unresolved phrase / ???,
    vocab-restricted punctuation wrap, Title-case named state, slash-taxonomy
    (lowercase), else hard markers. Wraps run before Title-case masking.
    """
    allow = allowlist if allowlist is not None else frozenset()
    if not body or not body.strip():
        return False

    if _TRIPLE_QUESTION.search(body) and not any("???" in entry for entry in allow):
        return True
    if _UNRESOLVED_PHRASE.search(body) and not any(
        "to be determined" in entry.lower() for entry in allow
    ):
        return True

    for match in _COLON_WRAP.finditer(body):
        token = match.group(1)
        if not (_allowlisted(token, allow) or _allowlisted(f"{token}:", allow)):
            return True
    for match in _BRACKET_WRAP.finditer(body):
        inner = match.group(1).strip()
        bracketed = f"[{match.group(1)}]"
        if not (_allowlisted(inner, allow) or _allowlisted(bracketed, allow)):
            return True

    masked = _SLASH_TAXONOMY_LOWERCASE.sub(" ", body)
    masked = _TITLE_CASE_NAMED_STATE.sub(" ", masked)

    for match in _CASUAL_LOWER_MARKER.finditer(masked):
        if not _allowlisted(match.group(0), allow):
            return True
    for match in _HARD_AMBIGUITY_MARKER.finditer(masked):
        if not _allowlisted(match.group(0), allow):
            return True
    return False

# PRD 342 R34 — Acceptance Scenarios + Success Criteria required for new PRD bodies only.
PRD_BODY_CONTRACT_KEY = "prdBodyContract"
PRD_BODY_CONTRACT_V2 = "v2"
PRD_V2_REQUIRED_SECTIONS = ("Acceptance Scenarios", "Success Criteria")
PRD_BASE_REQUIRED_SECTIONS = ("Overview", "Goals", "Non-Goals", "Requirements", "Testing Strategy")

PACKAGE_ROOT = SCRIPT_DIR.parent


def _resolve_cli_root(raw: str | None) -> str | None:
    if raw is not None and str(raw).strip():
        return str(raw).strip()
    if os.environ.get("SW_HARNESS", "").strip() == "1":
        harness_root = os.environ.get("ROOT", "").strip()
        if harness_root:
            return harness_root
    return None


def _resolve_consumer_root(raw: str | None) -> tuple[Path | None, str | None]:
    """PRD 358 R8 — consumer workspace root; not implicit SCRIPT_DIR.parent."""
    if raw is None or not str(raw).strip():
        return None, "missing required --root"
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        return None, f"--root is not a directory: {root}"
    scripts_at_root = root / "scripts"
    try:
        if scripts_at_root.resolve() == SCRIPT_DIR.resolve():
            if resolve_repository_posture(root) != POSTURE_PLUGIN_SELF:
                return None, "consumer --root must not be the package scripts/ parent"
    except (OSError, RuntimeError, ValueError):
        return None, "consumer --root must not be the package scripts/ parent"
    return root, None


def _fail_root(message: str) -> int:
    print(json.dumps({"verdict": "fail", "error": message, "gate": "root"}))
    return 20


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
    reviewed_literals, reviewed_literals_error = _reviewed_literals_allowlist(text)
    findings: list[dict] = []

    def add(gate: str, severity: str, message: str, rid: str | None = None) -> None:
        item = {"gate": gate, "severity": severity, "message": message}
        if rid:
            item["rid"] = rid
        findings.append(item)

    if reviewed_literals_error:
        add("checklist", "error", reviewed_literals_error)
    elif reviewed_literals and not _decision_log_covers_reviewed_literals(text, reviewed_literals):
        add(
            "checklist",
            "error",
            "non-empty reviewedLiterals requires Decision Log naming each token",
        )

    def issue_store_virtual_handle_gate() -> None:
        """Traceability + doctor gate for issue-store virtual handles (PRD 280 R11/R12)."""
        if source != "issue-store":
            return
        from host_lib import load_workflow_config
        import planning_store_facade as planning_store_module

        cfg = load_workflow_config(root)
        gate = planning_store_module.doctor_tracked_prd_bodies(root, cfg)
        if gate.get("verdict") == "fail":
            add(
                "analyze",
                "error",
                "tracked docs/prds bodies forbidden in code repo under issue-store virtual handle",
                "R11",
            )
        add(
            "analyze",
            "pass",
            "artifact resolved via issue-store virtual handle for traceability",
            "R12",
        )

    def section_body(name: str) -> str:
        m = re.search(rf"^##\s+{re.escape(name)}\s*$([\s\S]*?)(?=^##\s|\Z)", text, re.M | re.I)
        return m.group(1) if m else ""

    if artifact == "prd":
        rids: list[str] = []
        for rid, body in doc_format.extract_rd_bullets(text):
            if not rid.startswith("R"):
                continue
            rids.append(rid)
            if text_has_ambiguity_marker(body, reviewed_literals):
                add("checklist", "error", f"ambiguity marker in {rid}", rid)
            if len(body) < 12:
                add("checklist", "warn", f"requirement text very short in {rid}", rid)
        if not rids:
            add("checklist", "error", "no R-IDs found in Requirements bullets")
        for d in sorted({r for r in rids if rids.count(r) > 1}):
            add("checklist", "error", f"duplicate R-ID {d}", d)
        for sec in PRD_BASE_REQUIRED_SECTIONS:
            if not re.search(rf"^##\s+{re.escape(sec)}\s*$", text, re.M | re.I):
                add("checklist", "error", f"missing section: {sec}")
        # R34 — forward-only: require Acceptance Scenarios + Success Criteria when
        # frontmatter declares prdBodyContract: v2 (new PRDs). Existing bodies without
        # the contract key remain grandfathered and never retroactively fail.
        try:
            import planning_bundle as _pb

            fm = _pb.parse_frontmatter(text) or {}
        except Exception:
            fm = {}
        if not isinstance(fm, dict):
            fm = {}
        contract = str(fm.get(PRD_BODY_CONTRACT_KEY, "") or "").strip().lower()
        if contract in {PRD_BODY_CONTRACT_V2, "2", "true", "yes"}:
            for sec in PRD_V2_REQUIRED_SECTIONS:
                if not re.search(rf"^##\s+{re.escape(sec)}\s*$", text, re.M | re.I):
                    add(
                        "checklist",
                        "error",
                        f"missing section: {sec} (required for prdBodyContract: v2)",
                    )
        if tier == "full":
            oq = section_body("Open Questions")
            if oq.strip():
                for line in oq.splitlines():
                    s = line.strip()
                    if not s or s.startswith("#"):
                        continue
                    if s.lower() in ("none", "(none)", "n/a", "- none"):
                        continue
                    if (
                        re.match(r"^- \[[ xX]\]", s)
                        or text_has_ambiguity_marker(s, reviewed_literals)
                        or s.startswith("- ")
                    ):
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
            if text_has_ambiguity_marker(body, reviewed_literals):
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
            if text_has_ambiguity_marker(body, reviewed_literals):
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
        issue_store_virtual_handle_gate()
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
            subprocess.check_output(
                [sys.executable, str(SCRIPT_DIR / "spec-union.py"), str(prd_file)],
                text=True,
            )
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
    parser.add_argument(
        "--root",
        default=None,
        help="Consumer repository root for workflow config and issue-store artifact resolve (PRD 358 R8)",
    )
    args = parser.parse_args(argv)
    root, root_error = _resolve_consumer_root(_resolve_cli_root(args.root))
    if root is None:
        return _fail_root(root_error or "invalid --root")
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
