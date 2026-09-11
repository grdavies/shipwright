"""PRD 338 R29 — Claude Code installer mirror/refresh parity."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = SCRIPT_DIR.parent
for entry in (str(REPO_ROOT), str(SCRIPT_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from sw.generate import generate_platform  # noqa: E402


def _load_install():
    path = SCRIPT_DIR / "install.py"
    spec = importlib.util.spec_from_file_location("sw_install_prd338", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed_minimal_claude_dist(dist: Path) -> None:
    (dist / ".claude-plugin").mkdir(parents=True)
    (dist / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "shipwright", "version": "2.10.0-test"}) + "\n",
        encoding="utf-8",
    )
    (dist / "version.txt").write_text("2.10.0-test\n", encoding="utf-8")
    (dist / "hooks").mkdir(parents=True)
    (dist / "hooks" / "hooks.json").write_text("{}\n", encoding="utf-8")
    (dist / "core" / "sw-reference").mkdir(parents=True)
    (dist / "core" / "sw-reference" / "memory-provider-catalog.json").write_text(
        '{"providers":[]}\n',
        encoding="utf-8",
    )
    (dist / "commands").mkdir(parents=True)
    (dist / "commands" / "sw-ship.md").write_text("# ship\n", encoding="utf-8")


def _file_snapshot(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file()
    }


@pytest.fixture
def install_mod():
    return _load_install()


@pytest.fixture
def claude_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist" / "claude-code"
    _seed_minimal_claude_dist(dist)
    return dist


def test_claude_installer_mirror_refresh_clean_install(
    install_mod, claude_dist: Path, tmp_path: Path
) -> None:
    """O — clean install copies managed files to the machine destination."""
    dest = tmp_path / "machine"
    rc = install_mod.install(dest, src=claude_dist, integration="claude-code", install_hooks=False)
    assert rc == 0
    assert (dest / "version.txt").read_text(encoding="utf-8") == "2.10.0-test\n"
    assert (dest / "commands" / "sw-ship.md").is_file()
    assert (dest / ".sw" / "memory-provider-catalog.json").is_file()


def test_claude_installer_mirror_refresh_idempotent(
    install_mod, claude_dist: Path, tmp_path: Path
) -> None:
    """S — repeated refresh with unchanged source is a no-op."""
    dest = tmp_path / "machine"
    assert install_mod.install(dest, src=claude_dist, integration="claude-code", install_hooks=False) == 0
    before = _file_snapshot(dest)
    assert install_mod.install(dest, src=claude_dist, integration="claude-code", install_hooks=False) == 0
    after = _file_snapshot(dest)
    assert before == after


def test_claude_installer_mirror_refresh_updates_changed_files(
    install_mod, claude_dist: Path, tmp_path: Path
) -> None:
    """M — changed managed files refresh on the destination."""
    dest = tmp_path / "machine"
    assert install_mod.install(dest, src=claude_dist, integration="claude-code", install_hooks=False) == 0
    claude_dist.joinpath("commands", "sw-ship.md").write_text("# ship v2\n", encoding="utf-8")
    assert install_mod.install(dest, src=claude_dist, integration="claude-code", install_hooks=False) == 0
    assert dest.joinpath("commands", "sw-ship.md").read_text(encoding="utf-8") == "# ship v2\n"


def test_claude_installer_mirror_refresh_removes_stale_managed_files(
    install_mod, claude_dist: Path, tmp_path: Path
) -> None:
    """B — stale managed mirrors are removed on refresh."""
    dest = tmp_path / "machine"
    assert install_mod.install(dest, src=claude_dist, integration="claude-code", install_hooks=False) == 0
    stale = dest / "commands" / "retired.md"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("old\n", encoding="utf-8")
    assert install_mod.install(dest, src=claude_dist, integration="claude-code", install_hooks=False) == 0
    assert not stale.exists()


def test_claude_installer_mirror_refresh_preserves_user_owned(
    install_mod, claude_dist: Path, tmp_path: Path
) -> None:
    """User-owned files under ``.sw/local/`` survive managed refresh."""
    dest = tmp_path / "machine"
    assert install_mod.install(dest, src=claude_dist, integration="claude-code", install_hooks=False) == 0
    user_file = dest / ".sw" / "local" / "operator-notes.txt"
    user_file.parent.mkdir(parents=True, exist_ok=True)
    user_file.write_text("keep me\n", encoding="utf-8")
    claude_dist.joinpath("version.txt").write_text("2.10.1-test\n", encoding="utf-8")
    assert install_mod.install(dest, src=claude_dist, integration="claude-code", install_hooks=False) == 0
    assert user_file.read_text(encoding="utf-8") == "keep me\n"
    assert dest.joinpath("version.txt").read_text(encoding="utf-8") == "2.10.1-test\n"


def test_claude_installer_empty_source_fails(install_mod, tmp_path: Path) -> None:
    """Z — missing integration dist fails closed."""
    dest = tmp_path / "machine"
    missing = tmp_path / "missing-dist"
    rc = install_mod.install(dest, src=missing, integration="claude-code", install_hooks=False)
    assert rc == 1
    assert not dest.exists()


def test_claude_installer_entrypoint_emitted(repo_root: Path, tmp_path: Path) -> None:
    """I — Claude Code dist registers an install-root-relative installer entrypoint."""
    out = tmp_path / "dist"
    plugin_root = generate_platform("claude-code", dest_root=out)
    installer = plugin_root / "scripts" / "install.py"
    assert installer.is_file()
    text = installer.read_text(encoding="utf-8")
    assert "claude-code" in text
    assert "install.py" in text
    manifest = json.loads((plugin_root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest.get("installer") == "./scripts/install.py"


def test_claude_installer_dist_source_from_packaged_root(
    install_mod, claude_dist: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Packaged install roots resolve as their own dist source."""
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(claude_dist))
    resolved = install_mod.dist_source_for("claude-code")
    assert resolved.resolve() == claude_dist.resolve()
