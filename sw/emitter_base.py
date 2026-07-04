"""Capability-driven emitter base for Shipwright platform trees."""

from __future__ import annotations

import json
import os
import re
import shutil
from abc import ABC, abstractmethod
from pathlib import Path

EMITTABLE_DIRS = ("commands", "skills", "rules", "agents", "providers", "scripts", "communication")

EXCLUDE_DIR_NAMES = {"__pycache__", "test", ".git", "node_modules"}
DEV_ONLY_SCRIPT_RELPATHS = (
    "scripts/copy-to-core.sh",
    "scripts/copy-to-core.py",
    "scripts/snapshot-tree.sh",
    "scripts/snapshot-tree.py",
    "scripts/model-routing-check.sh",
    "scripts/model-routing-check.py",
)

EXCLUDE_REL_PATHS = frozenset({"scripts/install.sh", *DEV_ONLY_SCRIPT_RELPATHS})

SW_REFERENCE_CLOSED_EMIT = (
    "config.schema.json",
    "planning-unit.schema.json",
    "inflight-signal.schema.json",
    "inflight-tuple.schema.json",
    "layout.md",
    "workflow.config.example.json",
    "communication-routing.defaults.json",
    "model-routing.defaults.json",
    "verify-presets.json",
    "capability-index.json",
    "capability-manifest.schema.json",
    "signal-context.schema.json",
    "kernel-classification.json",
    "kernel-classification.md",
    "guidelines.schema.json",
    "guidelines.json",
    "guidelines.md",
)
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
                if path.suffix == ".sh" and dirname == "providers":
                    py_sibling = path.with_suffix(".py")
                    if py_sibling.is_file():
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

    def copy_closed_sw_reference(self, core_root: Path, dest: Path) -> None:
        """Emit the closed sw-reference set for user installs (PRD 018 R12/TR8)."""
        ref_src = core_root / "sw-reference"
        if not ref_src.is_dir():
            return
        ref_dir = dest / "core" / "sw-reference"
        ref_dir.mkdir(parents=True, exist_ok=True)
        for name in SW_REFERENCE_CLOSED_EMIT:
            src = ref_src / name
            if src.is_file():
                shutil.copy2(src, ref_dir / name)

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
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
        return

    def _on_rm_error(func, p: str, exc_info: object) -> None:
        import stat

        if not os.access(p, os.W_OK):
            os.chmod(p, stat.S_IWUSR | stat.S_IRUSR | stat.S_IXUSR)
            func(p)
        else:
            raise exc_info[1]  # type: ignore[index]

    trash = path.parent / f".{path.name}.delete.{os.getpid()}"
    suffix = 0
    while trash.exists():
        suffix += 1
        trash = path.parent / f".{path.name}.delete.{os.getpid()}.{suffix}"
    path.rename(trash)
    shutil.rmtree(trash, onerror=_on_rm_error, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
