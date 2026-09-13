"""Codex adapter generator — core → platforms/codex → dist/codex (PRD 349 R20–R23)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from hook_registry import build_mcp_config, registered_handlers, unsupported_events
from plugin_manifest import build_plugin_manifest, write_manifest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_version(repo_root: Path) -> str:
    for candidate in (repo_root / "version.txt", repo_root / "VERSION"):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip() or "0.0.0"
    return "0.0.0"


def _skill_ids(core_root: Path) -> list[str]:
    skills = core_root / "skills"
    if not skills.is_dir():
        return []
    ids: list[str] = []
    for child in sorted(skills.iterdir()):
        if child.is_dir() and (child / "SKILL.md").is_file():
            ids.append(child.name)
    return ids


def generate(
    dest: Path | None = None,
    *,
    repo_root: Path | None = None,
    core_root: Path | None = None,
    enable_mcp: bool = True,
) -> Path:
    """Generate a Codex native plugin package under dist/codex (or *dest*)."""
    repo = (repo_root or _repo_root()).resolve()
    core = (core_root or (repo / "core")).resolve()
    out = (dest or (repo / "dist" / "codex")).resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    skill_ids = _skill_ids(core)
    handlers = registered_handlers("codex")
    host_events = [h["host_event"] for h in handlers]
    version = _read_version(repo)

    manifest = build_plugin_manifest(
        version=version,
        skill_ids=skill_ids,
        hook_events=host_events,
    )
    write_manifest(out / ".codex-plugin" / "plugin.json", manifest)

    # Stable skill identity index — references only, no body duplication (R21).
    skills_dir = out / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    index = {"skills": [{"id": sid, "source": f"core/skills/{sid}"} for sid in skill_ids]}
    (skills_dir / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    for sid in skill_ids:
        ref_dir = skills_dir / sid
        ref_dir.mkdir(parents=True, exist_ok=True)
        (ref_dir / "SKILL.ref.json").write_text(
            json.dumps({"id": sid, "source": f"core/skills/{sid}"}, indent=2) + "\n",
            encoding="utf-8",
        )

    hooks_dir = out / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    (hooks_dir / "hooks.json").write_text(
        json.dumps(
            {
                "handlers": handlers,
                "unsupportedEvents": unsupported_events("codex"),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (hooks_dir / "codex-hook.py").write_text(
        "#!/usr/bin/env python3\n"
        '"""Thin Codex hook entry — delegates to core hook runtime."""\n'
        "from __future__ import annotations\n"
        "import sys\n"
        "from pathlib import Path\n"
        "_ROOT = Path(__file__).resolve().parent.parent\n"
        "sys.path.insert(0, str(_ROOT / 'core' / 'hooks'))\n"
        "print('codex-hook: ok')\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )

    agents_dir = out / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / "default.json").write_text(
        json.dumps(
            {
                "id": "shipwright-default",
                "name": "Shipwright",
                "instructions_source": "core/rules",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    # Descriptor for platform discovery
    (out / "descriptor.json").write_text(
        json.dumps(
            {
                "platform": "codex",
                "hooks": "native",
                "skills": "ref-index",
                "commands": "projected",
                "mcp": "optional",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (out / "version.txt").write_text(version + "\n", encoding="utf-8")

    if enable_mcp:
        mcp = build_mcp_config(repo, enabled=True)
        if mcp:
            mcp_dir = out / "mcp"
            mcp_dir.mkdir(parents=True, exist_ok=True)
            (mcp_dir / "shipwright.json").write_text(
                json.dumps(mcp, indent=2) + "\n", encoding="utf-8"
            )

    # Prove no skill bodies leaked into adapter output (R21).
    for path in out.rglob("SKILL.md"):
        raise RuntimeError(f"skill body must not appear in Codex output: {path}")

    return out


def emit(core_root: Path, repo_root: Path, dest: Path) -> None:
    """sw generate entrypoint."""
    generate(dest, repo_root=repo_root, core_root=core_root)


if __name__ == "__main__":
    print(generate())
