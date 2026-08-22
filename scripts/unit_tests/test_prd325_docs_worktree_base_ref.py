#!/usr/bin/env python3
"""PRD 325 R13 — docs worktree base-ref precedence (phase 8)."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def _load_docs_worktree():
    spec = importlib.util.spec_from_file_location("docs_worktree", SCRIPT_DIR / "docs_worktree.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _init_repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "fixture@test"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)
    (root / "README").write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "README"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "init"], check=True, capture_output=True)
    return root, subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()


def test_remote_tracking_precedence_over_stale_local(tmp_path: Path) -> None:
    mod = _load_docs_worktree()
    root, local_sha = _init_repo(tmp_path)
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "clone", "--bare", str(root), str(bare)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "remote", "add", "origin", str(bare)], check=True, capture_output=True)
    (root / "README").write_text("v2-remote\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "README"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "remote tip"], check=True, capture_output=True)
    remote_sha = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    subprocess.run(["git", "-C", str(bare), "fetch", "origin", "main:main"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "reset", "--hard", local_sha], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "fetch", "origin", "main"], check=True, capture_output=True)

    payload = mod.resolve_docs_worktree_base(root, remote="origin", default="main", fetch_ok=True)
    assert payload["baseRef"] == "origin/main"
    assert payload["baseSha"] == remote_sha
    assert payload["baseSha"] != local_sha


def test_fetch_failure_degrades_with_notice(tmp_path: Path) -> None:
    mod = _load_docs_worktree()
    root, local_sha = _init_repo(tmp_path)
    payload = mod.resolve_docs_worktree_base(root, remote="origin", default="main", fetch_ok=False)
    assert payload["baseRef"] == "main"
    assert payload["baseSha"] == local_sha
    assert "fetchNotice" in payload


def test_provision_dry_run_includes_base_fields(tmp_path: Path) -> None:
    mod = _load_docs_worktree()
    root, local_sha = _init_repo(tmp_path)
    payload = mod.resolve_docs_worktree_base(root, remote="origin", default="main", fetch_ok=True)
    assert payload["baseRef"] in {"main", "origin/main", "HEAD"}
    assert payload["baseSha"] == local_sha
