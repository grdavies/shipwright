"""Python-first authoring assertions for state-root surfaces (PRD 342 R3)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

PHASE_OWNED = (
    "scripts/path_literal_guard.py",
    "scripts/shipwright_paths.py",
    "core/scripts/path_literal_guard.py",
    "core/scripts/shipwright_paths.py",
    "core/sw-reference/state-root-inventory.json",
    "core/sw-reference/path-literal-ratchet.json",
)


def _load_module(rel: str, module_name: str) -> ModuleType:
    path = REPO_ROOT / rel
    scripts = str(REPO_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def zero_shell() -> ModuleType:
    return _load_module("scripts/zero-shell-guard.py", "zero_shell_guard_state_root")


@pytest.fixture(scope="module")
def dep_import() -> ModuleType:
    return _load_module("scripts/dep-import-guard.py", "dep_import_guard_state_root")


def test_phase_owned_paths_are_not_shell_scripts() -> None:
    """No .sh/.bash/.ps1 among the state-root / path-literal surfaces."""
    shell_suffixes = {".sh", ".bash", ".ps1"}
    offenders = [
        rel
        for rel in PHASE_OWNED
        if (REPO_ROOT / rel).suffix.lower() in shell_suffixes
        or (REPO_ROOT / rel).is_file()
        and (REPO_ROOT / rel).suffix.lower() in shell_suffixes
    ]
    # Also refuse a sibling shell port for the guard.
    for stem in ("path_literal_guard", "shipwright_paths", "path-literal-guard"):
        for tree in ("scripts", "core/scripts"):
            for suffix in shell_suffixes:
                candidate = REPO_ROOT / tree / f"{stem}{suffix}"
                if candidate.is_file():
                    offenders.append(candidate.relative_to(REPO_ROOT).as_posix())
    assert offenders == [], offenders


def test_no_shell_out_from_relocated_modules(zero_shell: ModuleType) -> None:
    all_outs = zero_shell.find_shell_outs(REPO_ROOT)
    relocated = [
        hit
        for hit in all_outs
        if "shipwright_paths.py" in hit or "path_literal_guard.py" in hit
    ]
    assert relocated == [], f"shell-out from relocated modules: {relocated}"


def test_relocated_modules_third_party_deps_declared(dep_import: ModuleType) -> None:
    violations = dep_import.check(REPO_ROOT)
    relocated_violations = [
        v
        for v in violations
        if "shipwright_paths.py" in v or "path_literal_guard.py" in v
    ]
    assert relocated_violations == [], relocated_violations


def test_path_literal_guard_is_stdlib_only(dep_import: ModuleType) -> None:
    path = REPO_ROOT / "scripts" / "path_literal_guard.py"
    text = path.read_text(encoding="utf-8")
    for name in dep_import.scan_file(path):
        top = dep_import.top_level_module(name)
        if top in dep_import.STDLIB:
            continue
        if top == "_sw" or name.startswith("_sw"):
            continue
        pytest.fail(f"undeclared non-stdlib import in path_literal_guard: {name}")
    assert "shell=True" not in text
