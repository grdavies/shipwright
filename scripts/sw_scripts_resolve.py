#!/usr/bin/env python3
"""Shared Shipwright scripts-root resolver (PRD 073 R2, R14, R15; PRD 078 R4, R5, R10).

Precedence:
  1. self-repo working-tree scripts/
  2. validated SHIPWRIGHT_SCRIPTS
  3. plugin install (local, then marketplace/cache roots)
  4. consumer context without plugin — fail closed (no workspace scripts/)

Untrusted SHIPWRIGHT_SCRIPTS values fail closed — no silent fallback.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

TRUST_MARKERS = ("check-gate.py", "resolve-model-tier.py")
DIST_SHIM_MARKER = "sw-run.py"
ENV_VAR = "SHIPWRIGHT_SCRIPTS"
PLUGIN_LOCAL_SCRIPTS = Path.home() / ("." + "cursor") / "plugins" / "local" / "shipwright" / "scripts"
PLUGIN_SCRIPTS = PLUGIN_LOCAL_SCRIPTS
PLUGIN_CACHE_ROOT = Path.home() / ("." + "cursor") / "plugins" / "cache"
CONSUMER_NO_PLUGIN_ERROR = (
    "Shipwright plugin not installed; install the plugin locally "
    "(python3 scripts/install.py from the Shipwright source repo) "
    "or set SHIPWRIGHT_SCRIPTS to a trusted absolute scripts root"
)


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
    try:
        from repository_context import is_plugin_self_repository

        return is_plugin_self_repository(workspace)
    except Exception:
        return False


def is_dist_only_plugin_scripts(path: Path) -> bool:
    """True when ``scripts/`` contains only the zipapp shim (pure install)."""
    if not path.is_dir():
        return False
    files = [item for item in path.rglob("*") if item.is_file()]
    return files == [path / DIST_SHIM_MARKER]


def _operator_trust_store_path(workspace: Path) -> Path:
    from graph.packages.trust import DEFAULT_TRUST_ANCHOR_PATH

    candidate = workspace / ("." + "cursor") / "sw-package-trust-anchors.json"
    if candidate.is_file():
        return candidate
    return workspace / DEFAULT_TRUST_ANCHOR_PATH


def dist_trust_verdict_for_install(
    install_root: Path,
    *,
    workspace: Path,
) -> dict[str, str]:
    from graph.packages.trust import (
        TrustAnchorError,
        load_trust_anchors,
        resolve_dist_trust_verdict,
    )

    trust_path = _operator_trust_store_path(workspace)
    if not trust_path.is_file():
        raise TrustAnchorError(f"operator trust store missing: {trust_path}")
    trust_store = load_trust_anchors(trust_path)
    verdict = resolve_dist_trust_verdict(install_root, trust_store=trust_store)
    return {
        "verdict": str(verdict.get("verdict") or ""),
        "trustDigest": str(verdict.get("trustDigest") or ""),
        "anchorId": str(verdict.get("anchorId") or ""),
        "signerKeyId": str(verdict.get("signerKeyId") or ""),
    }


def scripts_dir_is_trusted(path: Path, *, workspace: Path | None = None) -> bool:
    if not path.is_dir():
        return False
    resolved = path.resolve()
    if all((resolved / marker).is_file() for marker in TRUST_MARKERS):
        return True
    if not is_dist_only_plugin_scripts(resolved):
        return False
    root = workspace.resolve() if workspace is not None else Path.cwd()
    try:
        verdict = dist_trust_verdict_for_install(resolved.parent, workspace=root)
    except Exception:
        return False
    return verdict.get("verdict") == "ok"


def _lexical_parent(path: Path) -> Path:
    """Parent of ``path`` without following a symlink on ``path`` itself."""
    parent = path.parent
    try:
        return parent.resolve()
    except OSError:
        return parent


def _is_contained(resolved: Path, root: Path) -> bool:
    try:
        resolved.relative_to(root)
    except ValueError:
        return False
    return True


def plugin_scripts_contained(candidate: Path) -> bool:
    """True when ``candidate.resolve()`` stays inside a plugin install tree.

    Trust markers are not enough: a ``scripts`` symlink that escapes
    ``~/.cursor/plugins/{local,cache}/…/shipwright`` must fail closed.
    Containment uses the lexical plugin parent so a dangling or escaped
    ``PLUGIN_LOCAL_SCRIPTS`` symlink cannot redefine the allowed root.
    """
    try:
        resolved = candidate.resolve()
    except OSError:
        return False
    local_root = _lexical_parent(PLUGIN_LOCAL_SCRIPTS)
    if _is_contained(resolved, local_root):
        return True
    try:
        cache_root = PLUGIN_CACHE_ROOT.resolve() if PLUGIN_CACHE_ROOT.exists() else PLUGIN_CACHE_ROOT
    except OSError:
        cache_root = PLUGIN_CACHE_ROOT
    if not _is_contained(resolved, cache_root):
        return False
    return "shipwright" in resolved.parts


def compute_scripts_root_hash(scripts_root: Path, *, workspace: Path | None = None) -> str:
    """Stable SHA256 digest over the resolved scripts root trust binding."""
    resolved = scripts_root.resolve()
    if all((resolved / marker).is_file() for marker in TRUST_MARKERS):
        lines: list[str] = []
        for marker in sorted(TRUST_MARKERS):
            marker_path = resolved / marker
            digest = hashlib.sha256(marker_path.read_bytes()).hexdigest()
            lines.append(f"{marker}:{digest}")
        return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    if is_dist_only_plugin_scripts(resolved):
        root = workspace.resolve() if workspace is not None else Path.cwd()
        verdict = dist_trust_verdict_for_install(resolved.parent, workspace=root)
        if verdict.get("verdict") != "ok":
            raise ScriptsResolveError("dist trust anchor invalid")
        digest = verdict.get("trustDigest")
        if not digest:
            raise ScriptsResolveError("dist trust digest missing")
        return str(digest)
    raise ScriptsResolveError("trust marker missing: check-gate.py")


def scripts_root_binding(
    workspace: Path,
    *,
    env: Mapping[str, str] | None = None,
    executor: Path | None = None,
) -> dict[str, str]:
    """Resolve trusted scripts root and return a durable binding record."""
    result = resolve_scripts_dir(workspace, env=env, executor=executor)
    if result.error:
        raise ScriptsResolveError(result.error)
    if result.path is None:
        raise ScriptsResolveError("no trusted scripts root found")
    return {
        "root": str(result.path.resolve()),
        "source": str(result.source or ""),
        "hash": compute_scripts_root_hash(result.path, workspace=workspace),
    }


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


def iter_plugin_script_candidates() -> Iterable[Path]:
    """Probe local install first, then marketplace/cache plugin roots."""
    yield PLUGIN_LOCAL_SCRIPTS
    if not PLUGIN_CACHE_ROOT.is_dir():
        return
    for scripts in sorted(PLUGIN_CACHE_ROOT.glob("*/*/*/scripts")):
        if scripts.parent.parent.name == "shipwright":
            yield scripts


def plugin_install_scripts(*, workspace: Path | None = None) -> Path | None:
    root = workspace.resolve() if workspace is not None else Path.cwd()
    for candidate in iter_plugin_script_candidates():
        if not plugin_scripts_contained(candidate):
            continue
        if scripts_dir_is_trusted(candidate, workspace=root):
            return candidate.resolve()
    return None


def consumer_fallback_scripts(workspace: Path) -> Path | None:
    scripts = (workspace / "scripts").resolve()
    if scripts_dir_is_trusted(scripts):
        return scripts
    return None


def executor_scripts_dir(executor: Path | None) -> Path | None:
    if executor is None:
        return None
    scripts = executor.resolve().parent
    if scripts_dir_is_trusted(scripts):
        return scripts
    return None


def resolve_scripts_dir(
    workspace: Path,
    *,
    env: Mapping[str, str] | None = None,
    executor: Path | None = None,
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

    plugin = plugin_install_scripts(workspace=root)
    if plugin is not None:
        source = "plugin-local" if plugin == PLUGIN_LOCAL_SCRIPTS.resolve() else "plugin-cache"
        if is_dist_only_plugin_scripts(plugin):
            source = f"{source}-dist"
        return ScriptsResolveResult(plugin, source)

    if not is_shipwright_self_repo(root):
        invoked = executor_scripts_dir(executor)
        if invoked is not None:
            return ScriptsResolveResult(invoked, "executor")
        return ScriptsResolveResult(None, None, CONSUMER_NO_PLUGIN_ERROR)

    consumer = consumer_fallback_scripts(root)
    if consumer is not None:
        return ScriptsResolveResult(consumer, "consumer")

    invoked = executor_scripts_dir(executor)
    if invoked is not None:
        return ScriptsResolveResult(invoked, "executor")

    return ScriptsResolveResult(None, None, "no trusted scripts root found")


def resolve_script(
    workspace: Path,
    name: str,
    *,
    env: Mapping[str, str] | None = None,
    executor: Path | None = None,
) -> Path:
    if executor is None:
        import inspect

        frame = inspect.currentframe()
        if frame and frame.f_back:
            caller = frame.f_back.f_globals.get("__file__")
            if isinstance(caller, str) and caller:
                executor = Path(caller)
    result = resolve_scripts_dir(workspace, env=env, executor=executor)
    if result.error:
        raise ScriptsResolveError(result.error)
    if result.path is None:
        raise ScriptsResolveError("no trusted scripts root found")
    script = result.path / name
    if not script.is_file():
        raise ScriptsResolveError(f"script missing: {name}")
    return script


def ensure_scripts_on_path(
    workspace: Path,
    *,
    env: Mapping[str, str] | None = None,
    executor: Path | None = None,
) -> Path:
    """Insert resolved scripts dir on sys.path; return the directory used."""
    result = resolve_scripts_dir(workspace, env=env, executor=executor)
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
