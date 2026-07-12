"""Adversarial completion-claims audit (PRD 064 R3/R4)."""
from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import doc_format
from checkbox_diff import parse_task_checkboxes

SUBTASK_CHECKBOX = re.compile(r"^-\s+\[([ xX])\]\s+(\d+(?:\.\d+)+)\s+(.+)$")
EXPECTED_LINE = re.compile(r"^\s*-\s+\*\*Expected:\*\*\s*(.+)$")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_phase_subtasks(text: str, phase_id: str) -> list[dict[str, Any]]:
    chunk = doc_format.phase_section_text(text, phase_id)
    if not chunk:
        return []
    subtasks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in chunk.splitlines():
        match = SUBTASK_CHECKBOX.match(line)
        if match:
            if current:
                subtasks.append(current)
            ref_id = match.group(2)
            if not doc_format.REF_ID_PATTERN.match(ref_id):
                continue
            current = {
                "ref": ref_id,
                "title": match.group(3).strip(),
                "files": [],
                "expected": "",
                "checked": match.group(1).lower() == "x",
            }
            continue
        if not current:
            continue
        if "**File:**" in line:
            raw = re.sub(r"^\s*-?\s*\*\*File:\*\*\s*", "", line).strip()
            backtick_paths = re.findall(r"`([^`]+)`", raw)
            if backtick_paths:
                paths = [doc_format.normalize_file_path(p) for p in backtick_paths if p.strip()]
            else:
                paths = [
                    doc_format.normalize_file_path(p.strip())
                    for p in re.split(r"[,]|(?:\s+and\s+)|(?:\s+or\s+)", raw)
                    if p.strip()
                ]
            current["files"].extend(paths)
            continue
        expected_match = EXPECTED_LINE.match(line)
        if expected_match:
            current["expected"] = expected_match.group(1).strip()
    if current:
        subtasks.append(current)
    for st in subtasks:
        st["files"] = sorted(set(st.get("files") or []))
    return subtasks


def completed_claims(text: str, phase_id: str, *, refs: set[str] | None = None) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for st in parse_phase_subtasks(text, phase_id):
        ref = str(st.get("ref") or "")
        if refs is not None and ref not in refs:
            continue
        if not st.get("checked"):
            continue
        claims.append({
            "ref": ref,
            "title": st.get("title") or "",
            "files": list(st.get("files") or []),
            "expected": st.get("expected") or "",
        })
    return claims


def git_diff_paths(root: Path, base: str, head: str | None = None) -> set[str]:
    root = root.resolve()
    target = head or "HEAD"
    paths: set[str] = set()
    for args in (
        ["git", "-C", str(root), "diff", "--name-only", f"{base}...{target}"],
        ["git", "-C", str(root), "diff", "--name-only", base, target],
    ):
        proc = subprocess.run(args, capture_output=True, text=True)
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                path = line.strip()
                if path:
                    paths.add(path)
    return paths


def path_touched(declared: str, touched: set[str]) -> bool:
    declared = declared.strip().rstrip("/")
    if not declared:
        return False
    if declared in touched:
        return True
    prefix = declared.rstrip("/") + "/"
    return any(p == declared or p.startswith(prefix) for p in touched)


def _exists_or_dir_prefix(root: Path, declared: str) -> bool:
    path = root / declared
    if path.exists():
        return True
    if declared.endswith("/"):
        return path.is_dir()
    parent = path.parent
    return parent.is_dir() and any(parent.iterdir()) if parent.is_dir() else False


