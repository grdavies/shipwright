"""PRD 091 R4 — zipapp build-manifest completeness regression guard."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def _load_build_zipapp():
    spec = importlib.util.spec_from_file_location("build_zipapp", SCRIPT_DIR / "build_zipapp.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_emits_manifest_and_passes_completeness(repo_root: Path, tmp_path: Path) -> None:
    mod = _load_build_zipapp()
    dest = tmp_path / "plugin"
    payload = mod.build_archive(repo_root, dest)
    assert payload["verdict"] == "pass"
    manifest_path = Path(str(payload["manifestPath"]))
    assert manifest_path.is_file()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["moduleCount"] == payload["moduleCount"]
    assert data["modules"] == payload["modules"]
    pyz = Path(str(payload["versionedPath"]))
    assert mod.verify_zipapp_completeness(pyz, data["modules"]) == []


def test_completeness_fails_when_module_missing(repo_root: Path, tmp_path: Path) -> None:
    mod = _load_build_zipapp()
    dest = tmp_path / "plugin"
    with pytest.raises(mod.ZipappCompletenessError, match="missing modules"):
        mod.build_archive(repo_root, dest, skip_modules={"resolve-model-tier.py"})


def test_completeness_passes_when_module_included(repo_root: Path, tmp_path: Path) -> None:
    mod = _load_build_zipapp()
    dest = tmp_path / "plugin"
    payload = mod.build_archive(repo_root, dest)
    pyz = Path(str(payload["versionedPath"]))
    assert "resolve-model-tier.py" in payload["modules"]
    assert mod.verify_zipapp_completeness(pyz, payload["modules"]) == []


# PRD 367 PACKAGE: exercise the standard builder before any test-only mutation.
@pytest.fixture(scope="module")
def scanner_standard_archive(tmp_path_factory):
    import zipfile

    root = SCRIPT_DIR.parent
    dest = tmp_path_factory.mktemp("scanner-standard-build")
    payload = _load_build_zipapp().build_archive(root, dest)
    assert payload["verdict"] == "pass"
    archive = Path(str(payload["versionedPath"]))
    manifest = json.loads(Path(str(payload["manifestPath"])).read_bytes())
    required = ("secret_scan.py", "secret_scan_exact.py", "secret_patterns.py",
                "secret_scan_data/reviewed-occurrences.v1.json")
    with zipfile.ZipFile(archive) as built:
        assert manifest["moduleCount"] == len(manifest["modules"])
        assert sorted(built.namelist()) == sorted([*manifest["modules"], "__main__.py"])
        for member in required:
            assert manifest["modules"].count(member) == 1
            assert built.namelist().count(member) == 1
            assert built.read(member) == (SCRIPT_DIR / member).read_bytes()
        catalog = built.read(required[-1])
        import secret_scan_exact

        parsed = secret_scan_exact.parse_catalog(catalog)
        # Valid empty catalogs are supported; later reviewed populations retain
        # this same byte-parity/schema check without freezing release contents.
        assert len(parsed.records) == len(json.loads(catalog)["records"])
    return archive


def test_standard_build_includes_exact_scanner_catalog(scanner_standard_archive):
    assert scanner_standard_archive.is_file()


@pytest.mark.skipif(sys.platform != "darwin", reason="secure enrollment requires native Darwin ACLs")
@pytest.mark.parametrize("damage", (
    "archive-digest", "missing-helper", "missing-catalog", "duplicate-helper",
    "duplicate-catalog", "traversal", "helper-bytes", "catalog-digest",
))
def test_standard_archive_integrity_declines_exceptions(scanner_standard_archive, damage):
    import tempfile
    import zipfile

    from unit_tests.test_zipapp_fresh_install import _ScannerInstall

    helper = "secret_scan_exact.py"
    catalog = "secret_scan_data/reviewed-occurrences.v1.json"
    # Reuse the secure account/home and bounded subprocess harness. Only the
    # isolated catalog is populated, and only after standard inclusion passed.
    with tempfile.TemporaryDirectory(prefix="scanner-package-") as temporary:
        root = Path(temporary).resolve()
        root.chmod(0o700)
        fixture = _ScannerInstall(root)
        with zipfile.ZipFile(scanner_standard_archive) as built:
            members = [(info.filename, built.read(info)) for info in built.infolist()]
        members = [(name, fixture.catalog if name == catalog else data)
                   for name, data in members]

        def write_members(contents):
            with zipfile.ZipFile(fixture.archive, "w", zipfile.ZIP_DEFLATED) as output:
                for name, data in contents:
                    output.writestr(name, data)
            fixture.archive.chmod(0o600)

        write_members(members)
        fixture.enroll("source")
        fixture.scan_readonly("source", 0)
        approved_args = fixture.args()
        if damage == "archive-digest":
            with fixture.archive.open("ab") as output:
                output.write(b"changed release bytes")
        elif damage.startswith("missing-"):
            missing = helper if damage == "missing-helper" else catalog
            write_members([(name, data) for name, data in members if name != missing])
        elif damage.startswith("duplicate-"):
            duplicate = helper if damage == "duplicate-helper" else catalog
            with pytest.warns(UserWarning, match="Duplicate name"):
                write_members(members + [(duplicate, dict(members)[duplicate])])
        elif damage == "traversal":
            write_members(members + [("../escape", b"must never be extracted")])
        else:
            altered = helper if damage == "helper-bytes" else catalog
            write_members([(name, data + b"\n" if name == altered else data)
                           for name, data in members])
        # Structural/module/catalog negatives supply the actual new archive
        # digest, so they cannot pass by testing only the outer hash mismatch.
        args = approved_args if damage == "archive-digest" else fixture.args()
        before = fixture.snapshot()
        result = fixture.invoke("source", args)
        assert result.returncode == 2
        assert result.stdout == ""
        assert "secret-scan: enrollment refused" in result.stderr
        assert fixture.snapshot() == before
        fixture.scan_readonly("source", 1)
        assert not (root / "escape").exists()
