"""Dist regeneration parity for credential-affected surfaces (PRD 080 26.5) — Z,O,M,E."""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _load_generate_all(repo_root: Path):
    path = repo_root / "scripts" / "sw-generate-all.py"
    spec = importlib.util.spec_from_file_location("sw_generate_all", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_z_credential_dist_matches_source_after_generate(repo_root: Path) -> None:
    """Z — generated dist trees match source for credential-affected surfaces."""
    gen = _load_generate_all(repo_root)
    assert gen.generate_all(repo_root) == 0
    assert gen.credential_dist_drift(repo_root) == []


def test_o_credential_dist_drift_is_detected(repo_root: Path, tmp_path: Path) -> None:
    """O — manual dist drift fails parity detection."""
    gen = _load_generate_all(repo_root)
    assert gen.generate_all(repo_root) == 0
    rel_paths = gen.credential_affected_rel_paths(repo_root)
    assert rel_paths
    target_rel = next(
        rel
        for rel in rel_paths
        if (repo_root / "core" / rel).is_file() and rel.startswith("commands/")
    )
    dist_path = repo_root / "dist" / "cursor" / target_rel
    original = dist_path.read_bytes()
    dist_path.write_bytes(original + b"\n")
    try:
        drift = gen.credential_dist_drift(repo_root)
        assert any(path.endswith(target_rel) for path in drift)
    finally:
        dist_path.write_bytes(original)


def test_m_regenerate_restores_credential_dist_parity(repo_root: Path) -> None:
    """M — sw generate --all restores credential dist parity after drift."""
    gen = _load_generate_all(repo_root)
    assert gen.generate_all(repo_root) == 0
    rel_paths = gen.credential_affected_rel_paths(repo_root)
    target_rel = next(
        rel
        for rel in rel_paths
        if (repo_root / "core" / rel).is_file() and rel.startswith("commands/")
    )
    dist_path = repo_root / "dist" / "cursor" / target_rel
    original = dist_path.read_bytes()
    dist_path.write_bytes(original + b"\n")
    assert gen.credential_dist_drift(repo_root)
    assert gen.generate_all(repo_root) == 0
    assert gen.credential_dist_drift(repo_root) == []
    dist_path.write_bytes(original)


def test_e_sw_generate_all_fails_on_residual_drift(
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E — sw-generate-all exits non-zero when credential dist drift remains."""
    gen = _load_generate_all(repo_root)
    assert gen.generate_all(repo_root) == 0
    rel_paths = gen.credential_affected_rel_paths(repo_root)
    target_rel = next(
        rel
        for rel in rel_paths
        if (repo_root / "core" / rel).is_file() and rel.startswith("commands/")
    )
    dist_path = repo_root / "dist" / "claude-code" / target_rel
    original = dist_path.read_bytes()
    dist_path.write_bytes(original + b"# drift\n")
    monkeypatch.setattr(gen, "generate_all", lambda _root=None: 0)
    try:
        assert gen.main() == 1
        assert gen.credential_dist_drift(repo_root)
    finally:
        dist_path.write_bytes(original)
