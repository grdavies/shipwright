"""PRD 068 wave-a-paths-state unit and harness coverage (R3–R4)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PKG = "scripts/unit_tests/deliver"
_HARNESS = "harness_wave_a_paths_state.py"


def _load_harness(repo_root: Path):
    path = repo_root / _PKG / _HARNESS
    for entry in (str(repo_root / "scripts" / "test"), str(repo_root / "scripts")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    spec = importlib.util.spec_from_file_location("harness_wave_a_paths_state", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load harness {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_normalize_worktree_path_absolute(tmp_path: Path) -> None:
    from wave_state import normalize_worktree_path

    anchor = tmp_path.resolve()
    nested = anchor / "safe" / "wt"
    nested.mkdir(parents=True)
    assert normalize_worktree_path("safe/wt", anchor=anchor) == str(nested.resolve())


def test_normalize_worktree_path_rejects_escape(tmp_path: Path) -> None:
    from wave_state import WorktreePathError, normalize_worktree_path

    with pytest.raises(WorktreePathError):
        normalize_worktree_path("../outside", anchor=tmp_path)


@pytest.mark.integration
@pytest.mark.git
def test_wave_a_paths_state_harness(repo_root: Path, sw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in sw_env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(repo_root)
    assert int(_load_harness(repo_root).main()) == 0


def test_wave_a_paths_state_harness_present(repo_root: Path) -> None:
    assert (repo_root / _PKG / _HARNESS).is_file()
