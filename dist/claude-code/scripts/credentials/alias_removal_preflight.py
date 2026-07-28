"""Alias-removal preflight for managed repositories (PRD 080 phase 26)."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from credentials.config_surface import IMPLICIT_DEFAULT_TABLE_TARGETS, present_implicit_default_tables
from credentials.doctor import release_blocking_alias_preflight
from credentials.migration_release_gate import (
    TRANSPORTS_NOT_MIGRATED_CODE,
    VERSION_FLOOR_UNPUBLISHED_CODE,
    enumerated_transports_migrated,
    is_version_floor_published,
    migration_release_gate_open,
    repo_root,
)

ENVIRONMENT_SHIM_TARGET = "scripts/_sw/proc.py:host_transport_child_env"


def _implicit_tables_removable() -> tuple[bool, tuple[str, ...]]:
    present = present_implicit_default_tables()
    remaining = tuple(target for target in IMPLICIT_DEFAULT_TABLE_TARGETS if target in present)
    return (not remaining, remaining)


def _environment_shim_present(root: Path) -> bool:
    rel, _, symbol = ENVIRONMENT_SHIM_TARGET.partition(":")
    path = root / rel
    if not path.is_file():
        return False
    source = path.read_text(encoding="utf-8")
    func_name = symbol.split(":", 1)[-1]
    return f"def {func_name}(" in source


def run_alias_removal_preflight(
    root: Path | str,
    *,
    token_env: str,
    selector_path: Path | None = None,
    xdg_base: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Refuse alias removal until local and CI proofs exist and the version floor is published."""
    repo = Path(root).expanduser().resolve()
    base = release_blocking_alias_preflight(
        repo,
        token_env=token_env,
        selector_path=selector_path,
        xdg_base=xdg_base,
        environ=environ,
    )
    version_floor_published = is_version_floor_published(repo)
    transports_migrated, missing_transports = enumerated_transports_migrated(repo)
    gate_open, gate_code = migration_release_gate_open(repo)
    tables_removable, remaining_tables = _implicit_tables_removable()
    shim_present = _environment_shim_present(repo)

    alias_removal_allowed = (
        bool(base.get("aliasRemovalAllowed"))
        and version_floor_published
        and transports_migrated
        and gate_open
    )

    code = base.get("code")
    if alias_removal_allowed:
        verdict = "pass"
        code = None
    elif not version_floor_published:
        verdict = "fail"
        code = VERSION_FLOOR_UNPUBLISHED_CODE
    elif not transports_migrated:
        verdict = "fail"
        code = TRANSPORTS_NOT_MIGRATED_CODE
    else:
        verdict = str(base.get("verdict") or "fail")

    return {
        "verdict": verdict,
        "code": code,
        "aliasRemovalAllowed": alias_removal_allowed,
        "localDeclared": bool(base.get("localDeclared")),
        "ciDeclared": bool(base.get("ciDeclared")),
        "versionFloorPublished": version_floor_published,
        "transportsMigrated": transports_migrated,
        "migrationGateOpen": gate_open,
        "gateCode": gate_code,
        "missingTransports": list(missing_transports),
        "implicitDefaultTablesRemovable": tables_removable,
        "remainingImplicitDefaultTables": list(remaining_tables),
        "environmentShimPresent": shim_present,
        "remediationCommand": base.get("remediationCommand"),
        "remediationScope": base.get("remediationScope"),
        "ambientFinding": base.get("ambientFinding"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="alias-removal-preflight",
        description="Prove local and CI credential resolution before alias removal.",
    )
    parser.add_argument("--root", default=".", help="Managed repository root")
    parser.add_argument("--token-env", default="GITHUB_TOKEN", help="Legacy token env var name")
    parser.add_argument("--selector-path", default=None, help="Optional machine-local selector path")
    args = parser.parse_args(argv)

    result = run_alias_removal_preflight(
        repo_root(Path(args.root)),
        token_env=args.token_env,
        selector_path=Path(args.selector_path) if args.selector_path else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["aliasRemovalAllowed"] else 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
