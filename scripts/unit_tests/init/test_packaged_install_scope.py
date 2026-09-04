"""Packaged install write-scope and cloned-install regression (PRD 342 R21/R22)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import install as install_mod
from init_ci_stub import STUB_WORKFLOW_REL, TEMPLATE_REL


def _snapshot_files(root: Path) -> set[str]:
    if not root.exists():
        return set()
    return {p.resolve().as_posix() for p in root.rglob("*") if p.is_file()}


def _seed_minimal_dist(dist_parent: Path) -> Path:
    """Tiny dist/cursor tree so machine mirror does not need a full generate."""
    cursor = dist_parent / "cursor"
    (cursor / "core" / "sw-reference").mkdir(parents=True)
    (cursor / "hooks").mkdir(parents=True)
    (cursor / "version.txt").write_text("2.9.0-test\n", encoding="utf-8")
    (cursor / "core" / "sw-reference" / "memory-provider-catalog.json").write_text(
        '{"providers":[]}\n',
        encoding="utf-8",
    )
    (cursor / "hooks" / "hooks.json").write_text("{}\n", encoding="utf-8")
    return cursor


def _seed_consumer_repo(repo: Path, *, shipwright_src: Path) -> None:
    """Consumer repo with CI-stub template available for consent-gated apply."""
    repo.mkdir(parents=True, exist_ok=True)
    (repo / ".git").mkdir(exist_ok=True)
    template_src = shipwright_src / TEMPLATE_REL
    template_dst = repo / TEMPLATE_REL
    template_dst.parent.mkdir(parents=True, exist_ok=True)
    if template_src.is_file():
        shutil.copy2(template_src, template_dst)
    else:
        template_dst.write_text(
            "name: shipwright-ci-stub\non:\n  pull_request:\njobs:\n  stub:\n"
            "    runs-on: ubuntu-latest\n    steps:\n"
            "      - name: Placeholder — replace with your CI steps\n"
            "        run: echo ok\n",
            encoding="utf-8",
        )


def _prepared_source_root(tmp_path: Path) -> Path:
    src_root = tmp_path / "sw-src"
    _seed_minimal_dist(src_root / "dist")
    return src_root


def test_pyproject_declares_shipwright_console(repo_root: Path) -> None:
    pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'shipwright = "sw.console:main"' in pyproject
    assert (repo_root / "sw" / "console.py").is_file()


def test_dry_run_enumerates_both_scopes_without_writes(
    repo_root: Path, tmp_path: Path
) -> None:
    src_root = _prepared_source_root(tmp_path)
    machine = tmp_path / "machine-plugin"
    consumer = tmp_path / "consumer"
    _seed_consumer_repo(consumer, shipwright_src=repo_root)

    before_machine = _snapshot_files(machine)
    before_repo = _snapshot_files(consumer)

    result = install_mod.init_packaged(
        integration="cursor",
        repo=consumer,
        dest=machine,
        source_root=src_root,
        accept_ci_stub=True,
        dry_run=True,
        install_hooks=False,
    )
    assert result["verdict"] == "pass"
    assert result["action"] == "dry-run"
    assert result["wrote"] is False

    scope = result["scope"]
    assert scope["repoScope"]["shipwright"]
    assert scope["repoScope"]["hostFiles"] == []
    assert STUB_WORKFLOW_REL.as_posix() in scope["repoScope"]["ciStub"]
    assert scope["machineScope"]["installRoot"] == str(machine.resolve())
    assert scope["machineScope"]["paths"]
    assert before_machine == _snapshot_files(machine)
    assert before_repo == _snapshot_files(consumer)


def test_real_run_touches_exactly_enumerated_set(
    repo_root: Path, tmp_path: Path
) -> None:
    src_root = _prepared_source_root(tmp_path)
    machine = tmp_path / "machine-plugin"
    consumer = tmp_path / "consumer"
    _seed_consumer_repo(consumer, shipwright_src=repo_root)

    dry = install_mod.init_packaged(
        integration="cursor",
        repo=consumer,
        dest=machine,
        source_root=src_root,
        accept_ci_stub=True,
        dry_run=True,
        install_hooks=False,
    )
    assert dry["verdict"] == "pass"
    enumerated = set(dry["scope"]["allPaths"])

    before_machine = _snapshot_files(machine)
    before_repo = _snapshot_files(consumer)

    real = install_mod.init_packaged(
        integration="cursor",
        repo=consumer,
        dest=machine,
        source_root=src_root,
        accept_ci_stub=True,
        dry_run=False,
        install_hooks=False,
    )
    assert real["verdict"] == "pass", real
    assert real["wrote"] is True

    after_machine = _snapshot_files(machine)
    after_repo = _snapshot_files(consumer)
    touched = (after_machine | after_repo) - (before_machine | before_repo)

    unexpected = sorted(touched - enumerated)
    assert not unexpected, f"writes outside dry-run scope: {unexpected}"

    missing = sorted(p for p in enumerated if not Path(p).exists())
    assert not missing, f"enumerated paths not written: {missing}"

    assert (consumer / ".shipwright" / "workflow.config.json").is_file()
    assert (consumer / STUB_WORKFLOW_REL).is_file()
    assert (machine / "hooks" / "hooks.json").is_file()


def test_cloned_repository_install_still_works(tmp_path: Path) -> None:
    """Contributor clone path: ``python3 scripts/install.py <dest>`` still succeeds (R21)."""
    src_root = _prepared_source_root(tmp_path)
    dest = tmp_path / "plugin-dest"
    dist = src_root / "dist" / "cursor"
    rc = install_mod.install(dest, src=dist, install_hooks=False)
    assert rc == 0
    assert (dest / "hooks" / "hooks.json").is_file()
    assert (dest / ".sw" / "memory-provider-catalog.json").is_file()


def test_console_init_dry_run_roundtrip(
    repo_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sw import console

    src_root = _prepared_source_root(tmp_path)
    machine = tmp_path / "machine"
    consumer = tmp_path / "consumer"
    _seed_consumer_repo(consumer, shipwright_src=repo_root)

    monkeypatch.chdir(consumer)
    rc = console.main(
        [
            "init",
            "--integration",
            "cursor",
            "--repo",
            str(consumer),
            "--dest",
            str(machine),
            "--source-root",
            str(src_root),
            "--dry-run",
        ]
    )
    assert rc == 0
