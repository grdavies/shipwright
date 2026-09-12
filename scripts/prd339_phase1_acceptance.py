#!/usr/bin/env python3
"""PRD 339 phase-1 correctness gate — independently shippable R35/R36/R38 acceptance."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

PRD_339_UNIT_ID = "339-prd-planning-store-correctness-provider-expansion"
PRD_339_R35_ACCEPTANCE_TEST = "scripts/unit_tests/planning/test_prd339_amendment_guard.py"
PRD_339_R36_ACCEPTANCE_TEST = "scripts/unit_tests/planning/test_prd339_secret_scan_email.py"
PRD_339_R38_ACCEPTANCE_TEST = "scripts/unit_tests/deliver/test_prd339_issue_source.py"
PRD_339_PHASE1_ACCEPTANCE_TEST = "scripts/unit_tests/planning/test_prd339_phase1_acceptance.py"


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
    with tempfile.TemporaryDirectory(prefix="prd339-phase1-pytest-") as td:
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


def prd339_phase1_correctness_milestone(root: Path | None = None) -> dict[str, Any]:
    """Return ready when PRD 339 R35/R36/R38 acceptance scenarios are green."""
    repo = _repo_root(root)
    r35 = _acceptance_test_ready(repo, PRD_339_R35_ACCEPTANCE_TEST)
    r36 = _acceptance_test_ready(repo, PRD_339_R36_ACCEPTANCE_TEST)
    r38 = _acceptance_test_ready(repo, PRD_339_R38_ACCEPTANCE_TEST)
    blocked = [item for item in (r35, r36, r38) if item.get("verdict") != "ready"]
    if blocked:
        return {
            "verdict": "blocked",
            "action": "prd339-phase1-correctness-gate",
            "cause": "prd-339-phase1-not-merged-green",
            "prd339UnitId": PRD_339_UNIT_ID,
            "requirements": ["R35", "R36", "R38"],
            "blocked": blocked,
            "resumeCommand": (
                "merge and green PRD 339 R35 (amendment guard), R36 (EMAIL secret scan), "
                "and R38 (issue-source disambiguation), then retry "
                f"python3 scripts/prd339_phase1_acceptance.py {repo}"
            ),
        }
    return {
        "verdict": "ready",
        "action": "prd339-phase1-correctness-gate",
        "prd339UnitId": PRD_339_UNIT_ID,
        "requirements": ["R35", "R36", "R38"],
        "checks": [r35, r36, r38],
    }


def main() -> None:
    import json

    root = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    out = prd339_phase1_correctness_milestone(root)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(0 if out.get("verdict") == "ready" else 20)


if __name__ == "__main__":
    main()
