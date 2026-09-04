"""PRD 342 unit 5 — template resolution stack (R37–R41)."""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import doctor  # noqa: E402
import template_pack as tp  # noqa: E402
import template_resolve as tr  # noqa: E402

REPO = Path(__file__).resolve().parents[3]


def _seed_core(repo: Path, *, pr_body: str = "CORE-PR\n") -> None:
    core = repo / "core" / "sw-reference" / "templates"
    core.mkdir(parents=True)
    (core / "pr-body.md").write_text(pr_body, encoding="utf-8")
    (core / "merge-commit.md").write_text("CORE-MERGE\n", encoding="utf-8")


def _write_pack(pack_dir: Path, *, pack_id: str = "demo", body: str = "PACK-PR\n") -> Path:
    pack_dir.mkdir(parents=True)
    (pack_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": pack_id,
                "version": "1.0.0",
                "paths": ["pr-body.md"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (pack_dir / "pr-body.md").write_text(body, encoding="utf-8")
    return pack_dir


def test_unused_stack_byte_identical_to_core() -> None:
    """R38: with no overrides and no packs, every resolved template matches core."""
    for resolved in tr.resolve_all(REPO):
        core_file = tr.core_templates_dir(REPO) / resolved.path
        assert core_file.is_file()
        assert resolved.bytes == core_file.read_bytes()
        assert resolved.layer == "core"


def test_first_match_wins_override_then_pack_then_core(tmp_path: Path) -> None:
    """R37: override > pack > core."""
    repo = tmp_path / "repo"
    _seed_core(repo)
    pack = _write_pack(tmp_path / "pack")
    tp.install_pack(repo, pack)

    pack_hit = tr.resolve_template(repo, "pr-body.md")
    assert pack_hit.layer == "pack"
    assert pack_hit.bytes == b"PACK-PR\n"

    override_dir = tr.preferred_overrides_dir(repo)
    override_dir.mkdir(parents=True)
    (override_dir / "pr-body.md").write_text("OVERRIDE-PR\n", encoding="utf-8")
    override_hit = tr.resolve_template(repo, "pr-body.md")
    assert override_hit.layer == "override"
    assert override_hit.bytes == b"OVERRIDE-PR\n"

    merge = tr.resolve_template(repo, "merge-commit.md")
    assert merge.layer == "core"
    assert merge.bytes == b"CORE-MERGE\n"


def test_provenance_names_supplying_layer(tmp_path: Path) -> None:
    """R39: provenance report names the layer that supplied each template."""
    repo = tmp_path / "repo"
    _seed_core(repo)
    pack = _write_pack(tmp_path / "pack")
    tp.install_pack(repo, pack)
    override_dir = tr.preferred_overrides_dir(repo)
    override_dir.mkdir(parents=True)
    (override_dir / "pr-body.md").write_text("OVERRIDE-PR\n", encoding="utf-8")

    report = tr.provenance_report(repo)
    by_path = {row["path"]: row for row in report["templates"]}
    assert by_path["pr-body.md"]["layer"] == "override"
    assert by_path["merge-commit.md"]["layer"] == "core"


def test_manifest_less_pack_rejected(tmp_path: Path) -> None:
    """R40: a pack without a manifest is rejected."""
    pack = tmp_path / "no-manifest"
    pack.mkdir()
    (pack / "pr-body.md").write_text("x\n", encoding="utf-8")
    with pytest.raises(tp.TemplatePackError) as excinfo:
        tp.validate_pack_dir(pack)
    assert excinfo.value.code == "manifest-missing"


def test_uninstall_restores_prior_outcome_and_leaves_core_untouched(tmp_path: Path) -> None:
    """R40: uninstall restores the prior resolution outcome; core files unchanged."""
    repo = tmp_path / "repo"
    _seed_core(repo, pr_body="CORE-PR\n")
    core_pr = tr.core_templates_dir(repo) / "pr-body.md"
    core_before = core_pr.read_bytes()

    before = tr.resolve_template(repo, "pr-body.md")
    assert before.layer == "core"
    assert before.bytes == core_before

    pack = _write_pack(tmp_path / "pack", body="PACK-PR\n")
    tp.install_pack(repo, pack)
    assert tr.resolve_template(repo, "pr-body.md").bytes == b"PACK-PR\n"

    # Also cover archive install path.
    archive = tmp_path / "pack.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(pack / "manifest.json", "manifest.json")
        zf.write(pack / "pr-body.md", "pr-body.md")
    tp.uninstall_pack(repo, "demo")
    tp.install_pack(repo, archive)
    assert tr.resolve_template(repo, "pr-body.md").layer == "pack"

    tp.uninstall_pack(repo, "demo")
    after = tr.resolve_template(repo, "pr-body.md")
    assert after.layer == "core"
    assert after.bytes == before.bytes == core_before
    assert core_pr.read_bytes() == core_before


def test_legacy_sw_templates_retired_and_disposition_recorded() -> None:
    """R37: no unread .sw/templates equivalent survives; disposition is recorded."""
    assert not tr.legacy_templates_present(REPO)
    legacy = REPO / ".sw" / "templates"
    assert not legacy.exists() or not any(p.is_file() for p in legacy.rglob("*"))

    disposition = tr.load_disposition(REPO)
    assert disposition is not None
    assert disposition.get("disposition") == "deleted"
    assert disposition.get("legacyPath") == ".sw/templates"
    assert "pr-body.md" in (disposition.get("deletedPaths") or [])


def test_doctor_reports_override_drift(tmp_path: Path) -> None:
    """R41: doctor surfaces overrides that shadow a changed core default."""
    repo = tmp_path / "repo"
    _seed_core(repo, pr_body="CORE-V1\n")
    override_dir = tr.preferred_overrides_dir(repo)
    override_dir.mkdir(parents=True)
    (override_dir / "pr-body.md").write_text("CUSTOM\n", encoding="utf-8")
    tr.record_core_baselines(repo, paths=["pr-body.md"])

    # Core default changes while the override remains.
    (tr.core_templates_dir(repo) / "pr-body.md").write_text("CORE-V2\n", encoding="utf-8")
    findings = tr.diagnose_override_drift(repo)
    assert any(f.get("path") == "pr-body.md" for f in findings)

    report = doctor.diagnose(repo)
    assert any(
        issue.startswith("template-override-drift:pr-body.md") for issue in report["issues"]
    )
    assert report["verdict"] == "warn"
