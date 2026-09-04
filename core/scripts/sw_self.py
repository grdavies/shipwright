#!/usr/bin/env python3
"""``shipwright self check`` / ``self upgrade`` (PRD 342 R20).

Resolves upgrade manifests from the distribution origin recorded in the
per-artifact version stamp. An unreachable origin yields a *degraded* check
rather than "up to date". Upgrade refuses on integrity failure naming
corruption in transit or on disk (R23) via the single mechanism in
``capability_trust`` (R51).
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import build_parser, run_module_main
import build_zipapp
import capability_trust

DEFAULT_ORIGIN = build_zipapp.DEFAULT_DISTRIBUTION_ORIGIN
STAMP_NAME = build_zipapp.DISTRIBUTION_STAMP_NAME

JsonFetcher = Callable[[str], Any]
BytesFetcher = Callable[[str], bytes]


def repo_root() -> Path:
    return SCRIPT_DIR.parent


def load_installed_stamp(
    *,
    stamp_path: Path | None = None,
    pyz_path: Path | None = None,
    install_root: Path | None = None,
) -> dict[str, Any]:
    """Load the installed distribution stamp from sidecar, pyz, or install root."""
    if stamp_path and stamp_path.is_file():
        data = json.loads(stamp_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    if pyz_path and pyz_path.is_file():
        embedded = build_zipapp.read_distribution_stamp_from_pyz(pyz_path)
        if embedded:
            return dict(embedded)
    root = install_root or repo_root()
    for candidate in (
        root / STAMP_NAME,
        root / "dist" / STAMP_NAME,
        root / "dist" / "cursor" / STAMP_NAME,
    ):
        if candidate.is_file():
            data = json.loads(candidate.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    for pyz in (
        root / "dist" / "shipwright.pyz",
        root / "dist" / "cursor" / "shipwright.pyz",
    ):
        if pyz.is_file():
            embedded = build_zipapp.read_distribution_stamp_from_pyz(pyz)
            if embedded:
                return dict(embedded)
    version_path = root / "version.txt"
    version = (
        version_path.read_text(encoding="utf-8").strip()
        if version_path.is_file()
        else "0.0.0"
    )
    return {
        "schemaVersion": 1,
        "releaseVersion": version,
        "distributionOrigin": DEFAULT_ORIGIN,
        "integrity": {"algorithm": "sha256", "mechanism": "sha256-digest"},
        "degraded": True,
        "note": "no distribution stamp found; using version.txt + default origin",
    }


def origin_from_stamp(stamp: dict[str, Any]) -> str:
    return str(stamp.get("distributionOrigin") or DEFAULT_ORIGIN).rstrip("/")


def installed_version(stamp: dict[str, Any]) -> str:
    return str(stamp.get("releaseVersion") or stamp.get("version") or "0.0.0")


def urlopen_json(url: str, *, timeout: float = 15.0) -> Any:
    req = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "shipwright-self"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def urlopen_bytes(url: str, *, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "shipwright-self"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def resolve_available_from_origin(
    origin: str,
    *,
    fetcher: JsonFetcher | None = None,
) -> dict[str, Any]:
    """Resolve available release metadata from the distribution origin."""
    fetch_json = fetcher or urlopen_json
    origin = origin.rstrip("/")
    errors: list[str] = []

    if origin.endswith(".json"):
        try:
            manifest = fetch_json(origin)
            version = str(
                (manifest or {}).get("version")
                or (manifest or {}).get("releaseVersion")
                or ""
            )
            return {
                "status": "ok",
                "availableVersion": version,
                "manifest": manifest,
                "manifestUrl": origin,
            }
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            json.JSONDecodeError,
            OSError,
            TypeError,
        ) as exc:
            return {"status": "unreachable", "error": str(exc), "origin": origin}

    if origin.endswith("/releases") or "/releases" in origin:
        api = origin
        if "api.github.com" not in api:
            parts = origin.split("github.com/", 1)
            if len(parts) == 2:
                rest = parts[1].removesuffix("/releases").strip("/")
                api = f"https://api.github.com/repos/{rest}/releases/latest"
        try:
            release = fetch_json(api)
            tag = str((release or {}).get("tag_name") or "").lstrip("v")
            assets = (release or {}).get("assets") if isinstance(release, dict) else []
            stamp_url = None
            pyz_url = None
            if isinstance(assets, list):
                for asset in assets:
                    if not isinstance(asset, dict):
                        continue
                    name = str(asset.get("name") or "")
                    url = asset.get("browser_download_url")
                    if name == STAMP_NAME:
                        stamp_url = url
                    if name.endswith(".pyz") and "shipwright" in name:
                        pyz_url = url
            return {
                "status": "ok",
                "availableVersion": tag,
                "release": release,
                "stampUrl": stamp_url,
                "artifactUrl": pyz_url,
                "apiUrl": api,
            }
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            json.JSONDecodeError,
            OSError,
            TypeError,
        ) as exc:
            errors.append(str(exc))

    return {
        "status": "unreachable",
        "error": "; ".join(errors) if errors else "origin did not yield a resolvable release",
        "origin": origin,
    }


def compare_versions(installed: str, available: str) -> str:
    """Return newer|same|older|unknown using simple dotted-int comparison."""

    def parts(v: str) -> list[int] | None:
        try:
            return [int(p) for p in v.split(".")]
        except ValueError:
            return None

    left, right = parts(installed), parts(available)
    if left is None or right is None:
        return "same" if installed == available else "unknown"
    n = max(len(left), len(right))
    left = left + [0] * (n - len(left))
    right = right + [0] * (n - len(right))
    if left < right:
        return "newer"
    if left > right:
        return "older"
    return "same"


def self_check(
    *,
    stamp: dict[str, Any] | None = None,
    fetcher: JsonFetcher | None = None,
    install_root: Path | None = None,
) -> dict[str, Any]:
    stamp = stamp or load_installed_stamp(install_root=install_root)
    origin = origin_from_stamp(stamp)
    installed = installed_version(stamp)
    available = resolve_available_from_origin(origin, fetcher=fetcher)

    if available.get("status") != "ok":
        return {
            "verdict": "degraded",
            "status": "degraded",
            "installedVersion": installed,
            "availableVersion": None,
            "distributionOrigin": origin,
            "updateAvailable": False,
            "message": (
                "distribution origin unreachable; check is degraded "
                "(not reported as up to date)"
            ),
            "error": available.get("error"),
        }

    avail_ver = str(available.get("availableVersion") or "")
    relation = compare_versions(installed, avail_ver)
    update_available = relation == "newer"
    if update_available:
        message = f"update available: {installed} → {avail_ver}"
    elif relation == "same":
        message = f"installed {installed} matches available {avail_ver}"
    else:
        message = f"installed {installed}; available {avail_ver} ({relation})"
    return {
        "verdict": "pass",
        "status": "ok",
        "installedVersion": installed,
        "availableVersion": avail_ver,
        "distributionOrigin": origin,
        "updateAvailable": update_available,
        "relation": relation,
        "message": message,
        "available": available,
    }


def self_upgrade(
    *,
    stamp: dict[str, Any] | None = None,
    fetcher: JsonFetcher | None = None,
    fetch_bytes: BytesFetcher | None = None,
    install_root: Path | None = None,
    dest_dir: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    check = self_check(stamp=stamp, fetcher=fetcher, install_root=install_root)
    if check.get("status") == "degraded":
        return {
            "verdict": "fail",
            "status": "degraded",
            "upgradeApplied": False,
            "message": check.get("message"),
            "check": check,
        }
    if not check.get("updateAvailable"):
        return {
            "verdict": "pass",
            "status": "noop",
            "upgradeApplied": False,
            "message": check.get("message"),
            "check": check,
        }

    available = check.get("available") or {}
    artifact_url = available.get("artifactUrl")
    stamp_url = available.get("stampUrl")
    if not artifact_url or not stamp_url:
        return {
            "verdict": "fail",
            "status": "missing-assets",
            "upgradeApplied": False,
            "message": "release is missing shipwright artifact or distribution stamp assets",
            "check": check,
        }

    get_bytes = fetch_bytes or urlopen_bytes
    try:
        artifact_bytes = get_bytes(str(artifact_url))
        stamp_bytes = get_bytes(str(stamp_url))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        return {
            "verdict": "fail",
            "status": "download-failed",
            "upgradeApplied": False,
            "message": f"failed to download upgrade assets: {exc}",
            "check": check,
        }

    try:
        remote_stamp = json.loads(stamp_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {
            "verdict": "fail",
            "status": "stamp-corrupt",
            "upgradeApplied": False,
            "message": capability_trust.CORRUPTION_REFUSAL,
            "error": str(exc),
            "check": check,
        }

    dest = dest_dir or (install_root or repo_root()) / "dist"
    dest.mkdir(parents=True, exist_ok=True)
    integrity: dict[str, Any]
    with tempfile.TemporaryDirectory(prefix="sw-self-upgrade-") as tmp:
        tmp_path = Path(tmp)
        avail_ver = str(check.get("availableVersion") or "upgrade")
        artifact_path = tmp_path / f"shipwright-{avail_ver}.pyz"
        stamp_path = tmp_path / STAMP_NAME
        artifact_path.write_bytes(artifact_bytes)
        stamp_path.write_bytes(stamp_bytes)

        integrity = capability_trust.verify_distribution_integrity(
            artifact_path,
            stamp=remote_stamp if isinstance(remote_stamp, dict) else None,
            stamp_path=stamp_path,
        )
        if not integrity.get("ok"):
            return {
                "verdict": "fail",
                "status": "integrity-failed",
                "upgradeApplied": False,
                "message": integrity.get("message") or capability_trust.CORRUPTION_REFUSAL,
                "integrity": integrity,
                "check": check,
            }

        if dry_run:
            return {
                "verdict": "pass",
                "status": "dry-run",
                "upgradeApplied": False,
                "message": f"integrity ok; would install {avail_ver} into {dest}",
                "integrity": integrity,
                "check": check,
            }

        final_artifact = dest / f"shipwright-{avail_ver}.pyz"
        final_stamp = dest / STAMP_NAME
        shutil.copy2(artifact_path, final_artifact)
        shutil.copy2(stamp_path, final_stamp)
        stable = dest / "shipwright.pyz"
        if stable.exists() or stable.is_symlink():
            stable.unlink()
        stable.symlink_to(final_artifact.name)

    return {
        "verdict": "pass",
        "status": "upgraded",
        "upgradeApplied": True,
        "installedVersion": check.get("availableVersion"),
        "previousVersion": check.get("installedVersion"),
        "destination": str(dest),
        "integrity": integrity,
        "check": check,
        "message": (
            f"upgraded {check.get('installedVersion')} → {check.get('availableVersion')}"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="sw_self.py",
        description="shipwright self check / self upgrade (R20)",
    )
    parser.add_argument("--install-root", default="", help="Installed package / repo root")
    parser.add_argument("--stamp", default="", help="Path to distribution stamp JSON")
    parser.add_argument("--pyz", default="", help="Path to installed shipwright.pyz")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="Report installed vs available (degraded if origin unreachable)")
    up = sub.add_parser(
        "upgrade", help="Apply update from distribution origin after integrity check"
    )
    up.add_argument("--dest", default="", help="Directory to write upgraded artifact into")
    up.add_argument("--dry-run", action="store_true", help="Download + verify without installing")
    args = parser.parse_args(argv)

    install_root = Path(args.install_root) if args.install_root else None
    stamp = load_installed_stamp(
        stamp_path=Path(args.stamp) if args.stamp else None,
        pyz_path=Path(args.pyz) if args.pyz else None,
        install_root=install_root,
    )

    if args.cmd == "check":
        result = self_check(stamp=stamp, install_root=install_root)
        print(json.dumps(result, indent=2))
        if result.get("status") == "degraded":
            return 10
        return 0 if result.get("verdict") == "pass" else 1

    if args.cmd == "upgrade":
        result = self_upgrade(
            stamp=stamp,
            install_root=install_root,
            dest_dir=Path(args.dest) if args.dest else None,
            dry_run=bool(args.dry_run),
        )
        print(json.dumps(result, indent=2))
        return 0 if result.get("verdict") == "pass" else 20

    return 2


if __name__ == "__main__":
    run_module_main(main)
