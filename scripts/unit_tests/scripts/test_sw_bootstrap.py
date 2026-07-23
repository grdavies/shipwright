"""Bootstrap CLI fixtures (PRD 078 phase 3 / TR2, R10, R12, R13)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from sw_bootstrap import normalize_script_name, resolve_helper, validate_script_name
from sw_scripts_resolve import ScriptsResolveError


def _seed_trusted_scripts(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "check-gate.py").write_text("# marker\n", encoding="utf-8")
    (path / "resolve-model-tier.py").write_text("# marker\n", encoding="utf-8")


def _snapshot_tree(root: Path) -> set[str]:
    if not root.exists():
        return set()
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def test_normalize_script_name_adds_py_suffix() -> None:
    assert normalize_script_name("wave_deliver") == "wave_deliver.py"
    assert normalize_script_name("wave_deliver.py") == "wave_deliver.py"


def test_validate_script_name_rejects_unsafe() -> None:
    for raw in ("../wave.py", "foo/bar.py", "wave.py;rm", "/etc/passwd", ""):
        name, err = validate_script_name(raw)
        assert name is None
        assert err is not None


def test_validate_script_name_accepts_safe_basenames() -> None:
    name, err = validate_script_name("wave_deliver.py")
    assert err is None
    assert name == "wave_deliver.py"


def test_print_happy_path(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()

    plugin_scripts = tmp_path / "plugin" / "scripts"
    _seed_trusted_scripts(plugin_scripts)
    helper = plugin_scripts / "wave_deliver.py"
    helper.write_text("print('ok')\n", encoding="utf-8")

    resolved = resolve_helper(consumer, "wave_deliver.py", env={"SHIPWRIGHT_SCRIPTS": str(plugin_scripts)})
    assert resolved == helper.resolve()

    proc = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[2] / "sw_bootstrap.py"),
            "--root",
            str(consumer),
            "--print",
            "wave_deliver.py",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SHIPWRIGHT_SCRIPTS": str(plugin_scripts)},
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == str(helper.resolve())


def test_exec_happy_path(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()

    plugin_scripts = tmp_path / "plugin" / "scripts"
    _seed_trusted_scripts(plugin_scripts)
    helper = plugin_scripts / "echo_helper.py"
    helper.write_text(
        "import sys\nprint(' '.join(sys.argv[1:]))\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[2] / "sw_bootstrap.py"),
            "--root",
            str(consumer),
            "echo_helper.py",
            "--",
            "hello",
            "bootstrap",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SHIPWRIGHT_SCRIPTS": str(plugin_scripts)},
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == "hello bootstrap"


def test_missing_plugin_fails_closed_without_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    app_script = consumer / "scripts" / "my_app.py"
    app_script.parent.mkdir(parents=True)
    app_script.write_text("# app\n", encoding="utf-8")
    before = _snapshot_tree(consumer)

    monkeypatch.delenv("SHIPWRIGHT_SCRIPTS", raising=False)
    monkeypatch.setattr("sw_scripts_resolve.PLUGIN_LOCAL_SCRIPTS", tmp_path / "missing-local")
    monkeypatch.setattr("sw_scripts_resolve.PLUGIN_CACHE_ROOT", tmp_path / "missing-cache")

    with pytest.raises(ScriptsResolveError, match="plugin not installed"):
        resolve_helper(consumer, "wave_deliver.py")

    proc = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[2] / "sw_bootstrap.py"),
            "--root",
            str(consumer),
            "--print",
            "wave_deliver.py",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={k: v for k, v in os.environ.items() if k != "SHIPWRIGHT_SCRIPTS"},
    )
    # When a real local plugin is installed, subprocess may resolve via plugin-local.
    # In-process monkeypatch above proves fail-closed when no plugin root exists.
    if proc.returncode == 0:
        assert proc.stdout.strip()
    else:
        assert proc.returncode == 2
        assert "plugin not installed" in proc.stderr or "does not exist" in proc.stderr
    after = _snapshot_tree(consumer)
    assert before == after


def test_cli_fail_closed_on_invalid_env(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    before = _snapshot_tree(consumer)
    proc = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[2] / "sw_bootstrap.py"),
            "--root",
            str(consumer),
            "--print",
            "wave_deliver.py",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SHIPWRIGHT_SCRIPTS": str(tmp_path / "missing-scripts-root")},
    )
    assert proc.returncode == 2
    assert "does not exist" in proc.stderr
    assert _snapshot_tree(consumer) == before


def test_cli_rejects_unsafe_name(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    proc = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[2] / "sw_bootstrap.py"),
            "--root",
            str(consumer),
            "../wave_deliver.py",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "unsafe script name" in proc.stderr
