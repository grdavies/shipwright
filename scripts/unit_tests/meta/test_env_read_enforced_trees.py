"""Meta parity between env-read-guard and zero-shell-guard enforced trees (PRD 080 R4)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module(repo_root: Path, rel: str, module_name: str):
    path = repo_root / rel
    scripts = str(repo_root / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_enforced_trees_match_zero_shell_guard(repo_root: Path) -> None:
    env_guard = _load_module(repo_root, "scripts/env-read-guard.py", "env_read_guard")
    zero_guard = _load_module(repo_root, "scripts/zero-shell-guard.py", "zero_shell_guard")
    assert env_guard.ENFORCED_TREES == zero_guard.ENFORCED_TREES


def test_exemptions_load_only_from_anchored_manifest(repo_root: Path) -> None:
    env_guard = _load_module(repo_root, "scripts/env-read-guard.py", "env_read_guard_meta")
    manifest_path = env_guard.manifest_path(repo_root)
    assert manifest_path.name == "env-read-exemptions.json"
    assert manifest_path.parent.as_posix().endswith("scripts/_sw")

    manifest = env_guard.load_manifest(repo_root)
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert tuple(raw["brokerPaths"]) == manifest.broker_paths
    assert frozenset(raw["allowlistedControlVariables"]) == manifest.allowlisted_control_variables

    # No alternate exemption sources under scripts/_sw.
    siblings = sorted(p.name for p in manifest_path.parent.glob("env-read-exemptions*.json"))
    assert siblings == ["env-read-exemptions.json"]
