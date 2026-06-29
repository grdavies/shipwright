#!/usr/bin/env python3
"""PRD 034 Phase 3 — pluggable planning.store interface + backend registry (R5, R6, R18, R11, R25)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from host_lib import load_workflow_config
from memory_sot import resolve_memory_provider

SCRIPT_DIR = Path(__file__).resolve().parent

DEFAULT_BACKEND = "in-repo-public"
SHIPPED_BACKENDS = frozenset({"in-repo-public", "local-synced", "memory"})
DEFERRED_BACKENDS = frozenset({"private-repo", "encryption-at-rest"})
ALL_BACKENDS = SHIPPED_BACKENDS | DEFERRED_BACKENDS

BANNED_MEMORY_CLASSES = frozenset({"discussion", "progress"})
RAW_TRANSCRIPT_MARKERS = (
    re.compile(r"(?i)\buser:\s"),
    re.compile(r"(?i)\bassistant:\s"),
    re.compile(r"(?i)\braw transcript\b"),
    re.compile(r"(?i)\bagent transcript\b"),
)

CLOUD_SYNC_ROOTS = (
    "Dropbox",
    "Library/Mobile Documents/com~apple~CloudDocs",
    "OneDrive",
    "Google Drive",
)


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def git_root(start: Path | None = None) -> Path:
    cwd = start or Path.cwd()
    proc = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail("not a git repository")
    return Path(proc.stdout.strip())


def planning_section(cfg: dict[str, Any]) -> dict[str, Any]:
    planning = cfg.get("planning")
    return planning if isinstance(planning, dict) else {}


def store_section(cfg: dict[str, Any]) -> dict[str, Any]:
    store = planning_section(cfg).get("store")
    return store if isinstance(store, dict) else {}


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def log_operation(
    op: str,
    unit_id: str,
    body_path: str,
    content: str | None,
    backend: str,
    *,
    stream: Any = None,
) -> None:
    digest = content_hash(content) if content is not None else "none"
    line = json.dumps(
        {
            "planningStore": True,
            "op": op,
            "unitId": unit_id,
            "path": body_path,
            "hash": digest,
            "backend": backend,
        },
        ensure_ascii=False,
    )
    target = stream if stream is not None else sys.stderr
    print(line, file=target)


def redact_content(content: str) -> str:
    proc = subprocess.run(
        [str(SCRIPT_DIR / "memory-redact.sh")],
        input=content,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail(proc.stderr.strip() or "memory-redact failed", code="redact-failed")
    return proc.stdout


def contains_raw_transcript(content: str) -> bool:
    return any(marker.search(content) for marker in RAW_TRANSCRIPT_MARKERS)


@dataclass(frozen=True)
class StoreResult:
    verdict: str
    unit_id: str
    body_path: str
    backend: str
    content: str | None = None
    hash: str | None = None
    reason: str | None = None
    inert: bool = False

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "verdict": self.verdict,
            "unitId": self.unit_id,
            "bodyPath": self.body_path,
            "backend": self.backend,
        }
        if self.content is not None:
            out["content"] = self.content
        if self.hash is not None:
            out["hash"] = self.hash
        if self.reason is not None:
            out["reason"] = self.reason
        if self.inert:
            out["inert"] = True
        return out


class PlanningStoreBackend(ABC):
    backend_id: str

    def __init__(self, root: Path, cfg: dict[str, Any]) -> None:
        self.root = root
        self.cfg = cfg

    @abstractmethod
    def put(self, unit_id: str, body_path: str, content: str, *, content_class: str | None = None) -> StoreResult:
        raise NotImplementedError

    @abstractmethod
    def get(self, unit_id: str, body_path: str) -> StoreResult:
        raise NotImplementedError

    @abstractmethod
    def exists(self, unit_id: str, body_path: str) -> StoreResult:
        raise NotImplementedError

    @abstractmethod
    def materialize(self, unit_id: str, body_path: str, dest_path: Path) -> StoreResult:
        raise NotImplementedError


class InRepoPublicBackend(PlanningStoreBackend):
    backend_id = "in-repo-public"

    def _resolve_path(self, body_path: str) -> Path:
        path = (self.root / body_path).resolve()
        root_resolved = self.root.resolve()
        if root_resolved not in path.parents and path != root_resolved:
            fail("body path escapes repository root", bodyPath=body_path)
        return path

    def put(self, unit_id: str, body_path: str, content: str, *, content_class: str | None = None) -> StoreResult:
        path = self._resolve_path(body_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        log_operation("put", unit_id, body_path, content, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=content, hash=content_hash(content))

    def get(self, unit_id: str, body_path: str) -> StoreResult:
        path = self._resolve_path(body_path)
        if not path.is_file():
            return StoreResult("missing", unit_id, body_path, self.backend_id, reason="not-found")
        content = path.read_text(encoding="utf-8")
        log_operation("get", unit_id, body_path, content, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=content, hash=content_hash(content))

    def exists(self, unit_id: str, body_path: str) -> StoreResult:
        path = self._resolve_path(body_path)
        present = path.is_file()
        log_operation("exists", unit_id, body_path, None, self.backend_id)
        return StoreResult("ok" if present else "missing", unit_id, body_path, self.backend_id, reason=None if present else "not-found")

    def materialize(self, unit_id: str, body_path: str, dest_path: Path) -> StoreResult:
        src = self._resolve_path(body_path)
        if not src.is_file():
            return StoreResult("missing", unit_id, body_path, self.backend_id, reason="not-found")
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest_path)
        content = dest_path.read_text(encoding="utf-8")
        log_operation("materialize", unit_id, body_path, content, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=content, hash=content_hash(content))


class LocalSyncedBackend(PlanningStoreBackend):
    backend_id = "local-synced"

    def synced_root(self) -> Path:
        store = store_section(self.cfg)
        local = store.get("localSynced")
        if not isinstance(local, dict):
            fail("planning.store.localSynced.path is required for local-synced backend")
        raw = local.get("path")
        if not isinstance(raw, str) or not raw.strip():
            fail("planning.store.localSynced.path is required for local-synced backend")
        return Path(os.path.expanduser(raw.strip())).resolve()

    def _unit_path(self, unit_id: str) -> Path:
        safe_id = re.sub(r"[^a-zA-Z0-9._-]+", "_", unit_id)
        return self.synced_root() / f"{safe_id}.md"

    def put(self, unit_id: str, body_path: str, content: str, *, content_class: str | None = None) -> StoreResult:
        path = self._unit_path(unit_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        log_operation("put", unit_id, body_path, content, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=content, hash=content_hash(content))

    def get(self, unit_id: str, body_path: str) -> StoreResult:
        path = self._unit_path(unit_id)
        if not path.is_file():
            return StoreResult("missing", unit_id, body_path, self.backend_id, reason="not-found")
        content = path.read_text(encoding="utf-8")
        log_operation("get", unit_id, body_path, content, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=content, hash=content_hash(content))

    def exists(self, unit_id: str, body_path: str) -> StoreResult:
        present = self._unit_path(unit_id).is_file()
        log_operation("exists", unit_id, body_path, None, self.backend_id)
        return StoreResult("ok" if present else "missing", unit_id, body_path, self.backend_id, reason=None if present else "not-found")

    def materialize(self, unit_id: str, body_path: str, dest_path: Path) -> StoreResult:
        src = self._unit_path(unit_id)
        if not src.is_file():
            return StoreResult("missing", unit_id, body_path, self.backend_id, reason="not-found")
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest_path)
        content = dest_path.read_text(encoding="utf-8")
        log_operation("materialize", unit_id, body_path, content, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=content, hash=content_hash(content))


class MemoryBackend(PlanningStoreBackend):
    backend_id = "memory"

    def memory_project(self) -> str:
        memory = self.cfg.get("memory")
        if isinstance(memory, dict) and isinstance(memory.get("project"), str) and memory["project"].strip():
            return memory["project"].strip()
        return self.root.name

    def provider(self) -> str | None:
        return resolve_memory_provider(self.root, self.cfg)

    def _store_dir(self) -> Path:
        if self.provider() is None:
            fail("memory backend degraded: no memory provider configured", verdict="degraded")
        return self.root / ".cursor" / "sw-memory" / "planning-bodies" / self.memory_project()

    def _unit_path(self, unit_id: str) -> Path:
        safe_id = re.sub(r"[^a-zA-Z0-9._-]+", "_", unit_id)
        return self._store_dir() / f"{safe_id}.md"

    def _validate_class(self, content_class: str | None) -> None:
        if content_class and content_class.lower() in BANNED_MEMORY_CLASSES:
            fail(f"memory backend bans content class: {content_class}", code="banned-class")

    def _validate_content(self, content: str) -> None:
        if contains_raw_transcript(content):
            fail("raw transcript content refused by memory backend", code="raw-transcript")

    def put(self, unit_id: str, body_path: str, content: str, *, content_class: str | None = None) -> StoreResult:
        self._validate_class(content_class)
        self._validate_content(content)
        redacted = redact_content(content)
        store_dir = self._store_dir()
        store_dir.mkdir(parents=True, exist_ok=True)
        target = self._unit_path(unit_id)
        frontmatter = (
            "---\n"
            f"unitId: {unit_id}\n"
            f"bodyPath: {body_path}\n"
            f"project: {self.memory_project()}\n"
            f"provider: {self.provider() or 'none'}\n"
            "---\n"
        )
        target.write_text(frontmatter + redacted, encoding="utf-8")
        log_operation("put", unit_id, body_path, redacted, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=redacted, hash=content_hash(redacted))

    def get(self, unit_id: str, body_path: str) -> StoreResult:
        path = self._unit_path(unit_id)
        if not path.is_file():
            if self.provider() is None:
                return StoreResult("degraded", unit_id, body_path, self.backend_id, reason="no-provider")
            return StoreResult("missing", unit_id, body_path, self.backend_id, reason="not-found")
        raw = path.read_text(encoding="utf-8")
        body = raw.split("---", 2)[-1].lstrip("\n") if raw.startswith("---") else raw
        redacted = redact_content(body)
        log_operation("get", unit_id, body_path, redacted, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=redacted, hash=content_hash(redacted))

    def exists(self, unit_id: str, body_path: str) -> StoreResult:
        present = self._unit_path(unit_id).is_file()
        log_operation("exists", unit_id, body_path, None, self.backend_id)
        if not present and self.provider() is None:
            return StoreResult("degraded", unit_id, body_path, self.backend_id, reason="no-provider")
        return StoreResult("ok" if present else "missing", unit_id, body_path, self.backend_id, reason=None if present else "not-found")

    def materialize(self, unit_id: str, body_path: str, dest_path: Path) -> StoreResult:
        got = self.get(unit_id, body_path)
        if got.verdict != "ok" or got.content is None:
            return StoreResult(got.verdict, unit_id, body_path, self.backend_id, reason=got.reason)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text(got.content, encoding="utf-8")
        log_operation("materialize", unit_id, body_path, got.content, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=got.content, hash=got.hash)


class DeferredBackend(PlanningStoreBackend):
    def __init__(self, root: Path, cfg: dict[str, Any], backend_id: str) -> None:
        super().__init__(root, cfg)
        self.backend_id = backend_id

    def _inert(self, unit_id: str, body_path: str) -> StoreResult:
        log_operation("inert", unit_id, body_path, None, self.backend_id)
        return StoreResult("deferred", unit_id, body_path, self.backend_id, reason="backend-deferred", inert=True)

    def put(self, unit_id: str, body_path: str, content: str, *, content_class: str | None = None) -> StoreResult:
        return self._inert(unit_id, body_path)

    def get(self, unit_id: str, body_path: str) -> StoreResult:
        return self._inert(unit_id, body_path)

    def exists(self, unit_id: str, body_path: str) -> StoreResult:
        return self._inert(unit_id, body_path)

    def materialize(self, unit_id: str, body_path: str, dest_path: Path) -> StoreResult:
        return self._inert(unit_id, body_path)


BACKEND_CLASSES: dict[str, type[PlanningStoreBackend]] = {
    "in-repo-public": InRepoPublicBackend,
    "local-synced": LocalSyncedBackend,
    "memory": MemoryBackend,
    "private-repo": DeferredBackend,
    "encryption-at-rest": DeferredBackend,
}


def resolve_backend_id(cfg: dict[str, Any], *, override: str | None = None) -> str:
    if override and override in ALL_BACKENDS:
        return override
    store = store_section(cfg)
    pinned = store.get("pinnedBackend")
    if isinstance(pinned, str) and pinned in ALL_BACKENDS:
        return pinned
    backend = store.get("backend", DEFAULT_BACKEND)
    if isinstance(backend, str) and backend in ALL_BACKENDS:
        return backend
    return DEFAULT_BACKEND


def get_backend(root: Path, cfg: dict[str, Any] | None = None, *, override: str | None = None) -> PlanningStoreBackend:
    cfg = cfg if cfg is not None else load_workflow_config(root)
    backend_id = resolve_backend_id(cfg, override=override)
    cls = BACKEND_CLASSES[backend_id]
    if backend_id in DEFERRED_BACKENDS:
        return cls(root, cfg, backend_id)
    return cls(root, cfg)


def validate_local_synced_path(path: Path, *, allowlist: list[str] | None = None) -> dict[str, Any]:
    warnings: list[str] = []
    checks: list[dict[str, Any]] = []
    home = Path.home().resolve()
    try:
        resolved = path.resolve()
    except OSError as exc:
        return {"verdict": "fail", "path": str(path), "error": str(exc), "checks": [], "warnings": []}
    allow_roots = [home] + [Path(os.path.expanduser(e)).resolve() for e in (allowlist or [])]
    contained = any(resolved == root or root in resolved.parents for root in allow_roots)
    checks.append({"check": "allowlist", "status": "ok" if contained else "fail", "resolved": str(resolved)})
    if not contained:
        return {"verdict": "fail", "path": str(resolved), "checks": checks, "warnings": ["path-outside-allowlist"]}
    if path.is_symlink():
        checks.append({"check": "symlink", "status": "fail"})
        return {"verdict": "fail", "path": str(resolved), "checks": checks, "warnings": ["symlink-rejected"]}
    checks.append({"check": "symlink", "status": "ok"})
    if ".." in path.parts:
        checks.append({"check": "dotdot", "status": "fail"})
        return {"verdict": "fail", "path": str(resolved), "checks": checks, "warnings": ["dotdot-rejected"]}
    checks.append({"check": "dotdot", "status": "ok"})
    if resolved.is_dir():
        mode = resolved.stat().st_mode & 0o777
        loose = mode > 0o700
        checks.append({"check": "mode", "status": "fail" if loose else "ok", "mode": oct(mode)})
        if loose:
            return {"verdict": "fail", "path": str(resolved), "checks": checks, "warnings": ["loose-directory-mode"]}
    else:
        checks.append({"check": "mode", "status": "skipped", "reason": "not-a-directory"})
    for cloud in CLOUD_SYNC_ROOTS:
        cloud_path = home / cloud
        try:
            if cloud_path.exists() and cloud_path.resolve() in resolved.parents:
                warnings.append(f"cloud-sync-root:{cloud}")
                checks.append({"check": "cloud-sync", "status": "warn", "root": cloud})
                break
        except OSError:
            continue
    return {"verdict": "ok", "path": str(resolved), "checks": checks, "warnings": warnings}


def _require(args: list[str], flag: str) -> str:
    if flag not in args:
        fail(f"missing required flag: {flag}")
    idx = args.index(flag)
    if idx + 1 >= len(args):
        fail(f"missing value for {flag}")
    return args[idx + 1]


def _optional(args: list[str], flag: str) -> str | None:
    if flag not in args:
        return None
    idx = args.index(flag)
    return args[idx + 1] if idx + 1 < len(args) else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Planning store interface (PRD 034)")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("resolve-backend", "list-backends", "put", "get", "exists", "materialize", "validate-local-synced"):
        sub.add_parser(name)
    args, rest = parser.parse_known_args()
    root = git_root(Path(args.root).resolve())
    if args.command == "resolve-backend":
        cfg = load_workflow_config(root)
        override = _optional(rest, "--backend")
        backend_id = resolve_backend_id(cfg, override=override)
        emit({"verdict": "ok", "backend": backend_id, "shipped": backend_id in SHIPPED_BACKENDS, "deferred": backend_id in DEFERRED_BACKENDS})
    elif args.command == "list-backends":
        emit({"verdict": "ok", "default": DEFAULT_BACKEND, "shipped": sorted(SHIPPED_BACKENDS), "deferred": sorted(DEFERRED_BACKENDS), "interface": ["put", "get", "exists", "materialize"]})
    elif args.command == "put":
        backend = get_backend(root, override=_optional(rest, "--backend"))
        result = backend.put(_require(rest, "--unit-id"), _require(rest, "--body-path"), _require(rest, "--content"), content_class=_optional(rest, "--content-class"))
        emit(result.as_dict())
    elif args.command == "get":
        backend = get_backend(root, override=_optional(rest, "--backend"))
        result = backend.get(_require(rest, "--unit-id"), _require(rest, "--body-path"))
        emit(result.as_dict(), 0 if result.verdict in {"ok", "degraded"} else 2)
    elif args.command == "exists":
        backend = get_backend(root, override=_optional(rest, "--backend"))
        emit(backend.exists(_require(rest, "--unit-id"), _require(rest, "--body-path")).as_dict())
    elif args.command == "materialize":
        backend = get_backend(root, override=_optional(rest, "--backend"))
        result = backend.materialize(_require(rest, "--unit-id"), _require(rest, "--body-path"), Path(_require(rest, "--dest")))
        emit(result.as_dict(), 0 if result.verdict == "ok" else 2)
    elif args.command == "validate-local-synced":
        raw = _require(rest, "--path")
        allowlist_raw = _optional(rest, "--allowlist")
        allowlist = [p.strip() for p in allowlist_raw.split(",") if p.strip()] if allowlist_raw else None
        store = store_section(load_workflow_config(root))
        local = store.get("localSynced")
        if isinstance(local, dict) and not allowlist:
            cfg_allow = local.get("allowlist")
            if isinstance(cfg_allow, list):
                allowlist = [str(x) for x in cfg_allow]
        result = validate_local_synced_path(Path(os.path.expanduser(raw)), allowlist=allowlist)
        emit(result, 0 if result["verdict"] == "ok" else 2)


if __name__ == "__main__":
    main()
