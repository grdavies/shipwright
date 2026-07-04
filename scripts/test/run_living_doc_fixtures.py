#!/usr/bin/env python3
"""Living-doc INDEX commit safety fixtures (PRD 055 R7)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))

from _sw.cli import run_module_main
from _sw.vendor_paths import repo_root


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _init_fixture_repo() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="sw-living-doc-fix-"))
    (tmp / "docs" / "prds").mkdir(parents=True)
    (tmp / ".cursor").mkdir()
    (tmp / ".cursor" / "workflow.config.json").write_text(
        json.dumps({"defaultBaseBranch": "main"}), encoding="utf-8"
    )
    (tmp / "docs" / "prds" / "INDEX.md").write_text(
        "| # | Slug | PRD | Tasks | Status |\n"
        "|---|------|-----|-------|--------|\n"
        "| 055 | workflow-fidelity | [x](x) | [tasks](y) | in-progress |\n",
        encoding="utf-8",
    )
    (tmp / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(tmp, "init", "-q")
    _git(tmp, "config", "user.email", "t@t.com")
    _git(tmp, "config", "user.name", "T")
    _git(tmp, "add", ".")
    _git(tmp, "commit", "-q", "-m", "init")
    _git(tmp, "branch", "-M", "main")
    return tmp


def scenario_living_docs_reconcile_refuses_default_branch(root: Path) -> None:
    fix = _init_fixture_repo()
    state_path = fix / ".cursor" / "sw-deliver-state.json"
    state_path.write_text(
        json.dumps(
            {
                "prd_number": "055",
                "phases": {"1": {"status": "green-merged"}},
                "target": {"branch": "feat/fixture"},
            }
        ),
        encoding="utf-8",
    )
    (fix / ".cursor" / "sw-deliver-plan.json").write_text("{}", encoding="utf-8")
    scripts = root / "scripts"
    proc = subprocess.run(
        [sys.executable, str(scripts / "wave_living_docs.py"), str(fix), "reconcile", "--commit"],
        cwd=str(fix),
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        raise AssertionError(f"expected fail on main, got pass: {proc.stdout} {proc.stderr}")
    payload = proc.stdout.strip() or proc.stderr.strip()
    if "refused" not in payload and "default branch" not in payload:
        raise AssertionError(f"expected refusal message, got: {payload}")


def main() -> int:
    root = repo_root(__file__)
    failures: list[str] = []
    scenarios = [
        ("living-docs-reconcile-refuses-default-branch", scenario_living_docs_reconcile_refuses_default_branch),
    ]
    for name, fn in scenarios:
        try:
            fn(root)
            print(f"OK  {name}")
        except Exception as exc:
            print(f"FAIL {name}: {exc}")
            failures.append(name)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run_module_main(main))
