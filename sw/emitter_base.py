"""Capability-driven emitter base for Shipwright platform trees."""

from __future__ import annotations

import json
import re
import shutil
from abc import ABC, abstractmethod
from pathlib import Path

EMITTABLE_DIRS = ("commands", "skills", "rules", "agents", "providers", "scripts", "communication")

EXCLUDE_DIR_NAMES = {"__pycache__", "test", ".git", "node_modules"}
EXCLUDE_REL_PATHS = frozenset({"scripts/install.sh"})
EXCLUDE_SUFFIXES = (".pyc",)

CURSOR_PLUGIN_ROOT = "${CURSOR_PLUGIN_ROOT}"
CLAUDE_PLUGIN_ROOT = "${CLAUDE_PLUGIN_ROOT}"
CURSOR_FALLBACK_RE = re.compile(
    r"\$HOME/\.cursor/plugins/local/shipwright"
)


class EmitterError(Exception):
    """Raised when generation cannot satisfy the platform descriptor."""


def read_version(repo_root: Path) -> str:
    """Read the bare semver string from repo-root version.txt."""
    path = repo_root / "version.txt"
    if not path.is_file():
        raise EmitterError(f"missing version source: {path}")
    version = path.read_text(encoding="utf-8").strip()
    if not version:
        raise EmitterError(f"empty version source: {path}")
    return version


class EmitterBase(ABC):
    """Copy emittable core/ content and apply platform-specific wiring."""

    platform_id: str

    def __init__(self, descriptor: dict) -> None:
        self.descriptor = descriptor
        self.platform_id = str(descriptor.get("platform", ""))

    def validate_descriptor(self) -> None:
        """Subclasses enforce supported capability flags (R4)."""
        return

    @abstractmethod
    def emit(self, core_root: Path, repo_root: Path, dest: Path) -> None:
        """Write the full platform tree to dest."""

    def copy_emittable_content(self, core_root: Path, dest: Path) -> list[str]:
        """Copy verbatim core subtrees; return relative paths written."""
        written: list[str] = []
        for dirname in EMITTABLE_DIRS:
            src = core_root / dirname
            if not src.is_dir():
                continue
            for path in sorted(src.rglob("*")):
                if not path.is_file():
                    continue
                rel = path.relative_to(src)
                parts = rel.parts
                if any(p in EXCLUDE_DIR_NAMES for p in parts):
                    continue
                out_rel = f"{dirname}/{rel.as_posix()}"
                if out_rel in EXCLUDE_REL_PATHS:
                    continue
                if path.suffix in EXCLUDE_SUFFIXES:
                    continue
                if dirname == "scripts" and parts and parts[0] == "test":
                    continue
                out_path = dest / out_rel
                out_path.parent.mkdir(parents=True, exist_ok=True)
                content = path.read_bytes()
                content = self.transform_body(content, out_rel)
                out_path.write_bytes(content)
                written.append(out_rel)
        return written

    def transform_body(self, content: bytes, _rel_path: str) -> bytes:
        text = content.decode("utf-8")
        text = self.substitute_plugin_root_env(text)
        return text.encode("utf-8")

    def substitute_plugin_root_env(self, text: str) -> str:
        target = self.plugin_root_env_name()
        if target == "CURSOR_PLUGIN_ROOT":
            return text
        text = re.sub(
            r"\$\{CURSOR_PLUGIN_ROOT(:-[^}]+)?\}",
            lambda m: f"${{{target}{m.group(1) or ''}}}",
            text,
        )
        text = CURSOR_FALLBACK_RE.sub(
            "$HOME/.claude/plugins/local/shipwright",
            text,
        )
        return text

    @abstractmethod
    def plugin_root_env_name(self) -> str:
        """Env var name for plugin root in emitted bodies."""

    @staticmethod
    def load_descriptor(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
