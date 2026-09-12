"""PRD 345 R9–R11 — contributor initialization sequence and clean-environment validation."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import contributor_init
import install as install_mod
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))


def test_contributor_steps_match_getting_started() -> None:
    """R9 — contributor sequence documented with install.py then /sw-init."""
    gs = (REPO_ROOT / "core/documentation/getting-started.md").read_text(encoding="utf-8")
    section = contributor_init._contributor_section(gs)
    assert "/sw-init" in section
    assert "python3 scripts/install.py" in section
    assert "shipwright init --integration" not in section


def test_contributor_steps_match_sw_configure() -> None:
    """R9 — single-source contributor steps across configure and validation."""
    import importlib.util

    path = REPO_ROOT / "scripts" / "sw-configure.py"
    spec = importlib.util.spec_from_file_location("sw_configure_contributor_test", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.contributor_init_steps() == contributor_init.contributor_init_steps()


def test_readme_documents_adopter_and_contributor_paths() -> None:
    """R11 — README distinguishes adopter and contributor installation."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "Adopter vs contributor" in readme
    assert "pip install shipwright-workflow" in readme
    assert "python3 scripts/install.py" in readme
    assert "/sw-init" in readme


def test_validate_docs_passes_on_repo() -> None:
    result = contributor_init.validate_docs(root=REPO_ROOT)
    assert result["verdict"] == "pass", result.get("findings")


def test_install_installs_console_from_source_checkout(tmp_path: Path) -> None:
    """R9 — contributor install.py installs editable console."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")

    with patch("install.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        rc = install_mod.install_console(root=root)
    assert rc == 0
    run.assert_called_once()
    assert "-e" in run.call_args.args[0]


def test_install_skips_console_when_env_set(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")

    with patch.dict("os.environ", {"SW_SKIP_CONSOLE_INSTALL": "1"}):
        with patch("install.subprocess.run") as run:
            rc = install_mod.install_console(root=root)
    assert rc == 0
    run.assert_not_called()


@pytest.mark.integration
def test_clean_environment_smoke() -> None:
    """R10 — editable console installs in an isolated venv."""
    result = contributor_init.run_clean_environment_smoke(root=REPO_ROOT)
    assert result["verdict"] == "pass", result


def test_ci_workflow_has_contributor_clean_environment_step() -> None:
    """R10 — CI validates contributor path in clean environment."""
    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "contributor-init-clean-environment" in workflow
    assert "contributor_init.py" in workflow
