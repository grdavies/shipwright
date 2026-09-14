"""OpenCode adapter generator — distinct package mechanism (PRD 349 R26/R27/R30)."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from hook_registry import (
    build_mcp_config,
    lifecycle_plugin_unsupported_diagnostics,
    registered_handlers,
    unsupported_events,
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
    return [
        child.name
        for child in sorted(skills.iterdir())
        if child.is_dir() and (child / "SKILL.md").is_file()
    ]


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
    """Generate an OpenCode plugin package (not Claude plugin format)."""
    repo = (repo_root or _repo_root()).resolve()
    core = (core_root or (repo / "core")).resolve()
    out = (dest or (repo / "dist" / "opencode")).resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    version = _read_version(repo)
    skill_ids = _skill_ids(core)
    command_ids = _command_ids(core)
    handlers = registered_handlers("opencode")

    package = {
        "name": "shipwright-opencode",
        "version": version,
        "package_mechanism": "opencode-plugin",
        "main": "lifecycle_plugin.ts",
        "shipwright": {
            "skills": [{"id": sid, "source": f"core/skills/{sid}"} for sid in skill_ids],
            "commands": [{"id": cid, "source": f"core/commands/{cid}.md"} for cid in command_ids],
            "agents": [{"id": "shipwright-default", "source": "core/agents"}],
        },
    }
    (out / "opencode.plugin.json").write_text(
        json.dumps(package, indent=2) + "\n", encoding="utf-8"
    )

    shim_src = Path(__file__).resolve().parent / "lifecycle_plugin.ts"
    shutil.copy2(shim_src, out / "lifecycle_plugin.ts")

    hooks_meta = {
        "handlers": handlers,
        "unsupportedEvents": unsupported_events("opencode"),
        "unsupportedDiagnostics": lifecycle_plugin_unsupported_diagnostics(),
    }
    (out / "hooks.json").write_text(json.dumps(hooks_meta, indent=2) + "\n", encoding="utf-8")

    # PRD 352 R4: ship full skill bodies via hook_adapter.copy_emittable_content.
    from hook_adapter import copy_emittable_content

    written_skills = copy_emittable_content(core, out)
    if skill_ids and not written_skills:
        raise RuntimeError("expected skill bodies to be copied for OpenCode package")

    # Lifecycle Python handler (R5) alongside the TS registration shim.
    adapter_src = Path(__file__).resolve().parent
    for name in ("hook_adapter.py", "lifecycle.py"):
        shutil.copy2(adapter_src / name, out / name)
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

    proj = out / "projections"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "skills.json").write_text(
        json.dumps({"skills": package["shipwright"]["skills"]}, indent=2) + "\n",
        encoding="utf-8",
    )
    (proj / "commands.json").write_text(
        json.dumps({"commands": package["shipwright"]["commands"]}, indent=2) + "\n",
        encoding="utf-8",
    )
    (proj / "agents.json").write_text(
        json.dumps({"agents": package["shipwright"]["agents"]}, indent=2) + "\n",
        encoding="utf-8",
    )

    (out / "descriptor.json").write_text(
        json.dumps(
            {
                "platform": "opencode",
                "package_mechanism": "opencode-plugin",
                "hooks": "lifecycle-plugin",
                "skills": "projected",
                "distinct_from_claude_plugin": True,
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

    if (out / ".claude-plugin").exists() or (out / "CLAUDE.md").exists():
        raise RuntimeError("OpenCode package must not reuse Claude plugin paths (R26)")
    # PRD 352 R4: skill bodies are required in packaged OpenCode output.
    if skill_ids and not any(out.rglob("SKILL.md")):
        raise RuntimeError("OpenCode package missing skill bodies after emit")

    return out


def emit(core_root: Path, repo_root: Path, dest: Path) -> None:
    generate(dest, repo_root=repo_root, core_root=core_root)


if __name__ == "__main__":
    print(generate())
