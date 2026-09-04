#!/usr/bin/env python3
"""Converge assessment composition (PRD 342 R44).

Composes existing gates — claims audit, gap check, and verify gates — plus exactly
one new bundle-anchored assessor that checks implementation against bundle assets.
Findings are advisory; this module never grants merge authority (R45).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import claims_audit_lib as claims_lib  # noqa: E402
import planning_bundle as planning_bundle  # noqa: E402
import planning_paths as pp  # noqa: E402

COMPOSED_GATE_IDS = (
    "claims-audit",
    "gap-check",
    "verify-gates",
)
BUNDLE_ANCHORED_ASSESSOR_ID = "bundle-anchored"
ALL_ASSESSOR_IDS = COMPOSED_GATE_IDS + (BUNDLE_ANCHORED_ASSESSOR_ID,)

_PATH_IN_BACKTICKS = re.compile(r"`([^`\n]+)`")
_PATHISH = re.compile(
    r"(?:^|[\s(\[\"'])("
    r"(?:scripts|core|docs|platforms|hooks|rules|sw)/"
    r"[A-Za-z0-9_./-]+\.[A-Za-z0-9]+)"
)


def emit(payload: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(exit_code)


def _step(
    assessor_id: str,
    *,
    verdict: str,
    detail: str,
    findings: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": assessor_id,
        "verdict": verdict,
        "detail": detail,
        "findings": list(findings or []),
    }
    payload.update(extra)
    return payload


def run_claims_audit_step(
    root: Path,
    *,
    task_list: str,
    phase_id: str | None = None,
) -> dict[str, Any]:
    """Compose the existing claims-audit gate (advisory)."""
    task_path = Path(task_list)
    if not task_path.is_absolute():
        task_path = root / task_list
    if not task_path.is_file():
        return _step(
            "claims-audit",
            verdict="skip",
            detail="task list not readable for claims audit",
        )
    if not phase_id:
        return _step(
            "claims-audit",
            verdict="pass",
            detail="no phase-id scoped for claims audit; composed gate recorded",
            claims=[],
        )
    try:
        result = claims_lib.audit_phase_claims(
            root,
            tasks_path=task_path,
            phase_id=str(phase_id),
        )
    except Exception as exc:  # noqa: BLE001 — advisory composition must not crash converge
        return _step(
            "claims-audit",
            verdict="error",
            detail=f"claims audit raised: {exc}",
        )
    failures = result.get("failures") or []
    return _step(
        "claims-audit",
        verdict=str(result.get("verdict") or "pass"),
        detail="claims audit composed",
        findings=[
            {"ref": item.get("ref"), "reason": item.get("reason")}
            for item in failures
            if isinstance(item, dict)
        ],
    )


def run_gap_check_step(root: Path, *, phase_slug: str | None = None) -> dict[str, Any]:
    """Compose the existing gap-check gate (advisory; does not write durable status)."""
    if not phase_slug:
        return _step(
            "gap-check",
            verdict="pass",
            detail="no phase-slug scoped for gap check; composed gate recorded",
        )
    try:
        gate_path = SCRIPT_DIR / "gap-check-gate.py"
        spec = importlib.util.spec_from_file_location("gap_check_gate", gate_path)
        if spec is None or spec.loader is None:
            return _step("gap-check", verdict="error", detail="gap-check-gate missing")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        ok, cause = mod.deliver_gap_check_ok(
            root, phase_slug, require_status=False, auto_repair=False
        )
        return _step(
            "gap-check",
            verdict="pass" if ok else "fail",
            detail="gap check composed",
            cause=cause,
        )
    except Exception as exc:  # noqa: BLE001
        return _step("gap-check", verdict="error", detail=f"gap check raised: {exc}")


def run_verify_gates_step(
    root: Path,
    *,
    skip_execute: bool = False,
) -> dict[str, Any]:
    """Compose verify gates (advisory). Suite execution is skippable for unit tests."""
    if skip_execute:
        return _step(
            "verify-gates",
            verdict="pass",
            detail="verify gates composed (execution skipped)",
            skippedExecute=True,
        )
    try:
        import wave_failure as wf

        outcome = wf.run_verify_suite(root, root, flaky_retries=0, scope="phase")
        verdict = str(outcome.get("verdict") or "pass")
        return _step(
            "verify-gates",
            verdict=verdict,
            detail="verify gates composed",
            attempts=outcome.get("attempts"),
            note=outcome.get("note"),
        )
    except Exception as exc:  # noqa: BLE001
        return _step(
            "verify-gates",
            verdict="error",
            detail=f"verify gates raised: {exc}",
        )


def _extract_path_refs(text: str) -> list[str]:
    refs: list[str] = []
    for match in _PATH_IN_BACKTICKS.finditer(text):
        candidate = match.group(1).strip()
        if "/" in candidate and not candidate.startswith("http"):
            refs.append(candidate.split("#", 1)[0].strip())
    for match in _PATHISH.finditer(text):
        refs.append(match.group(1).strip())
    seen: set[str] = set()
    out: list[str] = []
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        out.append(ref)
    return out


def run_bundle_anchored_assessor(
    root: Path,
    *,
    unit_dir: Path | str,
) -> dict[str, Any]:
    """Exactly one new assessor: check implementation against bundle assets (R44)."""
    root = Path(root).resolve()
    unit_path = Path(unit_dir)
    if not unit_path.is_absolute():
        unit_path = root / unit_path
    unit_path = unit_path.resolve()
    bundle = planning_bundle.validate_unit_bundle(root, unit_path)
    disposition = str(bundle.get("disposition") or "")
    if disposition == planning_bundle.DISPOSITION_UNDECLARED:
        return _step(
            BUNDLE_ANCHORED_ASSESSOR_ID,
            verdict="pass",
            detail="unit declares no bundle; assessor records undeclared disposition",
            disposition=disposition,
            present=list(bundle.get("present") or []),
            missing=[],
        )

    present_roles = list(bundle.get("present") or [])
    findings: list[dict[str, Any]] = []
    checked_refs = 0
    missing_refs = 0
    worktree = pp.git_root(root)

    try:
        unit_rel = str(unit_path.resolve().relative_to(worktree.resolve())).replace(
            "\\", "/"
        )
    except ValueError:
        unit_rel = str(unit_path)

    for role in present_roles:
        try:
            rel = pp.bundle_asset_rel(unit_rel, role)
        except Exception:
            rel = str(Path(unit_rel) / pp.bundle_asset_filename(role))
        asset_path = worktree / rel
        if not asset_path.is_file():
            findings.append(
                {
                    "role": role,
                    "path": rel,
                    "reason": "asset-listed-present-but-unreadable",
                }
            )
            continue
        try:
            text = asset_path.read_text(encoding="utf-8")
        except OSError as exc:
            findings.append(
                {"role": role, "path": rel, "reason": f"unreadable:{exc}"}
            )
            continue
        for ref in _extract_path_refs(text):
            checked_refs += 1
            if not (worktree / ref).exists():
                missing_refs += 1
                findings.append(
                    {
                        "role": role,
                        "path": rel,
                        "ref": ref,
                        "reason": "bundle-ref-missing-from-tree",
                    }
                )

    if disposition == planning_bundle.DISPOSITION_INCOMPLETE:
        for role in bundle.get("missing") or []:
            findings.append(
                {
                    "role": role,
                    "reason": "declared-bundle-asset-missing",
                }
            )

    verdict = "findings" if findings else "pass"
    return _step(
        BUNDLE_ANCHORED_ASSESSOR_ID,
        verdict=verdict,
        detail=(
            "bundle-anchored assessor checked implementation refs against present assets"
        ),
        disposition=disposition,
        present=present_roles,
        missing=list(bundle.get("missing") or []),
        checkedRefs=checked_refs,
        missingRefs=missing_refs,
        findings=findings,
    )


def compose_converge_assessment(
    root: Path,
    *,
    task_list: str,
    unit_dir: Path | str,
    phase_id: str | None = None,
    phase_slug: str | None = None,
    skip_verify_execute: bool = False,
) -> dict[str, Any]:
    """Run the R44 composition: three existing gates + one bundle-anchored assessor."""
    steps = [
        run_claims_audit_step(root, task_list=task_list, phase_id=phase_id),
        run_gap_check_step(root, phase_slug=phase_slug),
        run_verify_gates_step(root, skip_execute=skip_verify_execute),
        run_bundle_anchored_assessor(root, unit_dir=unit_dir),
    ]
    ids = [str(step.get("id")) for step in steps]
    new_assessors = [step_id for step_id in ids if step_id not in COMPOSED_GATE_IDS]
    return {
        "verdict": "pass",
        "assessorIds": ids,
        "composedGateIds": list(COMPOSED_GATE_IDS),
        "bundleAnchoredAssessorId": BUNDLE_ANCHORED_ASSESSOR_ID,
        "newAssessorCount": len(new_assessors),
        "steps": steps,
        "taskList": task_list,
        "unitDir": str(unit_dir),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Converge assessment composition (PRD 342 R44)"
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--task-list", required=True)
    parser.add_argument("--unit-dir", required=True)
    parser.add_argument("--phase-id")
    parser.add_argument("--phase-slug")
    parser.add_argument(
        "--skip-verify-execute",
        action="store_true",
        help="Record verify-gates composition without running the suite",
    )
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    report = compose_converge_assessment(
        root,
        task_list=args.task_list,
        unit_dir=args.unit_dir,
        phase_id=args.phase_id,
        phase_slug=args.phase_slug,
        skip_verify_execute=bool(args.skip_verify_execute),
    )
    emit(report, 0)


if __name__ == "__main__":
    main()
