"""No credential-storage dependency tests (PRD 080 6.5 / R3)."""

from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path

import pytest

from credentials.backends import BACKEND_NAMES, backend_module_name, list_backends


REPO_ROOT = Path(__file__).resolve().parents[3]
DEPMANIFEST = REPO_ROOT / "scripts" / "_sw" / "depmanifest.json"
CREDENTIALS_PACKAGE = REPO_ROOT / "scripts" / "credentials"
FORBIDDEN_DEPENDENCY_MARKERS = (
    "keyring",
    "secretstorage",
    "keyrings.alt",
    "credential",
    "keytar",
)


def _stdlib_modules() -> set[str]:
    import sys

    if hasattr(sys, "stdlib_module_names"):
        return set(sys.stdlib_module_names)
    return {
        "abc",
        "argparse",
        "ast",
        "collections",
        "ctypes",
        "dataclasses",
        "enum",
        "importlib",
        "json",
        "logging",
        "os",
        "pathlib",
        "platform",
        "re",
        "sys",
        "typing",
        "urllib",
    }


def _top_level_module(name: str) -> str:
    return name.split(".", 1)[0]


def _local_script_modules() -> set[str]:
    scripts_dir = REPO_ROOT / "scripts"
    names = {"credentials", "_sw", "sw"}
    for path in scripts_dir.glob("*.py"):
        names.add(path.stem)
    return names


class TestNoCredentialDependency:
    def test_dependency_manifest_has_no_credential_storage_entry(self) -> None:
        manifest = json.loads(DEPMANIFEST.read_text(encoding="utf-8"))
        allowed = {_top_level_module(name) for name in manifest.get("allowed", [])}
        vendored = {_top_level_module(name) for name in manifest.get("vendored", {}).keys()}
        declared = allowed | vendored
        for marker in FORBIDDEN_DEPENDENCY_MARKERS:
            assert marker not in declared

    def test_broker_package_imports_no_third_party_module(self) -> None:
        stdlib = _stdlib_modules()
        local_roots = _local_script_modules()
        violations: list[str] = []
        for path in sorted(CREDENTIALS_PACKAGE.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module] if node.module else []
                else:
                    continue
                for name in names:
                    top = _top_level_module(name)
                    if top in stdlib or top in local_roots:
                        continue
                    violations.append(f"{path.name}: {name}")
        assert violations == []

    def test_keystore_backend_imports_cleanly(self) -> None:
        module = importlib.import_module("credentials.keystore_backend")
        assert module.get_keystore_adapter() is not None

    def test_listed_backends_include_keystore_without_extra_packages(self) -> None:
        assert "keystore" in BACKEND_NAMES
        assert backend_module_name("keystore") == "credentials.keystore_backend"
        assert "keystore" in list_backends()
