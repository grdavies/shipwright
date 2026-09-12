#!/usr/bin/env python3
"""PRD 339 R32/R33 — bundle closeout gate (visibility nomenclature + Linear browse)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from prd339_cross_prd_gate import PRD_339_UNIT_ID

PRD_339_BUNDLE_CLOSEOUT_TEST = (
    "scripts/unit_tests/planning/test_prd339_bundle_closeout.py"
)
PRD_339_LINEAR_BROWSE_TEST = (
    "scripts/unit_tests/planning/test_prd339_linear_operator_browse.py"
)
GAP_001_ABSORB_UNIT_ID = "gap-001-planning-visibility-profile-names-conflate-redac"
GAP_079_ABSORB_UNIT_ID = "gap-079-add-linear-as-a-new-planning-store-issue-trackin"


def _gate_scripts_dir() -> Path:
    return Path(__file__).resolve().parent


def _repo_root(root: Path | None) -> Path:
    return root if root is not None else _gate_scripts_dir().parent


def _vendored_pytest_pythonpath(gate_repo: Path) -> list[str]:
    try:
        if str(gate_repo / "scripts") not in sys.path:
            sys.path.insert(0, str(gate_repo / "scripts"))
        from _sw.vendor_paths import vendor_roots

        return [str(path) for path in vendor_roots(gate_repo)]
    except Exception:
        return []


def _acceptance_test_ready(root: Path, rel_test: str) -> dict[str, Any]:
    test_path = root / rel_test
    if not test_path.is_file():
        return {
            "verdict": "blocked",
            "test": rel_test,
            "reason": "acceptance-test-missing",
        }
    gate_repo = _gate_scripts_dir().parent
    env = os.environ.copy()
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTEST_CURRENT_TEST", None)
    path_parts = [
        str(root / "scripts"),
        *_vendored_pytest_pythonpath(gate_repo),
    ]
    prev_pp = env.get("PYTHONPATH", "")
    if prev_pp:
        path_parts.append(prev_pp)
    env["PYTHONPATH"] = os.pathsep.join(part for part in path_parts if part)
    with tempfile.TemporaryDirectory(prefix="prd339-bundle-pytest-") as td:
        empty_ini = Path(td) / "pytest.ini"
        empty_ini.write_text(
            "[pytest]\npythonpath = scripts\n",
            encoding="utf-8",
        )
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(test_path),
                "-q",
                "--rootdir",
                str(root),
                "-c",
                str(empty_ini),
                "-p",
                "no:cacheprovider",
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
            env=env,
        )
    if proc.returncode == 0:
        return {"verdict": "ready", "test": rel_test}
    detail = "\n".join(
        part
        for part in ((proc.stdout or "").strip(), (proc.stderr or "").strip())
        if part
    )
    return {
        "verdict": "blocked",
        "test": rel_test,
        "reason": "acceptance-test-failed",
        "exitCode": proc.returncode,
        "stderr": detail[:4000] or None,
    }


def prd339_bundle_closeout_milestone(root: Path | None = None) -> dict[str, Any]:
    """Return ready when R32 visibility nomenclature and R33 Linear browse are green."""
    repo = _repo_root(root)
    from prd339_visibility_nomenclature import check_visibility_nomenclature

    nomenclature = check_visibility_nomenclature(repo)
    linear_browse = _acceptance_test_ready(repo, PRD_339_LINEAR_BROWSE_TEST)
    blocked: list[dict[str, Any]] = []
    if nomenclature.get("verdict") != "pass":
        blocked.append(
            {
                "verdict": "blocked",
                "check": "visibility-nomenclature",
                "reason": "visibility-tier-vs-storage-placement-failed",
                "failures": nomenclature.get("failures") or [],
            }
        )
    if linear_browse.get("verdict") != "ready":
        blocked.append({**linear_browse, "check": "linear-operator-browse"})
    if blocked:
        return {
            "verdict": "blocked",
            "action": "prd339-bundle-closeout-gate",
            "cause": "prd-339-bundle-closeout-not-merged-green",
            "prd339UnitId": PRD_339_UNIT_ID,
            "requirements": ["R32", "R33"],
            "blocked": blocked,
            "resumeCommand": (
                "merge and green PRD 339 R32 (visibility nomenclature) and "
                "R33 (Linear operator browse), then retry "
                f"python3 scripts/prd339_bundle_closeout.py {repo}"
            ),
        }
    return {
        "verdict": "ready",
        "action": "prd339-bundle-closeout-gate",
        "prd339UnitId": PRD_339_UNIT_ID,
        "requirements": ["R32", "R33"],
        "checks": [
            {"verdict": "ready", "check": "visibility-nomenclature"},
            linear_browse,
        ],
        "gap001UnitId": GAP_001_ABSORB_UNIT_ID,
        "gap079UnitId": GAP_079_ABSORB_UNIT_ID,
    }


def prd339_absorb_closeout_milestone(root: Path | None = None) -> dict[str, Any]:
    """Gate close-delivery-units until correctness, Linear, and bundle closeout are green."""
    repo = _repo_root(root)
    from prd339_cross_prd_gate import prd339_absorb_acceptance_milestone
    from prd339_phase1_acceptance import prd339_phase1_correctness_milestone

    phase1 = prd339_phase1_correctness_milestone(repo)
    cross = prd339_absorb_acceptance_milestone(repo)
    linear = _acceptance_test_ready(repo, PRD_339_LINEAR_BROWSE_TEST)
    bundle = prd339_bundle_closeout_milestone(repo)
    blocked: list[dict[str, Any]] = []
    if phase1.get("verdict") != "ready":
        blocked.append({**phase1, "gate": "phase1-correctness"})
    if cross.get("verdict") != "ready":
        blocked.append({**cross, "gate": "cross-prd-r37-r39"})
    if linear.get("verdict") != "ready":
        blocked.append({**linear, "gate": "linear-operator-browse"})
    if bundle.get("verdict") != "ready":
        blocked.append({**bundle, "gate": "bundle-closeout"})
    if blocked:
        return {
            "verdict": "blocked",
            "action": "prd339-absorb-closeout-gate",
            "cause": "prd-339-closeout-prerequisites-not-green",
            "prd339UnitId": PRD_339_UNIT_ID,
            "blocked": blocked,
            "resumeCommand": (
                "green PRD 339 phase-1 correctness, R37/R39, Linear operator browse, "
                "and bundle closeout, then retry "
                "python3 scripts/planning_store.py close-delivery-units "
                f"--prd-unit {PRD_339_UNIT_ID}"
            ),
        }
    return {
        "verdict": "ready",
        "action": "prd339-absorb-closeout-gate",
        "prd339UnitId": PRD_339_UNIT_ID,
        "checks": {
            "phase1": phase1,
            "crossPrd": cross,
            "linearBrowse": linear,
            "bundleCloseout": bundle,
        },
    }


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    out = prd339_bundle_closeout_milestone(root)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(0 if out.get("verdict") == "ready" else 20)


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
