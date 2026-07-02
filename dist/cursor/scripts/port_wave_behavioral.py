#!/usr/bin/env python3
"""Materialize migration-wave behavioral harnesses and pytest entrypoints (PRD 054)."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

GIT_REF = "9f052d52"
SKIP_HARNESS_IDS = frozenset({"suite-registry-fixtures"})

TEST_TEMPLATE_W1 = '''"""Pytest port of {legacy_name} (PRD 054 W1 behavioral)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PKG = "{pytest_path}"
_HARNESS = "harness_{stem}.py"


def _load_harness(repo_root: Path):
    path = repo_root / _PKG / _HARNESS
    for entry in (str(repo_root / "scripts" / "test"), str(repo_root / "scripts")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    spec = importlib.util.spec_from_file_location("harness_{stem}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load harness {{path}}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_{stem}_behavior(repo_root: Path, sw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in sw_env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(repo_root)
    mod = _load_harness(repo_root)
    assert int(mod.main()) == 0


def test_{stem}_harness_present(repo_root: Path) -> None:
    """R16 — harness module must exist (fail-closed if port regresses)."""
    assert (repo_root / _PKG / _HARNESS).is_file()
'''

TEST_TEMPLATE_W2 = '''"""Pytest port of {legacy_name} (PRD 054 W2 behavioral)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PKG = "{pytest_path}"
_HARNESS = "harness_{stem}.py"


def _load_harness(repo_root: Path):
    path = repo_root / _PKG / _HARNESS
    for entry in (str(repo_root / "scripts" / "test"), str(repo_root / "scripts")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    spec = importlib.util.spec_from_file_location("harness_{stem}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load harness {{path}}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.git
def test_{stem}_tmp_git_repo_ready(tmp_git_repo: Path) -> None:
    """R15 — shared tmp_git_repo fixture is usable for W2 git scenarios."""
    assert (tmp_git_repo / ".git").is_dir()


@pytest.mark.git
def test_{stem}_behavior(repo_root: Path, sw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in sw_env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(repo_root)
    mod = _load_harness(repo_root)
    assert int(mod.main()) == 0


def test_{stem}_harness_present(repo_root: Path) -> None:
    """R16 — harness module must exist (fail-closed if port regresses)."""
    assert (repo_root / _PKG / _HARNESS).is_file()
'''


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _patch_harness_source(content: str) -> str:
    """Adjust legacy harness paths for scripts/unit_tests/<pkg>/ layout."""
    scripts_bootstrap = (
        "SCRIPT_DIR = Path(__file__).resolve().parent\n"
        "_SCRIPTS_ROOT = SCRIPT_DIR.parents[1]\n"
        "_TEST_DIR = _SCRIPTS_ROOT / \"test\"\n"
        "for _entry in (str(_TEST_DIR), str(_SCRIPTS_ROOT)):\n"
        "    if _entry not in sys.path:\n"
        "        sys.path.insert(0, _entry)\n"
    )
    content = re.sub(
        r"SCRIPT_DIR = Path\(__file__\)\.resolve\(\)\.parent\n"
        r"if str\(SCRIPT_DIR\.parent\) not in sys\.path:\n"
        r"    sys\.path\.insert\(0, str\(SCRIPT_DIR\.parent\)\)\n",
        scripts_bootstrap,
        content,
        count=1,
    )
    if "_TEST_DIR" not in content:
        content = content.replace(
            "SCRIPT_DIR = Path(__file__).resolve().parent\n",
            (
                "SCRIPT_DIR = Path(__file__).resolve().parent\n"
                "_SCRIPTS_ROOT = SCRIPT_DIR.parents[1]\n"
                "_TEST_DIR = _SCRIPTS_ROOT / \"test\"\n"
            ),
            1,
        )
    content = content.replace(
        'FX = SCRIPT_DIR / "fixtures"',
        'FX = _TEST_DIR / "fixtures"',
    )
    content = content.replace(
        'PY = SCRIPT_DIR.parent / "loop_autonomy.py"',
        'PY = _SCRIPTS_ROOT / "loop_autonomy.py"',
    )
    if "from _fixture_lib import repo_root" not in content:
        content = content.replace(
            "from pathlib import Path\n",
            "from pathlib import Path\n\nfrom _fixture_lib import repo_root\n",
            1,
        )
    for pattern in (
        r"^ROOT = Path\(__file__\)\.resolve\(\)\.parents\[2\]\s*$",
        r"^ROOT = SCRIPT_DIR\.parent\.parent\s*$",
        r"^ROOT = Path\(__file__\)\.resolve\(\)\.parent\.parent\.parent\s*$",
    ):
        content = re.sub(
            pattern,
            "ROOT = repo_root(__file__)",
            content,
            flags=re.MULTILINE,
        )
    return content


def _legacy_source(root: Path, legacy_rel: str) -> str:
    path = root / legacy_rel
    if path.is_file():
        return path.read_text(encoding="utf-8")
    proc = subprocess.run(
        ["git", "show", f"{GIT_REF}:{legacy_rel}"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"legacy source missing for {legacy_rel}: {proc.stderr}")
    return proc.stdout


def port_wave(root: Path, wave: str) -> int:
    waves_path = root / "core/sw-reference/migration-waves.json"
    suites = json.loads(waves_path.read_text(encoding="utf-8"))["waves"][wave]["suites"]
    template = TEST_TEMPLATE_W2 if wave == "W2" else TEST_TEMPLATE_W1
    for suite in suites:
        suite_id = suite["id"]
        legacy_rel = suite["legacy"]
        stem = suite["legacyBasename"].replace("run_", "").replace("_fixtures.py", "")
        pkg = root / suite["pytestPath"]
        pkg.mkdir(parents=True, exist_ok=True)
        if suite_id in SKIP_HARNESS_IDS:
            continue
        content = _patch_harness_source(_legacy_source(root, legacy_rel))
        legacy_bn = suite["legacyBasename"]
        content = content.replace(
            f"grep -q '{legacy_bn}' \"$ROOT/core/sw-reference/suite-registry.json\"",
            (
                f"grep -q '{suite_id}' \"$ROOT/core/sw-reference/suite-registry.json\" "
                f"&& grep -q '{suite['pytestPath']}' \"$ROOT/core/sw-reference/suite-registry.json\""
            ),
        )
        content = content.replace(
            "grep -qE 'run[-_]ux[-_]polish[-_]fixtures' \"$MANIFEST\"",
            "grep -q 'ux-polish-fixtures' \"$MANIFEST\"",
        )
        (pkg / f"harness_{stem}.py").write_text(content, encoding="utf-8")
        (pkg / f"test_{stem}.py").write_text(
            template.format(
                legacy_name=suite["legacyBasename"],
                stem=stem,
                pytest_path=suite["pytestPath"],
            ),
            encoding="utf-8",
        )
        print(f"ported {wave} {suite_id} -> {pkg.name}/harness_{stem}.py")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Port migration wave legacy suites to pytest harnesses.")
    parser.add_argument("wave", choices=["W1", "W2", "W3"])
    args = parser.parse_args(argv)
    return port_wave(repo_root(), args.wave)


if __name__ == "__main__":
    raise SystemExit(main())
