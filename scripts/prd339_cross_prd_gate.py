#!/usr/bin/env python3
"""PRD 337 consumer gate — blocks absorb closeout until PRD 339 R37/R39 are merged and green."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

PRD_339_UNIT_ID = "339-prd-planning-store-correctness-provider-expansion"
PRD_339_R37_ACCEPTANCE_TEST = (
    "scripts/unit_tests/planning/test_prd339_list_form_absorbs_projection.py"
)
PRD_339_R39_ACCEPTANCE_TEST = (
    "scripts/unit_tests/planning/test_prd339_unit_id_index_self_heal.py"
)


def _gate_scripts_dir() -> Path:
    return Path(__file__).resolve().parent


def _repo_root(root: Path | None) -> Path:
    return root if root is not None else _gate_scripts_dir().parent


def _acceptance_test_ready(root: Path, rel_test: str) -> dict[str, Any]:
    test_path = root / rel_test
    if not test_path.is_file():
        return {
            "verdict": "blocked",
            "test": rel_test,
            "reason": "acceptance-test-missing",
        }
    # Hermetic nested pytest: clear ambient ADDOPTS / parent-session leakage so a
    # deliver-loop CI shard cannot recurse into sibling planning tests, while still
    # providing scripts/ on pythonpath for real acceptance modules.
    env = os.environ.copy()
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTEST_CURRENT_TEST", None)
    scripts_dir = str(root / "scripts")
    prev_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        scripts_dir if not prev_pp else scripts_dir + os.pathsep + prev_pp
    )
    with tempfile.TemporaryDirectory(prefix="prd339-gate-pytest-") as td:
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


def prd339_absorb_acceptance_milestone(root: Path | None = None) -> dict[str, Any]:
    """Return ready when PRD 339 R37 and R39 acceptance tests exist and pass."""
    repo = _repo_root(root)
    r37 = _acceptance_test_ready(repo, PRD_339_R37_ACCEPTANCE_TEST)
    r39 = _acceptance_test_ready(repo, PRD_339_R39_ACCEPTANCE_TEST)
    blocked = [item for item in (r37, r39) if item.get("verdict") != "ready"]
    if blocked:
        return {
            "verdict": "blocked",
            "action": "prd339-cross-prd-absorb-gate",
            "cause": "prd-339-r37-r39-not-merged-green",
            "prd339UnitId": PRD_339_UNIT_ID,
            "requirements": ["R37", "R39"],
            "blocked": blocked,
            "resumeCommand": (
                "merge and green PRD 339 R37 (list-form absorbs projection) and "
                "R39 (unit-id marker reuse refusal + index self-heal), then retry "
                "python3 scripts/planning_store.py close-delivery-units "
                "--prd-unit 337-prd-workflow-runtime-autonomy-lifecycle"
            ),
        }
    return {
        "verdict": "ready",
        "action": "prd339-cross-prd-absorb-gate",
        "prd339UnitId": PRD_339_UNIT_ID,
        "requirements": ["R37", "R39"],
        "checks": [r37, r39],
    }


def main() -> None:
    import json

    root = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    out = prd339_absorb_acceptance_milestone(root)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(0 if out.get("verdict") == "ready" else 20)


if __name__ == "__main__":
    main()
