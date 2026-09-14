#!/usr/bin/env python3
"""Unified Shipwright installer with Codex/OpenCode choices (PRD 349 R43–R45).

Dispatches ``platforms/<adapter>/generator.py`` for selected adapters, preserves
existing adapter installs, snapshots settings before writes, and resolves
duplicate skill projections to the canonical ``core`` source.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any


ADAPTER_CHOICES = ("cursor", "claude-code", "codex", "opencode")

SETTINGS_WATCHLIST = (
    ".shipwright/settings.json",
    ".cursor/settings.json",
    ".claude/settings.json",
    ".codex/settings.json",
    ".opencode/settings.json",
)


class InstallerError(RuntimeError):
    """Fail-closed installer errors."""


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def available_choices() -> list[str]:
    return list(ADAPTER_CHOICES)


def _load_generator(adapter: str):
    gen_path = repo_root() / "platforms" / adapter / "generator.py"
    if not gen_path.is_file():
        raise InstallerError(f"no generator for adapter {adapter!r} at {gen_path}")
    spec = importlib.util.spec_from_file_location(f"sw_generator_{adapter}", gen_path)
    if spec is None or spec.loader is None:
        raise InstallerError(f"cannot load generator for {adapter}")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(gen_path.parent))
    spec.loader.exec_module(mod)
    if not hasattr(mod, "generate"):
        raise InstallerError(f"generator for {adapter} missing generate()")
    return mod


def snapshot_settings(root: Path) -> dict[str, str]:
    snap: dict[str, str] = {}
    for rel in SETTINGS_WATCHLIST:
        path = root / rel
        snap[rel] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""
    return snap


def diff_settings(before: dict[str, str], after: dict[str, str]) -> list[str]:
    diffs: list[str] = []
    for key in sorted(set(before) | set(after)):
        if before.get(key, "") != after.get(key, ""):
            diffs.append(f"{key}: {before.get(key, '')!r} -> {after.get(key, '')!r}")
    return diffs


def _hash_tree(path: Path) -> str:
    if not path.exists():
        return ""
    parts: list[str] = []
    for f in sorted(path.rglob("*")):
        if f.is_file():
            rel = f.relative_to(path).as_posix()
            digest = hashlib.sha256(f.read_bytes()).hexdigest()
            parts.append(f"{rel}:{f.stat().st_size}:{digest}")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def _other_adapter_roots(install_root: Path, selected: str) -> dict[str, str]:
    snaps: dict[str, str] = {}
    for adapter in ADAPTER_CHOICES:
        if adapter == selected:
            continue
        path = install_root / adapter
        if path.exists():
            snaps[adapter] = _hash_tree(path)
    return snaps


def _skill_projection_ids(dist_root: Path) -> set[str]:
    ids: set[str] = set()
    index = dist_root / "skills" / "index.json"
    if index.is_file():
        data = json.loads(index.read_text(encoding="utf-8"))
        for row in data.get("skills") or []:
            if isinstance(row, dict) and row.get("id"):
                ids.add(str(row["id"]))
    proj = dist_root / "projections" / "skills.json"
    if proj.is_file():
        data = json.loads(proj.read_text(encoding="utf-8"))
        for row in data.get("skills") or []:
            if isinstance(row, dict) and row.get("id"):
                ids.add(str(row["id"]))
    skills_dir = dist_root / "skills"
    if skills_dir.is_dir():
        for child in skills_dir.iterdir():
            if child.is_dir() and child.name not in {"__pycache__"}:
                ids.add(child.name)
    return ids


def detect_duplicate_skills(adapter_dists: dict[str, Path]) -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    for adapter, dist in adapter_dists.items():
        for sid in _skill_projection_ids(dist):
            owners.setdefault(sid, []).append(adapter)
    return {sid: ads for sid, ads in owners.items() if len(ads) > 1}


def load_adapter_descriptor(repo: Path, adapter: str) -> dict[str, Any]:
    """Load ``platforms/<adapter>/descriptor.json`` when present."""
    path = repo / "platforms" / adapter / "descriptor.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def adapter_skills_mode(repo: Path, adapter: str) -> str | None:
    """Return descriptor ``skills`` mode (e.g. ``native``, ``ref-index``)."""
    value = load_adapter_descriptor(repo, adapter).get("skills")
    return str(value) if isinstance(value, str) and value.strip() else None


def required_artifact_paths(repo: Path, adapter: str, dist: Path) -> set[Path]:
    """Resolve per-adapter required artifacts that must not be deleted (R8).

    Reads ``platforms/<adapter>/required-artifacts.json`` glob patterns when
    present, and always treats native skill bodies (``skills/*/SKILL.md``) as
    required for ``skills: native`` adapters.
    """
    required: set[Path] = set()
    manifest = repo / "platforms" / adapter / "required-artifacts.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        patterns = []
        if isinstance(data, dict):
            raw = data.get("paths") if data.get("paths") is not None else data.get("artifacts")
            if isinstance(raw, list):
                patterns = [str(p) for p in raw if str(p).strip()]
        for pattern in patterns:
            for match in dist.glob(pattern):
                if match.is_file():
                    required.add(match.resolve())
    if adapter_skills_mode(repo, adapter) == "native":
        skills_root = dist / "skills"
        if skills_root.is_dir():
            for skill_md in skills_root.glob("*/SKILL.md"):
                if skill_md.is_file():
                    required.add(skill_md.resolve())
    return required


def resolve_duplicate_skills(
    repo: Path,
    adapter_dists: dict[str, Path],
) -> list[dict[str, Any]]:
    """Keep canonical core projection; remove stale duplicate bodies (R45).

    PRD 352 R7: skip ``unlink()`` for adapters whose descriptor declares
    ``skills: native``. PRD 352 R8: refuse (InstallerError) when a planned
    deletion would remove a required artifact from the per-adapter manifest.
    """
    actions: list[dict[str, Any]] = []
    planned: list[tuple[str, str, Path, str]] = []
    duplicates = detect_duplicate_skills(adapter_dists)
    for skill_id, adapters in sorted(duplicates.items()):
        core_skill = repo / "core" / "skills" / skill_id / "SKILL.md"
        canonical = str(core_skill) if core_skill.is_file() else f"core/skills/{skill_id}"
        for adapter in adapters:
            dist = adapter_dists[adapter]
            body = dist / "skills" / skill_id / "SKILL.md"
            if body.is_file():
                if adapter_skills_mode(repo, adapter) == "native":
                    actions.append(
                        {
                            "skill_id": skill_id,
                            "adapter": adapter,
                            "action": "preserved_native_body",
                            "kept": canonical,
                        }
                    )
                else:
                    planned.append((skill_id, adapter, body, canonical))
            ref = dist / "skills" / skill_id / "SKILL.ref.json"
            skill_dir = dist / "skills" / skill_id
            # Native adapters keep their bodies; still allow a core ref marker.
            if skill_dir.is_dir() and not ref.is_file():
                ref.write_text(
                    json.dumps({"id": skill_id, "source": f"core/skills/{skill_id}"}, indent=2)
                    + "\n",
                    encoding="utf-8",
                )
                actions.append(
                    {
                        "skill_id": skill_id,
                        "adapter": adapter,
                        "action": "wrote_core_ref",
                        "kept": canonical,
                    }
                )

    violations: list[dict[str, str]] = []
    for skill_id, adapter, body, _canonical in planned:
        required = required_artifact_paths(repo, adapter, adapter_dists[adapter])
        if body.resolve() in required:
            violations.append(
                {
                    "skill_id": skill_id,
                    "adapter": adapter,
                    "path": str(body),
                }
            )
    if violations:
        raise InstallerError(
            "required artifact would be removed by duplicate-skill resolution (R8): "
            + json.dumps(violations)
        )

    for skill_id, adapter, body, canonical in planned:
        if body.is_file():
            body.unlink()
            actions.append(
                {
                    "skill_id": skill_id,
                    "adapter": adapter,
                    "action": "removed_stale_body",
                    "kept": canonical,
                }
            )
    return actions


def install_adapters(
    adapters: list[str],
    *,
    repo: Path | None = None,
    install_root: Path | None = None,
    dest_overrides: dict[str, Path] | None = None,
) -> dict[str, Any]:
    """Generate and stage selected adapters without disturbing existing ones."""
    repo = (repo or repo_root()).resolve()
    install_root = (install_root or (repo / ".shipwright" / "adapters")).resolve()
    install_root.mkdir(parents=True, exist_ok=True)
    dest_overrides = dest_overrides or {}

    selected = [a.strip().lower() for a in adapters]
    for a in selected:
        if a not in ADAPTER_CHOICES:
            raise InstallerError(f"unsupported adapter choice: {a}")

    # Adapters without a generator (cursor/claude-code) still appear as choices;
    # for those we only ensure the choice is advertised and skip generation here.
    generatable = {"codex", "opencode"}

    settings_before = snapshot_settings(repo)
    sibling_before: dict[str, dict[str, str]] = {
        a: _other_adapter_roots(install_root, a) for a in selected
    }

    generated: dict[str, Path] = {}
    for adapter in selected:
        if adapter not in generatable:
            # Preserve existing install; choice is still offered (R43).
            existing = dest_overrides.get(adapter) or (install_root / adapter)
            if existing.is_dir():
                generated[adapter] = existing
            continue

        staging = install_root / f".staging-{adapter}"
        if staging.exists():
            shutil.rmtree(staging)
        mod = _load_generator(adapter)
        out = mod.generate(staging, repo_root=repo, core_root=repo / "core")
        final = dest_overrides.get(adapter) or (install_root / adapter)
        if final.exists():
            shutil.rmtree(final)
        shutil.move(str(out), str(final))
        generated[adapter] = final

        sibling_after = _other_adapter_roots(install_root, adapter)
        if sibling_after != sibling_before[adapter]:
            raise InstallerError(
                "unexpected modification to existing adapter installation while "
                f"installing {adapter}: before={sibling_before[adapter]} after={sibling_after}"
            )

    settings_after = snapshot_settings(repo)
    setting_diffs = diff_settings(settings_before, settings_after)
    if setting_diffs:
        raise InstallerError(
            "unexpected settings change during install (R44); aborting:\n"
            + "\n".join(setting_diffs)
        )

    all_dists = {a: install_root / a for a in ADAPTER_CHOICES if (install_root / a).is_dir()}
    all_dists.update(generated)
    try:
        dedupe_actions = resolve_duplicate_skills(repo, all_dists)
    except InstallerError as exc:
        # R8: required-artifact preservation failure is a fail verdict, not a crash.
        return {
            "verdict": "fail",
            "error": str(exc),
            "installed": sorted(generated),
            "paths": {k: str(v) for k, v in generated.items()},
            "choices": list(ADAPTER_CHOICES),
            "duplicate_skill_actions": [],
            "settings_preserved": True,
        }

    return {
        "verdict": "pass",
        "installed": sorted(generated),
        "paths": {k: str(v) for k, v in generated.items()},
        "choices": list(ADAPTER_CHOICES),
        "duplicate_skill_actions": dedupe_actions,
        "settings_preserved": True,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Unified Shipwright adapter installer (PRD 349).")
    p.add_argument(
        "--adapters",
        nargs="+",
        required=True,
        choices=list(ADAPTER_CHOICES),
        help="Adapters to install (codex/opencode are new choices alongside cursor/claude-code)",
    )
    p.add_argument("--repo", default=None, help="Repository root (default: checkout root)")
    p.add_argument(
        "--install-root",
        default=None,
        help="Adapter install root (default: .shipwright/adapters)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = install_adapters(
            list(args.adapters),
            repo=Path(args.repo) if args.repo else None,
            install_root=Path(args.install_root) if args.install_root else None,
        )
    except InstallerError as exc:
        print(json.dumps({"verdict": "fail", "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
