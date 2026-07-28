"""AST env-read guard fixtures (PRD 080 phase 14 / R4)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_guard(repo_root: Path):
    path = repo_root / "scripts" / "env-read-guard.py"
    scripts = str(repo_root / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("env_read_guard", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_fixture(root: Path, rel: str, source: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _manifest_for(root: Path) -> object:
    guard = _load_guard(root)
    return guard.load_manifest(root)


def test_clean_module_has_no_findings(tmp_path: Path, repo_root: Path) -> None:
    guard = _load_guard(repo_root)
    manifest = _manifest_for(repo_root)
    rel = "scripts/fixture_env_read/clean_module.py"
    path = _write_fixture(
        tmp_path,
        rel,
        "def value() -> str:\n    return 'ok'\n",
    )
    assert guard.scan_file(path, manifest=manifest, rel_posix=rel) == []


def test_direct_getenv_is_flagged(tmp_path: Path, repo_root: Path) -> None:
    guard = _load_guard(repo_root)
    manifest = _manifest_for(repo_root)
    rel = "scripts/fixture_env_read/direct_getenv.py"
    path = _write_fixture(
        tmp_path,
        rel,
        "import os\n\ndef token() -> str | None:\n    return os.getenv('GITHUB_TOKEN')\n",
    )
    findings = guard.scan_file(path, manifest=manifest, rel_posix=rel)
    assert len(findings) == 1
    assert findings[0].kind == "os-getenv"


def test_evasion_forms_are_flagged(tmp_path: Path, repo_root: Path) -> None:
    guard = _load_guard(repo_root)
    manifest = _manifest_for(repo_root)
    cases = {
        "dynamic_get": (
            "import os\nkey = 'GITHUB_TOKEN'\nval = os.environ.get(key)\n",
            "environ-get-dynamic",
        ),
        "subscript": (
            "import os\nval = os.environ['GITHUB_TOKEN']\n",
            "environ-subscript",
        ),
        "dict_copy": (
            "import os\npayload = dict(os.environ)\n",
            "dict-environ",
        ),
        "unpack": (
            "import os\npayload = {**os.environ, 'X': '1'}\n",
            "dict-unpack-environ",
        ),
        "alias": (
            "import os\nenv = os.environ\nval = env.get('GITHUB_TOKEN')\n",
            "environ-get",
        ),
        "reexport": (
            "from os import environ as proc_env\nval = proc_env.get('GITHUB_TOKEN')\n",
            "environ-get",
        ),
        "subprocess_copy": (
            "import os\nimport subprocess\nsubprocess.run(['true'], env=os.environ.copy())\n",
            "subprocess-env-copy",
        ),
        "copy_module": (
            "import copy\nimport os\npayload = copy.copy(os.environ)\n",
            "copy-environ",
        ),
    }
    for name, (source, expected_kind) in cases.items():
        rel = f"scripts/fixture_env_read/evasion_{name}.py"
        path = _write_fixture(tmp_path, rel, source)
        findings = guard.scan_file(path, manifest=manifest, rel_posix=rel)
        assert findings, f"expected finding for {name}"
        assert any(f.kind == expected_kind for f in findings), (
            f"{name}: expected {expected_kind}, got {[f.kind for f in findings]}"
        )


def test_allowlisted_control_variable_is_permitted(tmp_path: Path, repo_root: Path) -> None:
    guard = _load_guard(repo_root)
    manifest = _manifest_for(repo_root)
    rel = "scripts/fixture_env_read/allowlisted.py"
    path = _write_fixture(
        tmp_path,
        rel,
        "import os\nmode = os.environ.get('SW_PHASE_MODE')\n",
    )
    assert guard.scan_file(path, manifest=manifest, rel_posix=rel) == []


def test_broker_path_is_exempt(tmp_path: Path, repo_root: Path) -> None:
    guard = _load_guard(repo_root)
    manifest = _manifest_for(repo_root)
    rel = "scripts/credentials/fixture_broker_read.py"
    path = _write_fixture(
        tmp_path,
        rel,
        "import os\nval = os.getenv('GITHUB_TOKEN')\n",
    )
    assert guard.scan_file(path, manifest=manifest, rel_posix=rel) == []


def test_warn_mode_returns_zero_despite_findings(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    guard = _load_guard(repo_root)
    monkeypatch.delenv("SW_ENV_READ_MODE", raising=False)
    monkeypatch.setattr(
        "credentials.migration_release_gate.env_read_enforcement_mode",
        lambda _root=None: "warn",
    )
    assert guard.main(["--mode", "warn"]) == 0


def test_default_mode_flips_to_fail_when_migration_gate_open(
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = _load_guard(repo_root)
    monkeypatch.delenv("SW_ENV_READ_MODE", raising=False)
    monkeypatch.setattr(
        "credentials.migration_release_gate.env_read_enforcement_mode",
        lambda _root=None: "fail",
    )
    assert guard.mode() == "fail"


def test_default_mode_stays_warn_when_migration_gate_closed(
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = _load_guard(repo_root)
    monkeypatch.delenv("SW_ENV_READ_MODE", raising=False)
    monkeypatch.setattr(
        "credentials.migration_release_gate.env_read_enforcement_mode",
        lambda _root=None: "warn",
    )
    assert guard.mode() == "warn"


def test_manifest_is_single_anchored_source(repo_root: Path) -> None:
    guard = _load_guard(repo_root)
    manifest_path = guard.manifest_path(repo_root)
    assert manifest_path == repo_root / "scripts" / "_sw" / "env-read-exemptions.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "brokerPaths" in payload
    assert "allowlistedControlVariables" in payload
    assert payload["brokerPaths"]
