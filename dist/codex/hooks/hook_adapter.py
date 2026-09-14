"""Codex hook/skill adapter — ships skill bodies and wires lifecycle (PRD 352 R4)."""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path


def _with_skill_name(text: str, name: str) -> str:
    """Ensure Codex SKILL.md frontmatter includes ``name:`` matching the directory."""
    if not text.startswith("---"):
        return f"---\nname: {name}\ndescription: Shipwright {name}\n---\n\n{text}"
    rest = text[3:].lstrip("\n")
    closing = rest.find("\n---")
    if closing == -1:
        return f"---\nname: {name}\n{rest}"
    fm = rest[:closing]
    body = rest[closing:]
    if re.search(r"(?m)^name\s*:", fm):
        return text
    return f"---\nname: {name}\n{fm}{body}"


def copy_command_skills(core_root: Path, dest: Path) -> list[str]:
    """Project core/commands/*.md as Codex skills so ``$sw-init`` is invokable."""
    commands_src = core_root / "commands"
    written: list[str] = []
    if not commands_src.is_dir():
        return written
    skills_dest = dest / "skills"
    skills_dest.mkdir(parents=True, exist_ok=True)
    for cmd in sorted(commands_src.glob("*.md")):
        name = cmd.stem
        out_dir = skills_dest / name
        out_dir.mkdir(parents=True, exist_ok=True)
        body = _with_skill_name(cmd.read_text(encoding="utf-8"), name)
        (out_dir / "SKILL.md").write_text(body, encoding="utf-8")
        written.append(f"skills/{name}/SKILL.md")
    return written


def copy_emittable_content(core_root: Path, dest: Path) -> list[str]:
    """Copy full skill bodies from core into the Codex package tree.

    Codex historically emitted ref stubs only (PRD 349 R21). PRD 352 R4 option (a)
    ships complete skill bodies so packaged installs remain self-contained.
    """
    skills_src = core_root / "skills"
    written: list[str] = []
    if not skills_src.is_dir():
        return written
    skills_dest = dest / "skills"
    skills_dest.mkdir(parents=True, exist_ok=True)
    for skill_dir in sorted(skills_src.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        out_dir = skills_dest / skill_dir.name
        if out_dir.exists():
            shutil.rmtree(out_dir)
        shutil.copytree(
            skill_dir,
            out_dir,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests", "test"),
        )
        written.append(f"skills/{skill_dir.name}/SKILL.md")
    return written


def _core_hooks_dir() -> Path:
    """Resolve core/hooks whether running from platforms/<host>/ or packaged hooks/."""
    here = Path(__file__).resolve().parent
    candidates = (
        here.parents[1] / "core" / "hooks",  # platforms/<host>/hook_adapter.py
        here.parent / "core" / "hooks",  # dist/<host>/hooks/hook_adapter.py
        here / "core" / "hooks",
    )
    for candidate in candidates:
        if (candidate / "before_task_dispatch.py").is_file():
            return candidate
    return candidates[0]


def before_task_dispatch_stdio() -> int:
    """Invoke core before_task_dispatch over stdin/stdout (lifecycle shim)."""
    hooks = _core_hooks_dir()
    if str(hooks) not in sys.path:
        sys.path.insert(0, str(hooks))
    import before_task_dispatch  # noqa: E402

    return int(before_task_dispatch.run_stdio())
