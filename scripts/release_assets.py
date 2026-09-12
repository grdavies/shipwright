#!/usr/bin/env python3
"""Release asset publication and verification for zipapp + distribution stamp (PRD 345 R5-R6)."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import build_parser, run_module_main
import build_zipapp
import capability_trust

EXIT_PASS = 0
EXIT_FAIL = 20
EXIT_ERROR = 2

DEFAULT_DEST_REL = "dist/cursor"


def repo_root(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit.resolve()
    return SCRIPT_DIR.parent


def read_version(root: Path) -> str:
    version_path = root / "scripts" / "version.py"
    if version_path.is_file():
        spec = importlib.util.spec_from_file_location(
            "scripts_version_release_assets", version_path
        )
        if spec is not None and spec.loader is not None:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            version = str(getattr(mod, "__version__", "")).strip()
            if version:
                return version
    return build_zipapp.read_version(root)


def asset_names(version: str) -> dict[str, str]:
    return {
        "versionedPyz": f"shipwright-{version}.pyz",
        "stablePyz": "shipwright.pyz",
        "distributionStamp": build_zipapp.DISTRIBUTION_STAMP_NAME,
        "manifest": f"shipwright-{version}.manifest.json",
    }


def resolve_dest(root: Path, dest: Path | None) -> Path:
    return (dest or (root / DEFAULT_DEST_REL)).resolve()


def build_release_assets(
    root: Path,
    *,
    dest_dir: Path | None = None,
    distribution_origin: str | None = None,
) -> dict[str, Any]:
    """Build versioned zipapp, distribution stamp, and manifest under the dist root (R5)."""
    dest = resolve_dest(root, dest_dir)
    payload = build_zipapp.build_archive(
        root,
        dest,
        distribution_origin=distribution_origin,
    )
    return {
        "verdict": "pass",
        "status": "built",
        "dest": dest.as_posix(),
        "version": payload.get("version"),
        "assets": publication_assets(root, dest_dir=dest),
        "build": payload,
    }


def publication_assets(
    root: Path,
    *,
    dest_dir: Path | None = None,
    version: str | None = None,
) -> list[dict[str, Any]]:
    """Return upload-ready release asset descriptors for the current version (R5)."""
    dest = resolve_dest(root, dest_dir)
    ver = version or read_version(root)
    names = asset_names(ver)
    assets: list[dict[str, Any]] = []
    for key in ("versionedPyz", "distributionStamp", "manifest"):
        path = dest / names[key]
        if path.is_file():
            assets.append(
                {
                    "kind": key,
                    "name": names[key],
                    "path": path.as_posix(),
                    "size": path.stat().st_size,
                }
            )
    return assets


def verify_release_assets(
    root: Path,
    *,
    dest_dir: Path | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    """Verify required release assets exist and pass integrity checks (R6)."""
    dest = resolve_dest(root, dest_dir)
    ver = version or read_version(root)
    names = asset_names(ver)
    findings: list[dict[str, str]] = []

    versioned_pyz = dest / names["versionedPyz"]
    stable_pyz = dest / names["stablePyz"]
    stamp_path = dest / names["distributionStamp"]
    manifest_path = dest / names["manifest"]

    required = {
        "versionedPyz": versioned_pyz,
        "distributionStamp": stamp_path,
        "manifest": manifest_path,
    }
    for label, path in required.items():
        if not path.is_file():
            findings.append(
                {
                    "asset": label,
                    "path": path.as_posix(),
                    "issue": "missing",
                }
            )

    if not stable_pyz.exists():
        findings.append(
            {
                "asset": "stablePyz",
                "path": stable_pyz.as_posix(),
                "issue": "missing",
            }
        )

    if findings:
        return {
            "verdict": "fail",
            "status": "missing-assets",
            "version": ver,
            "dest": dest.as_posix(),
            "findings": findings,
            "message": (
                f"release assets incomplete for {ver}; "
                "expected zipapp, distribution stamp, and manifest"
            ),
        }

    try:
        stamp_raw = stamp_path.read_text(encoding="utf-8")
        stamp = json.loads(stamp_raw)
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "verdict": "fail",
            "status": "stamp-corrupt",
            "version": ver,
            "dest": dest.as_posix(),
            "error": str(exc),
            "message": f"distribution stamp is unreadable: {exc}",
        }

    if not isinstance(stamp, dict):
        return {
            "verdict": "fail",
            "status": "stamp-corrupt",
            "version": ver,
            "dest": dest.as_posix(),
            "message": "distribution stamp must be a JSON object",
        }

    stamp_version = str(stamp.get("releaseVersion") or stamp.get("version") or "")
    if stamp_version != ver:
        return {
            "verdict": "fail",
            "status": "version-mismatch",
            "version": ver,
            "dest": dest.as_posix(),
            "stampVersion": stamp_version,
            "message": (
                f"distribution stamp version {stamp_version} does not match "
                f"canonical release version {ver}"
            ),
        }

    integrity = capability_trust.verify_distribution_integrity(
        versioned_pyz,
        stamp=stamp,
        stamp_path=stamp_path,
    )
    if not integrity.get("ok"):
        return {
            "verdict": "fail",
            "status": "integrity-failed",
            "version": ver,
            "dest": dest.as_posix(),
            "integrity": integrity,
            "message": integrity.get("message")
            or "release asset integrity verification failed",
        }

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "verdict": "fail",
            "status": "manifest-corrupt",
            "version": ver,
            "dest": dest.as_posix(),
            "error": str(exc),
            "message": f"release manifest is unreadable: {exc}",
        }

    modules = manifest.get("modules")
    if not isinstance(modules, list) or not modules:
        return {
            "verdict": "fail",
            "status": "manifest-invalid",
            "version": ver,
            "dest": dest.as_posix(),
            "message": "release manifest must include a non-empty modules list",
        }

    missing_modules = build_zipapp.verify_zipapp_completeness(
        versioned_pyz,
        [str(item) for item in modules],
    )
    if missing_modules:
        return {
            "verdict": "fail",
            "status": "zipapp-incomplete",
            "version": ver,
            "dest": dest.as_posix(),
            "missingModules": missing_modules,
            "message": (
                "zipapp is missing manifest-listed modules: "
                + ", ".join(missing_modules)
            ),
        }

    return {
        "verdict": "pass",
        "status": "ok",
        "version": ver,
        "dest": dest.as_posix(),
        "assets": publication_assets(root, dest_dir=dest, version=ver),
        "integrity": integrity,
        "message": f"release assets verified for {ver}",
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="release_assets.py",
        description="Build and verify zipapp + distribution stamp release assets (PRD 345)",
    )
    parser.add_argument("--root", type=Path, default=repo_root(), help="Repository root")
    parser.add_argument(
        "--dest",
        type=Path,
        default=None,
        help=f"Dist install root (default: <root>/{DEFAULT_DEST_REL})",
    )
    parser.add_argument("--version", default="", help="Override canonical release version")
    parser.add_argument(
        "--distribution-origin",
        default="",
        help="Distribution origin URL recorded in the stamp",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="Build zipapp, stamp, and manifest release assets")
    sub.add_parser("verify", help="Verify required release assets and integrity")
    sub.add_parser("manifest", help="List publication-ready asset descriptors")
    args = parser.parse_args(argv)

    root = repo_root(args.root)
    dest = resolve_dest(root, args.dest)
    version = args.version.strip() or None
    origin = args.distribution_origin.strip() or None

    if args.cmd == "build":
        result = build_release_assets(
            root,
            dest_dir=dest,
            distribution_origin=origin,
        )
        print(json.dumps(result, indent=2))
        return EXIT_PASS if result.get("verdict") == "pass" else EXIT_FAIL

    if args.cmd == "manifest":
        assets = publication_assets(root, dest_dir=dest, version=version)
        result = {
            "verdict": "pass" if assets else "fail",
            "version": version or read_version(root),
            "dest": dest.as_posix(),
            "assets": assets,
        }
        print(json.dumps(result, indent=2))
        return EXIT_PASS if assets else EXIT_FAIL

    if args.cmd == "verify":
        result = verify_release_assets(root, dest_dir=dest, version=version)
        print(json.dumps(result, indent=2))
        if result.get("verdict") == "pass":
            return EXIT_PASS
        return EXIT_FAIL

    return EXIT_ERROR


if __name__ == "__main__":
    run_module_main(main)