def mechanical_claim_results(claims: list[dict[str, Any]], touched: set[str], root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for claim in claims:
        ref = str(claim.get("ref") or "")
        files = list(claim.get("files") or [])
        missing_files = [f for f in files if not path_touched(f, touched)]
        if missing_files:
            results.append({
                "ref": ref,
                "verdict": "fail",
                "dimension": "mechanical",
                "reason": f"declared file(s) not touched in diff: {', '.join(missing_files)}",
            })
            continue
        absent = [f for f in files if not _exists_or_dir_prefix(root, f)]
        if absent:
            results.append({
                "ref": ref,
                "verdict": "fail",
                "dimension": "mechanical",
                "reason": f"declared path(s) missing on disk: {', '.join(absent)}",
            })
            continue
        results.append({
            "ref": ref,
            "verdict": "pass",
            "dimension": "mechanical",
            "reason": "declared file scope touched in diff",
        })
    return results


def normalize_agent_claims(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        ref = str(item.get("ref") or "")
        verdict = str(item.get("verdict") or "").lower()
        if ref and verdict in ("pass", "fail"):
            out.append({
                "ref": ref,
                "verdict": verdict,
                "dimension": "agent",
                "reason": str(item.get("reason") or item.get("detail") or ""),
            })
    return out


def merge_claim_results(
    mechanical: list[dict[str, Any]],
    agent: list[dict[str, Any]],
    *,
    claims: list[dict[str, Any]],
) -> dict[str, Any]:
    by_ref: dict[str, dict[str, Any]] = {}
    for row in mechanical:
        by_ref[str(row.get("ref"))] = dict(row)
    for row in agent:
        ref = str(row.get("ref"))
        prior = by_ref.get(ref)
        if prior and prior.get("verdict") == "fail":
            continue
        by_ref[ref] = dict(row)

    ordered_refs = [str(c.get("ref")) for c in claims]
    claim_rows: list[dict[str, Any]] = []
    for ref in ordered_refs:
        if ref in by_ref:
            claim_rows.append(by_ref[ref])
        else:
            claim_rows.append({
                "ref": ref,
                "verdict": "fail",
                "dimension": "agent",
                "reason": "missing agent verdict for completed claim",
            })

    for claim in claims:
        ref = str(claim.get("ref"))
        if not (claim.get("expected") or "").strip():
            continue
        has_agent = any(r.get("ref") == ref and r.get("dimension") == "agent" for r in agent)
        if not has_agent:
            claim_rows = [r for r in claim_rows if r.get("ref") != ref]
            claim_rows.append({
                "ref": ref,
                "verdict": "fail",
                "dimension": "agent",
                "reason": "expected contract present but agent verdict missing",
            })

    failures = [r for r in claim_rows if r.get("verdict") == "fail"]
    return {
        "verdict": "fail" if failures else "pass",
        "checkedAt": utc_now(),
        "claims": claim_rows,
        "failureCount": len(failures),
    }


def build_agent_brief(claims: list[dict[str, Any]], *, diff_paths: set[str], diff_stat: str = "") -> dict[str, Any]:
    return {
        "claims": claims,
        "touchedPaths": sorted(diff_paths),
        "diffStat": diff_stat,
        "instructions": (
            "Verify each completion claim against the branch diff. "
            "Return JSON {\"claims\":[{\"ref\":\"6.1\",\"verdict\":\"pass|fail\",\"reason\":\"...\"}]} "
            "for every claim. Fail closed on any mismatch between Expected and on-disk evidence."
        ),
    }


def apply_verification_overlay(verdict: dict[str, Any], claims_status: dict[str, Any] | None) -> dict[str, Any]:
    if not claims_status:
        return verdict
    if claims_status.get("verdict") == "fail":
        return {
            **verdict,
            "verdict": "inconclusive",
            "reason": "claims-audit: completion claim mismatch",
            "inconclusiveClass": "missing-required",
            "claimsAudit": claims_status,
        }
    if claims_status.get("claims"):
        return {**verdict, "claimsAudit": claims_status}
    return verdict


def resolve_diff_base(root: Path) -> str:
    try:
        import shipwright_state_lib as ssl
        state = ssl.read_state(root)
        parent = state.get("parentBranch")
        if parent:
            return str(parent)
    except Exception:
        pass
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD@{upstream}"],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()
    return "main"


def audit_phase_claims(
    root: Path,
    *,
    tasks_path: Path,
    phase_id: str,
    agent_claims: list[dict[str, Any]] | None = None,
    diff_base: str | None = None,
    head: str | None = None,
    claim_refs: set[str] | None = None,
) -> dict[str, Any]:
    text = tasks_path.read_text(encoding="utf-8")
    claims = completed_claims(text, phase_id, refs=claim_refs)
    if not claims:
        return {
            "verdict": "pass",
            "checkedAt": utc_now(),
            "claims": [],
            "failureCount": 0,
            "note": "no completed claims in scope",
        }
    base = diff_base or resolve_diff_base(root)
    touched = git_diff_paths(root, base, head=head)
    mechanical = mechanical_claim_results(claims, touched, root)
    agent = agent_claims or []
    result = merge_claim_results(mechanical, agent, claims=claims)
    result["completionClaims"] = claims
    result["diffBase"] = base
    if head:
        result["head"] = head
    return result


def claims_from_status(status: dict[str, Any]) -> list[dict[str, Any]]:
    raw = status.get("completionClaims")
    if isinstance(raw, list):
        return [c for c in raw if isinstance(c, dict) and c.get("ref")]
    return []


def _agent_pass_for_refs(refs: set[str]) -> list[dict[str, Any]]:
    return [{
        "ref": ref,
        "verdict": "pass",
        "dimension": "agent",
        "reason": "collect-time structural re-check only; ship-time agent audit authoritative",
    } for ref in sorted(refs)]


def collect_audit_from_status(
    root: Path,
    status: dict[str, Any],
    *,
    tasks_path: Path,
    phase_id: str,
    phase_branch: str | None = None,
) -> dict[str, Any]:
    claims = claims_from_status(status)
    if not claims:
        return {
            "verdict": "pass",
            "checkedAt": utc_now(),
            "claims": [],
            "failureCount": 0,
            "note": "no completionClaims on status — skipped",
        }
    head = str(status.get("head") or "")
    refs = {str(c.get("ref")) for c in claims}
    integration = phase_branch or resolve_diff_base(root)
    return audit_phase_claims(
        root,
        tasks_path=tasks_path,
        phase_id=phase_id,
        diff_base=integration,
        head=head or None,
        claim_refs=refs,
        agent_claims=_agent_pass_for_refs(refs),
    )


def phase_id_for_slug(tasks_text: str, phase_slug: str) -> str | None:
    for phase in doc_format.extract_phases(tasks_text):
        if phase.get("slug") == phase_slug:
            return str(phase.get("id") or "")
    return None
