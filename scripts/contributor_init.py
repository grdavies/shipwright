#!/usr/bin/env python3
"""Contributor initialization sequence and clean-environment validation (PRD 345 R9–R11)."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

EXIT_PASS = 0
EXIT_FAIL = 20
EXIT_ERROR = 2

CONTRIBUTOR_HEADING = "## Contributor path: clone this repository"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def contributor_init_steps() -> list[str]:
    """Canonical contributor steps — must match getting-started.md (PRD 345 R9)."""
    return [
        "Clone this repository (`git clone https://github.com/grdavies/shipwright`).",
        "Run `python3 scripts/install.py` (mirrors the plugin and installs the console).",
        "Run `/sw-init` in this repository to configure project settings.",
        "Reload the editor before using `sw-` commands.",
    ]


def _contributor_section(text: str) -> str:
    start = text.find(CONTRIBUTOR_HEADING)
    if start < 0:
        return ""
    rest = text[start + len(CONTRIBUTOR_HEADING) :]
    next_heading = rest.find("\n## ")
    if next_heading >= 0:
        return rest[:next_heading]
    return rest


def validate_docs(*, root: Path) -> dict[str, Any]:
    """Validate adopter/contributor distinction and contributor sequence in docs (R9, R11)."""
    findings: list[dict[str, str]] = []
    readme = root / "README.md"
    getting_started = root / "core" / "documentation" / "getting-started.md"

    if not readme.is_file():
        findings.append({"file": "README.md", "reason": "missing README"})
    if not getting_started.is_file():
        findings.append({"file": "core/documentation/getting-started.md", "reason": "missing getting-started"})

    if readme.is_file():
        text = readme.read_text(encoding="utf-8")
        if not re.search(r"\b[Aa]dopter\b", text):
            findings.append({"file": "README.md", "reason": "missing adopter path documentation"})
        if not re.search(r"\b[Cc]ontributor\b", text):
            findings.append({"file": "README.md", "reason": "missing contributor path documentation"})
        if "pip install shipwright-workflow" not in text:
            findings.append({"file": "README.md", "reason": "missing packaged adopter install command"})
        if "python3 scripts/install.py" not in text:
            findings.append({"file": "README.md", "reason": "missing contributor install.py step"})
        if "/sw-init" not in text:
            findings.append({"file": "README.md", "reason": "missing contributor /sw-init step"})

    section = ""
    if getting_started.is_file():
        gs_text = getting_started.read_text(encoding="utf-8")
        section = _contributor_section(gs_text)
        if not section:
            findings.append(
                {
                    "file": "core/documentation/getting-started.md",
                    "reason": "missing contributor path section",
                }
            )
        else:
            if "/sw-init" not in section:
                findings.append(
                    {
                        "file": "core/documentation/getting-started.md",
                        "reason": "contributor path must document /sw-init after clone",
                    }
                )
            if "python3 scripts/install.py" not in section:
                findings.append(
                    {
                        "file": "core/documentation/getting-started.md",
                        "reason": "contributor path must document install.py",
                    }
                )
            if re.search(r"shipwright\s+init\s+--integration", section):
                findings.append(
                    {
                        "file": "core/documentation/getting-started.md",
                        "reason": "contributor path must not use packaged shipwright init",
                    }
                )

    for step in contributor_init_steps():
        needle = step.split("`")[1] if "`" in step else step
        if section and needle not in section and needle not in (getting_started.read_text(encoding="utf-8") if getting_started.is_file() else ""):
            if "Reload" in step:
                continue
            findings.append(
                {
                    "file": "core/documentation/getting-started.md",
                    "reason": f"contributor step not reflected in docs: {needle}",
                }
            )

    verdict = "pass" if not findings else "doc-mismatch"
    return {"verdict": verdict, "findings": findings}


def run_clean_environment_smoke(*, root: Path) -> dict[str, Any]:
    """Exercise contributor console install in an isolated venv (PRD 345 R10)."""
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return {"verdict": "fail", "error": "pyproject.toml missing"}

    with tempfile.TemporaryDirectory(prefix="sw-contributor-smoke-") as tmp:
        venv_dir = Path(tmp) / "venv"
        proc = subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            return {
                "verdict": "fail",
                "error": "venv-create-failed",
                "stderr": proc.stderr,
            }

        pip = venv_dir / "bin" / "pip"
        python = venv_dir / "bin" / "python"
        if not pip.is_file():
            pip = venv_dir / "Scripts" / "pip.exe"
            python = venv_dir / "Scripts" / "python.exe"

        for cmd in (
            [str(pip), "install", "--upgrade", "pip"],
            [str(pip), "install", "-e", str(root)],
        ):
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                return {
                    "verdict": "fail",
                    "error": "pip-install-failed",
                    "command": cmd,
                    "stderr": proc.stderr,
                    "stdout": proc.stdout,
                }

        help_proc = subprocess.run(
            [str(python), "-m", "sw.console", "init", "--help"],
            capture_output=True,
            text=True,
        )
        if help_proc.returncode not in (0, 2):
            return {
                "verdict": "fail",
                "error": "console-init-help-failed",
                "stderr": help_proc.stderr,
                "stdout": help_proc.stdout,
            }

        import_proc = subprocess.run(
            [
                str(python),
                "-c",
                "import sw.console; from sw.console import main; raise SystemExit(main(['init','--help']))",
            ],
            capture_output=True,
            text=True,
        )
        if import_proc.returncode not in (0, 2):
            return {
                "verdict": "fail",
                "error": "console-entry-import-failed",
                "stderr": import_proc.stderr,
            }

    return {"verdict": "pass", "action": "clean-environment-smoke"}


def run_check(*, root: Path, smoke: bool = True) -> dict[str, Any]:
    doc_result = validate_docs(root=root)
    if doc_result["verdict"] != "pass":
        return doc_result
    if not smoke:
        return doc_result
    smoke_result = run_clean_environment_smoke(root=root)
    if smoke_result["verdict"] != "pass":
        return smoke_result
    return {"verdict": "pass", "docs": doc_result, "smoke": smoke_result}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate contributor init docs and clean-environment path")
    parser.add_argument("--root", type=Path, default=repo_root(), help="Repository root")
    parser.add_argument("--docs-only", action="store_true", help="Skip clean-environment smoke")
    parser.add_argument("--strict", action="store_true", help="Exit 20 when validation fails")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if not root.is_dir():
        print(json.dumps({"verdict": "error", "error": f"root not found: {root}"}), file=sys.stderr)
        return EXIT_ERROR

    result = run_check(root=root, smoke=not args.docs_only)
    print(json.dumps(result, separators=(",", ":")))
    if result["verdict"] != "pass" and args.strict:
        return EXIT_FAIL
    return EXIT_PASS


if __name__ == "__main__":
    raise SystemExit(main())
