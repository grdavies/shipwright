#!/usr/bin/env python3
"""Build the versioned Shipwright scripts zipapp (PRD 091 R3/R4; PRD 342 R49)."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import build_parser, run_module_main

MANIFEST_VERSION = 1
# Per-artifact distribution stamp (R49). Forks pass --distribution-origin.
DEFAULT_DISTRIBUTION_ORIGIN = "https://github.com/grdavies/shipwright/releases"
DISTRIBUTION_STAMP_NAME = "shipwright-distribution-stamp.json"
INTEGRITY_ALG = "sha256"

EXCLUDE_DIR_NAMES = {"__pycache__", "test", "tests", "unit_tests", ".git", "node_modules"}
DEV_TEST_SCRIPT_DIRS = frozenset({"test", "tests", "unit_tests"})
DEV_ONLY_SCRIPT_RELPATHS = frozenset(
    {
        "copy-to-core.sh",
        "copy-to-core.py",
        "core_content_sync.py",
        "snapshot-tree.sh",
        "snapshot-tree.py",
        "model-routing-check.sh",
        "model-routing-check.py",
    }
)
EXCLUDE_REL_PATHS = frozenset(
    {"install.sh", "planning_store.py", *DEV_ONLY_SCRIPT_RELPATHS}
)
EXCLUDE_SUFFIXES = (".pyc",)

ZIPAPP_LAUNCHER = '''#!/usr/bin/env python3
"""Shipwright zipapp launcher — run a bundled script by relative path."""
from __future__ import annotations

import sys
import types
import zipimport
from pathlib import PurePosixPath


def _usage() -> None:
    print("usage: shipwright.pyz <script.py> [args...]", file=sys.stderr)


def _module_name(script: str) -> str:
    path = PurePosixPath(script)
    if path.suffix == ".py":
        path = path.with_suffix("")
    return path.as_posix()


def main() -> None:
    if not sys.argv or not sys.argv[0].endswith(".pyz"):
        return
    if len(sys.argv) < 2:
        _usage()
        raise SystemExit(2)
    script = sys.argv[1]
    if "\\\\" in script:
        script = script.replace("\\\\", "/")
    if script.startswith("/") or ".." in PurePosixPath(script).parts:
        print(f"unsafe script name: {script}", file=sys.stderr)
        raise SystemExit(2)
    if not script.endswith(".py"):
        script = f"{script}.py"
    archive = sys.argv[0]
    module_name = _module_name(script)
    sys.argv = [script, *sys.argv[2:]]
    importer = zipimport.zipimporter(archive)
    code = importer.get_code(module_name)
    module = types.ModuleType("__main__")
    module.__file__ = f"{archive}/{script}"
    sys.modules["__main__"] = module
    exec(code, module.__dict__)


if __name__ == "__main__":
    main()
'''

PLANNING_STORE_PATCH = (
    ('_CANONICAL_REL = "scripts/planning_store_facade.py"', '_CANONICAL_REL = "planning_store_facade.py"'),
    ("_REPO_ROOT_DEPTH = 1", "_REPO_ROOT_DEPTH = 0"),
)

# Reproducible zip entries (zipapp default timestamps are non-deterministic).
ZIPAPP_FIXED_DT = (1980, 1, 1, 0, 0, 0)


class ZipappCompletenessError(RuntimeError):
    """Raised when the built zipapp is missing manifest-listed modules."""


def repo_root(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit.resolve()
    return SCRIPT_DIR.parent


def read_version(root: Path) -> str:
    path = root / "version.txt"
    if not path.is_file():
        raise FileNotFoundError(f"missing version source: {path}")
    version = path.read_text(encoding="utf-8").strip()
    if not version:
        raise ValueError(f"empty version source: {path}")
    return version


def should_skip_script(rel_posix: str, parts: tuple[str, ...]) -> bool:
    if any(part in EXCLUDE_DIR_NAMES for part in parts):
        return True
    if rel_posix in EXCLUDE_REL_PATHS:
        return True
    if parts and parts[0] in DEV_TEST_SCRIPT_DIRS:
        return True
    return False


def stage_scripts_tree(scripts_src: Path, staging: Path) -> list[str]:
    """Copy the filtered scripts/ tree into staging; return relative paths staged."""
    written: list[str] = []
    for path in sorted(scripts_src.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(scripts_src)
        rel_posix = rel.as_posix()
        if path.suffix in EXCLUDE_SUFFIXES:
            continue
        if should_skip_script(rel_posix, rel.parts):
            continue
        if path.suffix == ".sh" and rel.parts and rel.parts[0] == "providers":
            py_sibling = path.with_suffix(".py")
            if py_sibling.is_file():
                continue
        out_path = staging / rel_posix
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, out_path)
        written.append(rel_posix)
    return written


def list_staged_modules(staging: Path) -> list[str]:
    return sorted(
        path.relative_to(staging).as_posix()
        for path in staging.rglob("*")
        if path.is_file()
    )


def patch_planning_store_shim(staging: Path, root: Path | None = None) -> None:
    """Emit a zipapp-local planning_store shim pointing at the bundled facade."""
    src = (root or repo_root()) / "scripts" / "planning_store.py"
    if not src.is_file():
        return
    text = src.read_text(encoding="utf-8")
    for old, new in PLANNING_STORE_PATCH:
        text = text.replace(old, new)
    (staging / "planning_store.py").write_text(text, encoding="utf-8")


def write_zipapp_launcher(staging: Path) -> None:
    (staging / "_zipapp_launcher.py").write_text(ZIPAPP_LAUNCHER, encoding="utf-8")


def create_deterministic_zipapp(staging: Path, target: Path) -> None:
    """Build a reproducible zipapp with a fixed entrypoint."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    payload = tempfile.NamedTemporaryFile(delete=False)
    payload.close()
    try:
        with zipfile.ZipFile(payload.name, "w", compression=zipfile.ZIP_STORED) as zf:
            for path in sorted(staging.rglob("*")):
                if not path.is_file():
                    continue
                arcname = path.relative_to(staging).as_posix()
                info = zipfile.ZipInfo(arcname, ZIPAPP_FIXED_DT)
                info.compress_type = zipfile.ZIP_STORED
                info.create_system = 3
                zf.writestr(info, path.read_bytes())
            main_info = zipfile.ZipInfo("__main__.py", ZIPAPP_FIXED_DT)
            main_info.compress_type = zipfile.ZIP_STORED
            main_info.create_system = 3
            main_body = (
                "# -*- coding: utf-8 -*-\n"
                "import _zipapp_launcher\n"
                "_zipapp_launcher.main()\n"
            )
            zf.writestr(main_info, main_body.encode("utf-8"))
        with open(payload.name, "rb") as src, open(target, "wb") as dst:
            dst.write(b"#!/usr/bin/env python3\n")
            dst.write(src.read())
    finally:
        Path(payload.name).unlink(missing_ok=True)
    target.chmod(0o755)


