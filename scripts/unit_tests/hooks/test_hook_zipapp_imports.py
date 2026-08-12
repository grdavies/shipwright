"""PRD 091 — guardrail hooks must import scripts from zipapp-only plugin installs."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

CORE_HOOKS = Path(__file__).resolve().parents[3] / "core" / "hooks"
SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def _load_hook_module(name: str):
    path = CORE_HOOKS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    if str(CORE_HOOKS) not in sys.path:
        sys.path.insert(0, str(CORE_HOOKS))
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _scripts_tree_is_shim_only(scripts_dir: Path) -> bool:
    if not scripts_dir.is_dir():
        return True
    files = [p for p in scripts_dir.rglob("*") if p.is_file()]
    return files == [scripts_dir / "sw-run.py"]


def _generate_platform_dist(repo_root: Path, out_root: Path, platform: str) -> Path:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "sw",
            "generate",
            platform,
            "--dest",
            str(out_root),
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return out_root / platform


@pytest.fixture(scope="module")
def cursor_zipapp_plugin(repo_root: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("zipapp-hook-dist")
    plugin = _generate_platform_dist(repo_root, out, "cursor")
    assert _scripts_tree_is_shim_only(plugin / "scripts")
    assert (plugin / "shipwright.pyz").is_file()
    return plugin


def test_plugin_scripts_sys_path_entries_prefer_pyz(cursor_zipapp_plugin: Path) -> None:
    sw_hook_util = _load_hook_module("sw_hook_util")
    entries = sw_hook_util.plugin_scripts_sys_path_entries(cursor_zipapp_plugin)
    pyz = sw_hook_util.resolve_plugin_pyz(cursor_zipapp_plugin)
    assert pyz is not None
    assert entries[0] == str(pyz)
    assert str((cursor_zipapp_plugin / "scripts").resolve()) in entries


def test_pythonpath_for_plugin_includes_pyz(cursor_zipapp_plugin: Path) -> None:
    guardrail_core = _load_hook_module("guardrail_core")
    sw_hook_util = _load_hook_module("sw_hook_util")
    pyz = sw_hook_util.resolve_plugin_pyz(cursor_zipapp_plugin)
    assert pyz is not None
    pythonpath = guardrail_core._pythonpath_for_plugin(cursor_zipapp_plugin)
    parts = pythonpath.split(os.pathsep)
    assert str(pyz) in parts
    assert parts.index(str(pyz)) < parts.index(str((cursor_zipapp_plugin / "scripts").resolve()))


def test_validate_hook_provider_zipapp_only_no_repo_scripts(
    cursor_zipapp_plugin: Path, repo_root: Path
) -> None:
    """Clean subprocess: shim-only scripts/ + no workspace scripts on path must still import."""
    code = textwrap.dedent(
        f"""
        import sys
        from pathlib import Path

        plugin = Path({str(cursor_zipapp_plugin)!r})
        hooks = plugin / "core" / "hooks"
        # Intentionally omit repo scripts/ — zipapp must be enough.
        sys.path.insert(0, str(hooks))
        from sw_hook_util import ensure_plugin_scripts_importable, validate_hook_provider

        ensure_plugin_scripts_importable(plugin)
        ok = validate_hook_provider(plugin, "in-repo")
        print("ok" if ok else "fail")
        """
    )
    env = os.environ.copy()
    # Drop ambient PYTHONPATH that might point at the self-repo scripts tree.
    env.pop("PYTHONPATH", None)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert proc.stdout.strip() == "ok"


def test_submit_guard_zipapp_plugin_without_cwd_no_module_error(
    cursor_zipapp_plugin: Path, repo_root: Path, tmp_path: Path
) -> None:
    """Regression: beforeSubmitPrompt payload often omits cwd; must not ModuleNotFoundError."""
    workspace = tmp_path / "consumer"
    cursor = workspace / ".cursor"
    cursor.mkdir(parents=True)
    (cursor / "workflow.config.json").write_text(
        json.dumps(
            {
                "memory": {
                    "provider": "in-repo",
                    "project": "zipapp-hook-test",
                    "guardrails": {"enforceBeforeSubmit": True},
                }
            }
        ),
        encoding="utf-8",
    )
    (cursor / "sw-memory" / "rules").mkdir(parents=True)
    (cursor / "sw-memory" / "memories").mkdir(parents=True)

    code = textwrap.dedent(
        f"""
        import sys
        from pathlib import Path

        plugin = Path({str(cursor_zipapp_plugin)!r})
        workspace = Path({str(workspace)!r})
        sys.path.insert(0, str(plugin / "core" / "hooks"))
        sys.path.insert(0, str(plugin / "platforms" / "cursor"))
        from hook_adapter import run_before_submit_from_payload

        # No cwd — this is the failing Cursor payload shape after PRD 091.
        result = run_before_submit_from_payload(
            plugin,
            {{"workspace_roots": [str(workspace)]}},
        )
        print(result.allow)
        print(result.message)
        """
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    lines = proc.stdout.strip().splitlines()
    assert lines, proc.stdout
    message = "\n".join(lines[1:]) if len(lines) > 1 else ""
    assert "memory_provider_register" not in message
    assert "No module named" not in message
