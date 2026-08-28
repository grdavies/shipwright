"""Install/mirror must replace destination symlinks instead of copying through them."""
from __future__ import annotations

from pathlib import Path

from _sw import mirror


def test_mirror_replaces_destination_dir_symlink(tmp_path: Path) -> None:
    src = tmp_path / "dist"
    (src / "scripts").mkdir(parents=True)
    (src / "scripts" / "sw-run.py").write_text("# dist\n", encoding="utf-8")

    escaped = tmp_path / "open-vddk" / "runtime" / "scripts"
    escaped.mkdir(parents=True)
    sentinel = escaped / "sentinel.txt"
    sentinel.write_text("do-not-clobber\n", encoding="utf-8")

    dest = tmp_path / "plugin"
    dest.mkdir()
    (dest / "scripts").symlink_to(escaped)

    mirror.mirror(src, dest, delete=True)

    dest_scripts = dest / "scripts"
    assert dest_scripts.is_symlink() is False
    assert dest_scripts.is_dir()
    assert (dest_scripts / "sw-run.py").read_text(encoding="utf-8") == "# dist\n"
    assert sentinel.read_text(encoding="utf-8") == "do-not-clobber\n"
    assert not (escaped / "sw-run.py").exists()


def test_mirror_replaces_nested_dir_symlink(tmp_path: Path) -> None:
    src = tmp_path / "dist"
    ref = src / "core" / "sw-reference"
    ref.mkdir(parents=True)
    (ref / "layout.md").write_text("# dist layout\n", encoding="utf-8")

    escaped = tmp_path / "shipwright-src" / "core" / "sw-reference"
    escaped.mkdir(parents=True)
    (escaped / "layout.md").write_text("# source layout\n", encoding="utf-8")

    dest = tmp_path / "plugin"
    (dest / "core").mkdir(parents=True)
    (dest / "core" / "sw-reference").symlink_to(escaped)

    mirror.mirror(src, dest, delete=True)

    dest_ref = dest / "core" / "sw-reference"
    assert dest_ref.is_symlink() is False
    assert (dest_ref / "layout.md").read_text(encoding="utf-8") == "# dist layout\n"
    assert (escaped / "layout.md").read_text(encoding="utf-8") == "# source layout\n"