def list_zipapp_payload_modules(pyz: Path) -> set[str]:
    with zipfile.ZipFile(pyz, "r") as zf:
        return {name for name in zf.namelist() if name != "__main__.py"}


def verify_zipapp_completeness(pyz: Path, expected_modules: list[str]) -> list[str]:
    """Return manifest-listed modules missing from the zipapp payload."""
    actual = list_zipapp_payload_modules(pyz)
    return sorted(set(expected_modules) - actual)


def build_manifest_payload(
    version: str,
    modules: list[str],
    *,
    distribution_origin: str = DEFAULT_DISTRIBUTION_ORIGIN,
) -> dict[str, object]:
    return {
        "version": MANIFEST_VERSION,
        "zipappVersion": version,
        "modules": modules,
        "moduleCount": len(modules),
        "distributionOrigin": distribution_origin,
    }


def build_distribution_stamp(
    version: str,
    *,
    distribution_origin: str,
    artifact_sha256: str | None = None,
) -> dict[str, object]:
    """Single-source per-artifact version + origin stamp (R49)."""
    stamp: dict[str, object] = {
        "schemaVersion": 1,
        "releaseVersion": version,
        "distributionOrigin": distribution_origin,
        "integrity": {"algorithm": INTEGRITY_ALG, "mechanism": "sha256-digest"},
    }
    if artifact_sha256:
        stamp["integrity"] = {
            "algorithm": INTEGRITY_ALG,
            "mechanism": "sha256-digest",
            "sha256": artifact_sha256,
        }
    return stamp


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(
    dest_dir: Path,
    version: str,
    modules: list[str],
    *,
    distribution_origin: str = DEFAULT_DISTRIBUTION_ORIGIN,
) -> Path:
    manifest_name = f"shipwright-{version}.manifest.json"
    manifest_path = dest_dir / manifest_name
    manifest_path.write_text(
        json.dumps(
            build_manifest_payload(
                version, modules, distribution_origin=distribution_origin
            ),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    stable_manifest = dest_dir / "shipwright.manifest.json"
    if stable_manifest.exists() or stable_manifest.is_symlink():
        stable_manifest.unlink()
    stable_manifest.symlink_to(manifest_name)
    return manifest_path


def write_distribution_stamp(dest_dir: Path, stamp: dict[str, object]) -> Path:
    stamp_path = dest_dir / DISTRIBUTION_STAMP_NAME
    stamp_path.write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")
    return stamp_path


def embed_distribution_stamp(staging: Path, stamp: dict[str, object]) -> None:
    (staging / DISTRIBUTION_STAMP_NAME).write_text(
        json.dumps(stamp, indent=2) + "\n", encoding="utf-8"
    )


def read_distribution_stamp_from_pyz(pyz: Path) -> dict[str, object] | None:
    """Read the embedded distribution stamp from a built zipapp (R49/R20)."""
    with zipfile.ZipFile(pyz, "r") as zf:
        try:
            raw = zf.read(DISTRIBUTION_STAMP_NAME)
        except KeyError:
            return None
    data = json.loads(raw.decode("utf-8"))
    return data if isinstance(data, dict) else None


def build_archive(
    root: Path,
    dest_dir: Path,
    *,
    version: str | None = None,
    skip_modules: set[str] | None = None,
    distribution_origin: str | None = None,
) -> dict[str, str | int | list[str]]:
    scripts_src = root / "scripts"
    if not scripts_src.is_dir():
        raise FileNotFoundError(f"missing scripts tree: {scripts_src}")
    ver = version or read_version(root)
    origin = (distribution_origin or DEFAULT_DISTRIBUTION_ORIGIN).rstrip("/")
    dest_dir.mkdir(parents=True, exist_ok=True)
    versioned_name = f"shipwright-{ver}.pyz"
    versioned_path = dest_dir / versioned_name
    stable_path = dest_dir / "shipwright.pyz"
    skip = skip_modules or set()

    # Embedded stamp carries release + origin only. Digest lives in the sidecar
    # so the integrity check has a single stable mechanism (R49/R51) without a
    # self-referential hash of the stamp bytes.
    embedded_stamp = build_distribution_stamp(ver, distribution_origin=origin)
    with tempfile.TemporaryDirectory(prefix="sw-zipapp-stage-") as tmp:
        staging = Path(tmp)
        stage_scripts_tree(scripts_src, staging)
        patch_planning_store_shim(staging, root)
        write_zipapp_launcher(staging)
        embed_distribution_stamp(staging, embedded_stamp)
        expected_modules = list_staged_modules(staging)
        if skip:
            for rel in sorted(skip):
                target = staging / rel
                if target.is_file():
                    target.unlink()
        create_deterministic_zipapp(staging, versioned_path)

    missing = verify_zipapp_completeness(versioned_path, expected_modules)
    if missing:
        raise ZipappCompletenessError(
            "zipapp completeness check failed; missing modules: " + ", ".join(missing)
        )

    artifact_sha = sha256_file(versioned_path)
    stamp = build_distribution_stamp(
        ver, distribution_origin=origin, artifact_sha256=artifact_sha
    )
    stamp_path = write_distribution_stamp(dest_dir, stamp)
    manifest_path = write_manifest(
        dest_dir, ver, expected_modules, distribution_origin=origin
    )

    if stable_path.exists() or stable_path.is_symlink():
        stable_path.unlink()
    stable_path.symlink_to(versioned_name)

    return {
        "verdict": "pass",
        "version": ver,
        "moduleCount": len(expected_modules),
        "versionedPath": str(versioned_path),
        "stablePath": str(stable_path),
        "manifestPath": str(manifest_path),
        "distributionStampPath": str(stamp_path),
        "distributionOrigin": origin,
        "sha256": artifact_sha,
        "modules": expected_modules,
    }


def cmd_build(args: argparse.Namespace) -> int:
    root = repo_root(Path(args.root))
    dest = Path(args.dest).resolve() if args.dest else root / "dist"
    try:
        payload = build_archive(
            root,
            dest,
            version=args.version or None,
            distribution_origin=args.distribution_origin or None,
        )
    except ZipappCompletenessError as exc:
        print(str(exc), file=sys.stderr)
        return 20
    print(json.dumps(payload, indent=2))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    pyz = Path(args.pyz).resolve()
    manifest = Path(args.manifest).resolve()
    if not pyz.is_file():
        print(f"build_zipapp verify: missing zipapp {pyz}", file=sys.stderr)
        return 2
    if not manifest.is_file():
        print(f"build_zipapp verify: missing manifest {manifest}", file=sys.stderr)
        return 2
    data = json.loads(manifest.read_text(encoding="utf-8"))
    modules = data.get("modules")
    if not isinstance(modules, list) or not modules:
        print("build_zipapp verify: manifest.modules must be a non-empty list", file=sys.stderr)
        return 2
    expected = [str(item) for item in modules]
    missing = verify_zipapp_completeness(pyz, expected)
    if missing:
        print(
            "build_zipapp verify: FAIL missing modules: " + ", ".join(missing),
            file=sys.stderr,
        )
        return 20
    print(json.dumps({"verdict": "pass", "moduleCount": len(expected)}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="build_zipapp.py",
        description="Package scripts/ into a versioned shipwright.pyz zipapp.",
    )
    parser.add_argument("--root", default=".", help="Repository root")
    sub = parser.add_subparsers(dest="cmd", required=True)
    build = sub.add_parser("build", help="Build shipwright-{version}.pyz into --dest")
    build.add_argument(
        "--dest",
        default="",
        help="Output directory (default: <repo>/dist)",
    )
    build.add_argument("--version", default="", help="Override version.txt")
    build.add_argument(
        "--distribution-origin",
        default="",
        help="Per-artifact distribution origin URL recorded in the version stamp (R49)",
    )
    verify = sub.add_parser("verify", help="Verify zipapp contains manifest-listed modules")
    verify.add_argument("--pyz", required=True, help="Path to shipwright.pyz")
    verify.add_argument("--manifest", required=True, help="Path to shipwright manifest JSON")
    args = parser.parse_args(argv)
    if args.cmd == "build":
        return cmd_build(args)
    if args.cmd == "verify":
        return cmd_verify(args)
    return 2


if __name__ == "__main__":
    run_module_main(main)
