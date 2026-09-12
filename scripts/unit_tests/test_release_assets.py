"""PRD 345 R5–R6 — release asset publication and verification."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_zipapp
import release_assets
import sw_self


def test_asset_names_follow_version_convention() -> None:
    """R5 — required asset filenames are version-scoped and stable."""
    names = release_assets.asset_names("2.10.0")
    assert names["versionedPyz"] == "shipwright-2.10.0.pyz"
    assert names["distributionStamp"] == build_zipapp.DISTRIBUTION_STAMP_NAME
    assert names["manifest"] == "shipwright-2.10.0.manifest.json"


def test_verify_fails_when_assets_missing(tmp_path: Path) -> None:
    """Z — verification fails closed when no release assets exist."""
    root = tmp_path / "repo"
    dest = root / "dist" / "cursor"
    dest.mkdir(parents=True)
    (root / "version.txt").write_text("1.2.3\n", encoding="utf-8")

    result = release_assets.verify_release_assets(root, dest_dir=dest, version="1.2.3")
    assert result["verdict"] == "fail"
    assert result["status"] == "missing-assets"
    assert result["findings"]


def test_build_and_verify_round_trip(tmp_path: Path) -> None:
    """O/M — build emits zipapp + stamp; verify passes on complete set."""
    root = tmp_path / "repo"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "version.py").write_text('__version__ = "1.2.3"\n', encoding="utf-8")
    (scripts / "noop.py").write_text("def main() -> int:\n    return 0\n", encoding="utf-8")
    (root / "version.txt").write_text("1.2.3\n", encoding="utf-8")
    dest = root / "dist" / "cursor"

    built = release_assets.build_release_assets(root, dest_dir=dest)
    assert built["verdict"] == "pass"
    names = release_assets.asset_names("1.2.3")
    assert (dest / names["versionedPyz"]).is_file()
    assert (dest / names["distributionStamp"]).is_file()
    assert (dest / names["manifest"]).is_file()

    verified = release_assets.verify_release_assets(root, dest_dir=dest, version="1.2.3")
    assert verified["verdict"] == "pass"
    assert verified["status"] == "ok"
    assert len(verified["assets"]) == 3


def test_verify_detects_stamp_version_mismatch(tmp_path: Path) -> None:
    """E — stamp/release version mismatch is a hard verification failure."""
    root = tmp_path / "repo"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "version.py").write_text('__version__ = "1.2.3"\n', encoding="utf-8")
    (scripts / "noop.py").write_text("def main() -> int:\n    return 0\n", encoding="utf-8")
    (root / "version.txt").write_text("1.2.3\n", encoding="utf-8")
    dest = root / "dist" / "cursor"
    built = release_assets.build_release_assets(root, dest_dir=dest)
    assert built["verdict"] == "pass"

    stamp_path = dest / build_zipapp.DISTRIBUTION_STAMP_NAME
    stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    stamp["releaseVersion"] = "9.9.9"
    stamp_path.write_text(json.dumps(stamp) + "\n", encoding="utf-8")

    result = release_assets.verify_release_assets(root, dest_dir=dest, version="1.2.3")
    assert result["verdict"] == "fail"
    assert result["status"] == "version-mismatch"


def test_verify_detects_integrity_mismatch(tmp_path: Path) -> None:
    """E — corrupt zipapp bytes fail integrity verification."""
    root = tmp_path / "repo"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "version.py").write_text('__version__ = "1.2.3"\n', encoding="utf-8")
    (scripts / "noop.py").write_text("def main() -> int:\n    return 0\n", encoding="utf-8")
    (root / "version.txt").write_text("1.2.3\n", encoding="utf-8")
    dest = root / "dist" / "cursor"
    release_assets.build_release_assets(root, dest_dir=dest)

    names = release_assets.asset_names("1.2.3")
    pyz = dest / names["versionedPyz"]
    pyz.write_bytes(b"truncated-or-corrupt")

    result = release_assets.verify_release_assets(root, dest_dir=dest, version="1.2.3")
    assert result["verdict"] == "fail"
    assert result["status"] == "integrity-failed"


def test_publication_manifest_lists_upload_assets(tmp_path: Path) -> None:
    """R5 — manifest command surfaces upload-ready asset descriptors."""
    root = tmp_path / "repo"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "version.py").write_text('__version__ = "1.2.3"\n', encoding="utf-8")
    (scripts / "noop.py").write_text("def main() -> int:\n    return 0\n", encoding="utf-8")
    (root / "version.txt").write_text("1.2.3\n", encoding="utf-8")
    dest = root / "dist" / "cursor"
    release_assets.build_release_assets(root, dest_dir=dest)

    assets = release_assets.publication_assets(root, dest_dir=dest, version="1.2.3")
    assert len(assets) == 3
    assert {item["kind"] for item in assets} == {
        "versionedPyz",
        "distributionStamp",
        "manifest",
    }


def test_sw_self_upgrade_reports_missing_assets_gracefully() -> None:
    """R8 — missing release assets produce actionable upgrade refusal text."""
    stamp = {
        "schemaVersion": 1,
        "releaseVersion": "2.9.0",
        "distributionOrigin": "https://github.com/grdavies/shipwright/releases",
    }

    def ok(_url: str):
        return {
            "tag_name": "v2.10.0",
            "assets": [{"name": "README.md", "browser_download_url": "https://example.com/readme"}],
        }

    result = sw_self.self_upgrade(stamp=stamp, fetcher=ok)
    assert result["verdict"] == "fail"
    assert result["status"] == "missing-assets"
    message = result.get("message") or ""
    assert "distribution stamp" in message.lower()
    assert "self-upgrade.md" in message.lower()


def test_sw_self_check_flags_incomplete_release_assets() -> None:
    """R8 — self check surfaces when a release exists but assets are incomplete."""
    stamp = {
        "schemaVersion": 1,
        "releaseVersion": "2.9.0",
        "distributionOrigin": "https://github.com/grdavies/shipwright/releases",
    }

    def ok(_url: str):
        return {
            "tag_name": "v2.10.0",
            "assets": [],
        }

    result = sw_self.self_check(stamp=stamp, fetcher=ok)
    assert result["status"] == "ok"
    assert result.get("assetsAvailable") is False
    assert "missing required release assets" in (result.get("message") or "").lower()
