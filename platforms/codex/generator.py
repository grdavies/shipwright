"""Codex adapter generator — core → platforms/codex → dist/codex (PRD 349 R20–R23)."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from hook_registry import build_mcp_config, registered_handlers, unsupported_events
from plugin_manifest import (
    build_adapter_manifest,
    build_native_hooks_document,
    build_plugin_manifest,
    write_manifest,
)

_SW = Path(__file__).resolve().parents[2] / "sw"
if str(_SW) not in sys.path:
    sys.path.insert(0, str(_SW))
from emitter_base import copy_closed_sw_reference_files


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


def _command_ids(core_root: Path) -> list[str]:
    commands = core_root / "commands"
    if not commands.is_dir():
        return []
    return sorted(p.stem for p in commands.glob("*.md"))


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
    command_ids = _command_ids(core)
    handlers = registered_handlers("codex")
    host_events = [h["host_event"] for h in handlers]
    version = _read_version(repo)

    manifest = build_plugin_manifest(
        version=version,
        skill_ids=skill_ids,
        hook_events=host_events,
    )
    write_manifest(out / ".codex-plugin" / "plugin.json", manifest)
    adapter = build_adapter_manifest(
        version=version,
        skill_ids=skill_ids,
        command_ids=command_ids,
        hook_events=host_events,
    )
    (out / ".codex-plugin" / "adapter.json").write_text(
        json.dumps(adapter, indent=2) + "\n", encoding="utf-8"
    )

    # PRD 352 R4: ship full skill bodies (option a) via hook_adapter.copy_emittable_content.
    from hook_adapter import copy_command_skills, copy_emittable_content

    written_skills = copy_emittable_content(core, out)
    written_commands = copy_command_skills(core, out)
    skills_dir = out / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    index = {
        "skills": [
            {
                "id": sid,
                "source": f"core/skills/{sid}",
                "body": f"skills/{sid}/SKILL.md",
            }
            for sid in skill_ids
        ],
        "commands": [
            {
                "id": cid,
                "source": f"core/commands/{cid}.md",
                "body": f"skills/{cid}/SKILL.md",
            }
            for cid in command_ids
        ],
    }
    (skills_dir / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    if skill_ids and not written_skills:
        raise RuntimeError("expected skill bodies to be copied for Codex package")
    if command_ids and not written_commands:
        raise RuntimeError("expected command skills to be projected for Codex package")

    hooks_dir = out / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    (hooks_dir / "hooks.json").write_text(
        json.dumps(build_native_hooks_document(handlers), indent=2) + "\n",
        encoding="utf-8",
    )
    (hooks_dir / "registry.json").write_text(
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
    # Ship lifecycle + adapter so registered events process stdin (PRD 352 R5).
    adapter_src = Path(__file__).resolve().parent
    for name in ("hook_adapter.py", "lifecycle.py"):
        shutil.copy2(adapter_src / name, hooks_dir / name)
    # Core hook module needed by lifecycle shim when running from the package tree.
    core_hooks_src = core / "hooks"
    core_hooks_dest = out / "core" / "hooks"
    if core_hooks_src.is_dir():
        if core_hooks_dest.exists():
            shutil.rmtree(core_hooks_dest)
        shutil.copytree(
            core_hooks_src,
            core_hooks_dest,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests", "test"),
        )
    (hooks_dir / "codex-hook.py").write_text(
        "#!/usr/bin/env python3\n"
        '"""Codex hook entry — processes stdin via lifecycle (PRD 352 R5)."""\n'
        "from __future__ import annotations\n"
        "import sys\n"
        "from pathlib import Path\n"
        "_HERE = Path(__file__).resolve().parent\n"
        "sys.path.insert(0, str(_HERE))\n"
        "import lifecycle  # noqa: E402\n"
        "raise SystemExit(lifecycle.main(sys.argv[1:]))\n",
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
                # Bodies shipped (R4); index retained for ref-index hosts.
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
    copy_closed_sw_reference_files(core, out)

    if enable_mcp:
        mcp = build_mcp_config(repo, enabled=True)
        if mcp:
            mcp_dir = out / "mcp"
            mcp_dir.mkdir(parents=True, exist_ok=True)
            (mcp_dir / "shipwright.json").write_text(
                json.dumps(mcp, indent=2) + "\n", encoding="utf-8"
            )

    # PRD 352 R4: skill bodies are required in packaged Codex output.
    if skill_ids and not any(out.rglob("SKILL.md")):
        raise RuntimeError("Codex package missing skill bodies after emit")

    return out


def emit(core_root: Path, repo_root: Path, dest: Path) -> None:
    """sw generate entrypoint."""
    generate(dest, repo_root=repo_root, core_root=core_root)


if __name__ == "__main__":
    print(generate())
