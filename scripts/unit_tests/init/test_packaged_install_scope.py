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


def test_packaged_configure_consumer_without_schema_succeeds(tmp_path: Path) -> None:
    """Consumer repos are not Shipwright source trees — schema must come from the package."""
    configure = install_mod._load_sw_configure()
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    assert not (consumer / "core" / "sw-reference" / "config.schema.json").is_file()

    result = configure.apply_packaged_configure(consumer, accept_ci_stub=False)
    assert result["verdict"] == "pass", result
    assert (consumer / ".shipwright" / "workflow.config.json").is_file()
    assert not (consumer / "core" / "sw-reference").exists()


def test_schema_resolves_from_packaged_dist_when_consumer_empty(
    repo_root: Path, tmp_path: Path
) -> None:
    from init_profile_report import SCHEMA_REL, resolve_sw_reference_file

    consumer = tmp_path / "consumer"
    consumer.mkdir()
    fake_pkg = tmp_path / "sw-pkg"
    dist_schema = fake_pkg / "dist" / "codex" / "core" / "sw-reference"
    dist_schema.mkdir(parents=True)
    (fake_pkg / "scripts").mkdir()
    schema_src = repo_root / SCHEMA_REL
    (dist_schema / "config.schema.json").write_text(
        schema_src.read_text(encoding="utf-8"), encoding="utf-8"
    )

    found = resolve_sw_reference_file(
        consumer, SCHEMA_REL, script_dir=fake_pkg / "scripts"
    )
    assert found is not None
    assert found == dist_schema / "config.schema.json"


def test_packaged_configure_ci_stub_without_consumer_template(tmp_git_repo: Path) -> None:
    configure = install_mod._load_sw_configure()
    assert not (tmp_git_repo / "core" / "sw-reference" / "templates").exists()
    result = configure.apply_packaged_configure(tmp_git_repo, accept_ci_stub=True)
    assert result["verdict"] == "pass", result
    assert (tmp_git_repo / ".github" / "workflows" / "shipwright-ci-stub.yml").is_file()
    assert not (tmp_git_repo / "core" / "sw-reference").exists()
