#!/usr/bin/env python3
"""Shared Shipwright scripts-root resolver (PRD 073 R2, R14, R15).

Precedence:
  1. self-repo working-tree scripts/
  2. validated SHIPWRIGHT_SCRIPTS
  3. plugin install (~/.cursor/plugins/local/shipwright/scripts)
  4. consumer fallback (workspace scripts/ with trusted markers)

Untrusted SHIPWRIGHT_SCRIPTS values fail closed — no silent fallback.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

TRUST_MARKERS = ("check-gate.py", "resolve-model-tier.py")
ENV_VAR = "SHIPWRIGHT_SCRIPTS"
PLUGIN_SCRIPTS = Path.home() / ".cursor" / "plugins" / "local" / "shipwright" / "scripts"


class ScriptsResolveError(RuntimeError):
    """Resolver could not locate a trusted scripts root or named script."""


@dataclass(frozen=True)
class ScriptsResolveResult:
    path: Path | None
    source: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "path": str(self.path) if self.path else None,
            "source": self.source,
            "error": self.error,
        }


def is_shipwright_self_repo(workspace: Path) -> bool:
    root = workspace.resolve()
    return (
        (root / "version.txt").is_file()
        and (root / "core" / "sw-reference").is_dir()
        and (root / "scripts" / "check-gate.py").is_file()
    )


def scripts_dir_is_trusted(path: Path) -> bool:
    if not path.is_dir():
        return False
    resolved = path.resolve()
    return all((resolved / marker).is_file() for marker in TRUST_MARKERS)


def validate_env_scripts_root(raw: str) -> tuple[Path | None, str | None]:
    """Validate SHIPWRIGHT_SCRIPTS; fail closed when set but untrusted."""
    value = (raw or "").strip()
    if not value:
        return None, None
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        return None, f"{ENV_VAR} must be an absolute path"
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None, f"{ENV_VAR} path does not exist: {value}"
    if not scripts_dir_is_trusted(resolved):
        return None, f"{ENV_VAR} is not a trusted scripts root: {resolved}"
    return resolved, None


def plugin_install_scripts() -> Path | None:
    if scripts_dir_is_trusted(PLUGIN_SCRIPTS):
        return PLUGIN_SCRIPTS.resolve()
    return None


def consumer_fallback_scripts(workspace: Path) -> Path | None:
    scripts = (workspace / "scripts").resolve()
    if scripts_dir_is_trusted(scripts):
        return scripts
    return None


def resolve_scripts_dir(
    workspace: Path,
    *,
    env: Mapping[str, str] | None = None,
) -> ScriptsResolveResult:
    """Resolve trusted scripts directory for a workspace root."""
    root = workspace.resolve()
    env_map = env if env is not None else os.environ

    if is_shipwright_self_repo(root):
        scripts = root / "scripts"
        if scripts_dir_is_trusted(scripts):
            return ScriptsResolveResult(scripts.resolve(), "self-repo")

    env_raw = str(env_map.get(ENV_VAR, "") or "")
    if env_raw.strip():
        env_path, env_err = validate_env_scripts_root(env_raw)
        if env_err:
            return ScriptsResolveResult(None, None, env_err)
        if env_path is not None:
            return ScriptsResolveResult(env_path, "env")

    plugin = plugin_install_scripts()
    if plugin is not None:
        return ScriptsResolveResult(plugin, "plugin")

    consumer = consumer_fallback_scripts(root)
    if consumer is not None:
        return ScriptsResolveResult(consumer, "consumer")

    return ScriptsResolveResult(None, None, "no trusted scripts root found")


def resolve_script(
    workspace: Path,
    name: str,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    result = resolve_scripts_dir(workspace, env=env)
    if result.error:
        raise ScriptsResolveError(result.error)
    if result.path is None:
        raise ScriptsResolveError("no trusted scripts root found")
    script = result.path / name
    if not script.is_file():
        raise ScriptsResolveError(f"script missing: {name}")
    return script


def ensure_scripts_on_path(workspace: Path, *, env: Mapping[str, str] | None = None) -> Path:
    """Insert resolved scripts dir on sys.path; return the directory used."""
    result = resolve_scripts_dir(workspace, env=env)
    if result.error:
        raise ScriptsResolveError(result.error)
    if result.path is None:
        raise ScriptsResolveError("no trusted scripts root found")
    entry = str(result.path)
    if entry not in sys.path:
        sys.path.insert(0, entry)
    return result.path


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(
            json.dumps(
                {
                    "verdict": "fail",
                    "error": "usage: sw_scripts_resolve.py <workspace-root> [script-name]",
                }
            )
        )
        return 2
    workspace = Path(args[0]).resolve()
    if len(args) == 1:
        result = resolve_scripts_dir(workspace)
        print(json.dumps({"verdict": "ok" if result.path else "fail", **result.to_dict()}, indent=2))
        return 0 if result.path and not result.error else 2
    try:
        script = resolve_script(workspace, args[1])
    except ScriptsResolveError as exc:
        print(json.dumps({"verdict": "fail", "error": str(exc)}, indent=2))
        return 2
    print(json.dumps({"verdict": "ok", "path": str(script)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
