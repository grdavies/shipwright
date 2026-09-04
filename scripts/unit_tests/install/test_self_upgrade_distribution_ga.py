"""Phase 6 — self-upgrade, distribution integrity, GA bar (PRD 342 R19/R20/R23/R49/R51)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_zipapp
import capability_trust
import packaged_install_check_gate
import sw_self


def test_distribution_stamp_records_version_and_origin(repo_root: Path, tmp_path: Path) -> None:
    payload = build_zipapp.build_archive(
        repo_root,
        tmp_path / "dist",
        distribution_origin="https://example.com/fork/releases",
    )
    assert payload["distributionOrigin"] == "https://example.com/fork/releases"
    stamp_path = Path(str(payload["distributionStampPath"]))
    stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    assert stamp["releaseVersion"] == payload["version"]
    assert stamp["distributionOrigin"] == "https://example.com/fork/releases"
    assert stamp["integrity"]["sha256"] == payload["sha256"]
    embedded = build_zipapp.read_distribution_stamp_from_pyz(Path(str(payload["versionedPath"])))
    assert embedded is not None
    assert embedded["releaseVersion"] == payload["version"]
    assert embedded["distributionOrigin"] == "https://example.com/fork/releases"


def test_exactly_one_integrity_mechanism() -> None:
    assert capability_trust.distribution_integrity_mechanisms() == ["sha256-digest"]


def test_integrity_failure_names_corruption_not_tampering(tmp_path: Path) -> None:
    artifact = tmp_path / "shipwright.pyz"
    artifact.write_bytes(b"not-a-real-zipapp")
    stamp = build_zipapp.build_distribution_stamp(
        "9.9.9",
        distribution_origin="https://example.com/releases",
        artifact_sha256="00" * 32,
    )
    stamp_path = tmp_path / build_zipapp.DISTRIBUTION_STAMP_NAME
    stamp_path.write_text(json.dumps(stamp) + "\n", encoding="utf-8")
    result = capability_trust.verify_distribution_integrity(
        artifact, stamp=stamp, stamp_path=stamp_path
    )
    assert result["ok"] is False
    assert result["upgradeAllowed"] is False
    message = (result.get("message") or "").lower()
    assert "corruption" in message
    assert "tamper" not in message
    assert "provenance" not in message or "does not assert" in message


def test_self_check_degraded_when_origin_unreachable() -> None:
    stamp = {
        "schemaVersion": 1,
        "releaseVersion": "2.9.0",
        "distributionOrigin": "https://example.invalid/releases",
    }

    def boom(_url: str):
        raise TimeoutError("unreachable")

    result = sw_self.self_check(stamp=stamp, fetcher=boom)
    assert result["status"] == "degraded"
    assert result["updateAvailable"] is False
    assert "degraded" in (result.get("message") or "").lower()


def test_self_check_resolves_origin_manifests() -> None:
    stamp = {
        "schemaVersion": 1,
        "releaseVersion": "2.9.0",
        "distributionOrigin": "https://github.com/grdavies/shipwright/releases",
    }

    def ok(_url: str):
        return {
            "tag_name": "v2.10.0",
            "assets": [
                {
                    "name": build_zipapp.DISTRIBUTION_STAMP_NAME,
                    "browser_download_url": "https://example.com/stamp.json",
                },
                {
                    "name": "shipwright-2.10.0.pyz",
                    "browser_download_url": "https://example.com/shipwright-2.10.0.pyz",
                },
            ],
        }

    result = sw_self.self_check(stamp=stamp, fetcher=ok)
    assert result["status"] == "ok"
    assert result["updateAvailable"] is True
    assert result["availableVersion"] == "2.10.0"


def test_self_upgrade_refuses_corrupt_artifact(tmp_path: Path) -> None:
    stamp = {
        "schemaVersion": 1,
        "releaseVersion": "2.9.0",
        "distributionOrigin": "https://github.com/grdavies/shipwright/releases",
    }

    def ok(_url: str):
        return {
            "tag_name": "v2.10.0",
            "assets": [
                {
                    "name": build_zipapp.DISTRIBUTION_STAMP_NAME,
                    "browser_download_url": "https://example.com/stamp.json",
                },
                {
                    "name": "shipwright-2.10.0.pyz",
                    "browser_download_url": "https://example.com/a.pyz",
                },
            ],
        }

    bad_stamp = build_zipapp.build_distribution_stamp(
        "2.10.0",
        distribution_origin="https://github.com/grdavies/shipwright/releases",
        artifact_sha256="11" * 32,
    )

    def fetch_bytes(url: str) -> bytes:
        if url.endswith("stamp.json"):
            return json.dumps(bad_stamp).encode("utf-8")
        return b"truncated-or-corrupt-bytes"

    result = sw_self.self_upgrade(
        stamp=stamp,
        fetcher=ok,
        fetch_bytes=fetch_bytes,
        dest_dir=tmp_path / "dest",
    )
    assert result["verdict"] == "fail"
    assert result["upgradeApplied"] is False
    assert "corruption" in (result.get("message") or "").lower()


def test_packaged_install_check_gate_wiring(repo_root: Path) -> None:
    assert packaged_install_check_gate.packaged_install_workflow_present(repo_root)
    checks = packaged_install_check_gate.packaged_install_required_checks()
    assert "packaged-install-cursor" in checks
    assert "packaged-install-claude-code" in checks
    annotated = packaged_install_check_gate.annotate_check_gate_payload(
        {"verdict": "green"}, root=repo_root
    )
    assert annotated["packagedInstallGa"]["present"] is True


def test_console_routes_self_to_sw_self(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sys.path.insert(0, str(repo_root))
    from sw import console

    called: list[list[str]] = []

    class FakeSelf:
        @staticmethod
        def main(argv: list[str]) -> int:
            called.append(list(argv))
            return 0

    monkeypatch.setattr(console, "_load_scripts_module", lambda *_a, **_k: FakeSelf)
    assert console.main(["self", "check"]) == 0
    assert called == [["check"]]
