#!/usr/bin/env python3
"""Template pack install / uninstall from local sources only (PRD 342 R40).

A pack is a directory or archive containing ``manifest.json``:

```json
{
  "id": "acme-pr",
  "version": "1.0.0",
  "paths": ["pr-body.md"]
}
```

Install and uninstall never modify ``core/sw-reference/templates``.
Remote registries are out of scope — only a local directory or local archive.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from template_resolve import (
    MANIFEST_NAME,
    core_templates_dir,
    packs_dir,
)

REQUIRED_MANIFEST_KEYS = ("id", "version", "paths")


class TemplatePackError(Exception):
    """Fail-closed pack validation / install error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def as_dict(self) -> dict[str, Any]:
        return {"verdict": "fail", "code": self.code, "error": self.message}


def _read_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.is_file():
        raise TemplatePackError("manifest-missing", f"pack manifest not found: {manifest_path}")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TemplatePackError("manifest-invalid", f"pack manifest is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise TemplatePackError("manifest-invalid", "pack manifest must be a JSON object")
    for key in REQUIRED_MANIFEST_KEYS:
        if key not in data:
            raise TemplatePackError(
                "manifest-incomplete",
                f"pack manifest missing required key: {key}",
            )
    pack_id = str(data["id"]).strip()
    version = str(data["version"]).strip()
    paths = data["paths"]
    if not pack_id:
        raise TemplatePackError("manifest-incomplete", "pack manifest id must be non-empty")
    if not version:
        raise TemplatePackError("manifest-incomplete", "pack manifest version must be non-empty")
    if not isinstance(paths, list) or not paths:
        raise TemplatePackError(
            "manifest-incomplete",
            "pack manifest paths must be a non-empty list of template paths",
        )
    normalized = [str(p).replace("\\", "/").lstrip("/") for p in paths]
    if any(not p or p.startswith("..") or Path(p).is_absolute() for p in normalized):
        raise TemplatePackError("manifest-paths-invalid", "pack paths must be relative template paths")
    return {"id": pack_id, "version": version, "paths": normalized}


def validate_pack_dir(pack_dir: Path) -> dict[str, Any]:
    """Validate a local pack directory; reject manifest-less packs (R40)."""
    if not pack_dir.is_dir():
        raise TemplatePackError("pack-not-dir", f"pack source is not a directory: {pack_dir}")
    manifest = _read_manifest(pack_dir / MANIFEST_NAME)
    missing = [rel for rel in manifest["paths"] if not (pack_dir / rel).is_file()]
    if missing:
        raise TemplatePackError(
            "pack-paths-missing",
            f"pack is missing declared template files: {', '.join(missing)}",
        )
    return manifest


def _extract_archive(archive: Path, dest: Path) -> Path:
    if not archive.is_file():
        raise TemplatePackError("archive-missing", f"pack archive not found: {archive}")
    if not zipfile.is_zipfile(archive):
        raise TemplatePackError(
            "archive-unsupported",
            "only local zip archives are supported for pack install",
        )
    with zipfile.ZipFile(archive, "r") as zf:
        zf.extractall(dest)
    # Prefer archive root manifest; otherwise a single top-level directory.
    if (dest / MANIFEST_NAME).is_file():
        return dest
    children = [p for p in dest.iterdir() if not p.name.startswith(".")]
    if len(children) == 1 and children[0].is_dir() and (children[0] / MANIFEST_NAME).is_file():
        return children[0]
    # Search shallowly for a manifest.
    matches = list(dest.rglob(MANIFEST_NAME))
    if len(matches) == 1:
        return matches[0].parent
    raise TemplatePackError("manifest-missing", "archive does not contain a pack manifest.json")


def _assert_not_core(root: Path, target: Path) -> None:
    core = core_templates_dir(root).resolve()
    resolved = target.resolve()
    try:
        resolved.relative_to(core)
    except ValueError:
        return
    raise TemplatePackError(
        "core-mutation-forbidden",
        "template packs must not install into or modify core/sw-reference/templates",
    )


def install_pack(root: Path, source: Path) -> dict[str, Any]:
    """Install a pack from a local directory or local zip archive (R40)."""
    source = source.resolve()
    root = root.resolve()
    packs_root = packs_dir(root)
    _assert_not_core(root, packs_root)

    with tempfile.TemporaryDirectory(prefix="sw-template-pack-") as tmp:
        tmp_path = Path(tmp)
        if source.is_dir():
            pack_dir = source
            manifest = validate_pack_dir(pack_dir)
            staging = tmp_path / "staging"
            shutil.copytree(pack_dir, staging)
            pack_dir = staging
        elif source.is_file():
            extracted = _extract_archive(source, tmp_path / "extracted")
            manifest = validate_pack_dir(extracted)
            pack_dir = extracted
        else:
            raise TemplatePackError("source-missing", f"pack source not found: {source}")

        pack_id = manifest["id"]
        dest = packs_root / pack_id
        _assert_not_core(root, dest)
        if dest.exists():
            shutil.rmtree(dest)
        packs_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(pack_dir, dest)
        # Rewrite manifest to normalized form.
        (dest / MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    return {
        "verdict": "pass",
        "action": "install",
        "id": manifest["id"],
        "version": manifest["version"],
        "paths": manifest["paths"],
        "installDir": str(packs_root / manifest["id"]),
        "coreUnmodified": True,
    }


def uninstall_pack(root: Path, pack_id: str) -> dict[str, Any]:
    """Remove an installed pack without touching core templates (R40)."""
    root = root.resolve()
    pack_id = pack_id.strip()
    if not pack_id:
        raise TemplatePackError("pack-id-missing", "pack id is required for uninstall")
    dest = packs_dir(root) / pack_id
    _assert_not_core(root, dest)
    if not dest.exists():
        raise TemplatePackError("pack-not-installed", f"pack is not installed: {pack_id}")
    shutil.rmtree(dest)
    return {
        "verdict": "pass",
        "action": "uninstall",
        "id": pack_id,
        "coreUnmodified": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None, help="Repository root")
    sub = parser.add_subparsers(dest="command", required=True)
    install_p = sub.add_parser("install", help="Install pack from local dir or zip")
    install_p.add_argument("source", type=Path, help="Local directory or zip archive")
    uninstall_p = sub.add_parser("uninstall", help="Uninstall pack by id")
    uninstall_p.add_argument("pack_id", help="Pack identifier from manifest id")
    validate_p = sub.add_parser("validate", help="Validate a local pack directory")
    validate_p.add_argument("source", type=Path, help="Local pack directory")
    args = parser.parse_args(argv)
    root = (args.root or Path.cwd()).resolve()

    try:
        if args.command == "install":
            result = install_pack(root, args.source)
        elif args.command == "uninstall":
            result = uninstall_pack(root, args.pack_id)
        elif args.command == "validate":
            manifest = validate_pack_dir(args.source.resolve())
            result = {"verdict": "pass", "action": "validate", **manifest}
        else:  # pragma: no cover
            raise TemplatePackError("unknown-command", f"unknown command: {args.command}")
    except TemplatePackError as exc:
        print(json.dumps(exc.as_dict(), indent=2))
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
