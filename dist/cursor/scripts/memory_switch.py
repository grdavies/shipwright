#!/usr/bin/env python3
"""Provider-switch operator flow orchestration (PRD 071 R6)."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_provider_catalog import (
    INTERCHANGE_FORMATS,
    CatalogError,
    get_provider,
    load_catalog,
)

STATE_REL = Path(".cursor/shipwright/provider-switch-state.json")
CONFIG_PATHS = (Path(".cursor/workflow.config.json"), Path("workflow.config.json"))


class SwitchError(Exception):
    def __init__(self, message: str, *, cause: str) -> None:
        super().__init__(message)
        self.cause = cause


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, *, cause: str = "error", exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, "cause": cause, **extra}, exit_code)


def _load_in_repo_search():
    path = Path(__file__).resolve().parent / "in-repo-memory-search.py"
    spec = importlib.util.spec_from_file_location("in_repo_memory_search", path)
    if spec is None or spec.loader is None:
        raise SwitchError("in-repo-memory-search.py not found", cause="missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def interchange_mode(entry: dict[str, Any], fmt: str) -> str:
    interchange = entry.get("interchange")
    if not isinstance(interchange, dict):
        return "unsupported"
    mode = interchange.get(fmt)
    return str(mode).strip() if isinstance(mode, str) and mode.strip() else "unsupported"


def assess_format_migration(source_entry: dict[str, Any], target_entry: dict[str, Any], fmt: str) -> str:
    if fmt not in INTERCHANGE_FORMATS:
        return "blocked"
    source_mode = interchange_mode(source_entry, fmt)
    target_mode = interchange_mode(target_entry, fmt)
    if source_mode == "unsupported" or target_mode == "unsupported":
        return "blocked"
    if source_mode == "synthesized" or target_mode == "synthesized":
        return "lossy"
    return "supported"


def display_capabilities(catalog: dict[str, Any], source_id: str, target_id: str) -> dict[str, Any]:
    source = get_provider(catalog, source_id)
    target = get_provider(catalog, target_id)
    formats: dict[str, Any] = {}
    for fmt in sorted(INTERCHANGE_FORMATS):
        formats[fmt] = {
            "source": interchange_mode(source, fmt),
            "target": interchange_mode(target, fmt),
            "migration": assess_format_migration(source, target, fmt),
        }
    return {
        "verdict": "pass",
        "source": {"id": source_id, "interchange": {f: interchange_mode(source, f) for f in INTERCHANGE_FORMATS}},
        "target": {"id": target_id, "interchange": {f: interchange_mode(target, f) for f in INTERCHANGE_FORMATS}},
        "formats": formats,
    }


def plan_switch(catalog: dict[str, Any], source_id: str, target_id: str, *, fmt: str | None = None) -> dict[str, Any]:
    caps = display_capabilities(catalog, source_id, target_id)
    chosen_fmt = fmt
    migration = "blocked"
    if chosen_fmt:
        migration = str(caps["formats"][chosen_fmt]["migration"])
    else:
        for candidate in ("jsonl", "okf"):
            mode = caps["formats"][candidate]["migration"]
            if mode in {"supported", "lossy"}:
                chosen_fmt = candidate
                migration = mode
                break
        if chosen_fmt is None:
            chosen_fmt = "jsonl"
    path = "migrate" if migration in {"supported", "lossy"} else "skip"
    return {
        "verdict": "pass",
        "source": source_id,
        "target": target_id,
        "format": chosen_fmt,
        "migration": migration,
        "path": path,
        "capabilities": caps,
        "steps": (
            ["export+hash", "switch", "import-dry-run", "confirm", "fidelity"]
            if path == "migrate"
            else ["display-capabilities", "acknowledge-skip"]
        ),
    }


def state_path(root: Path) -> Path:
    return root / STATE_REL


def read_switch_state(root: Path) -> dict[str, Any] | None:
    path = state_path(root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def write_switch_state(root: Path, state: dict[str, Any]) -> Path:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    state = dict(state)
    state["updatedAt"] = _utc_now()
    if "createdAt" not in state:
        state["createdAt"] = state["updatedAt"]
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def clear_switch_state(root: Path, *, force: bool = False) -> bool:
    state = read_switch_state(root)
    path = state_path(root)
    if state is None:
        return False
    if not force and state.get("snapshotPreserved") and state.get("phase") not in {"complete", "partial-fail"}:
        return False
    if path.is_file():
        path.unlink()
    return True


def hash_interchange(path: Path, fmt: str) -> dict[str, Any]:
    if fmt == "jsonl":
        if not path.is_file():
            raise SwitchError(f"export file missing: {path}", cause="missing")
        text = path.read_text(encoding="utf-8")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "count": len(lines), "bytes": len(text.encode("utf-8"))}
    if fmt == "okf":
        if not path.is_dir():
            raise SwitchError(f"export bundle missing: {path}", cause="missing")
        files = sorted(p for p in path.rglob("*.md") if p.is_file())
        hasher = hashlib.sha256()
        count = 0
        for file_path in files:
            hasher.update(file_path.relative_to(path).as_posix().encode("utf-8"))
            hasher.update(b"\0")
            hasher.update(file_path.read_bytes())
            if file_path.name not in {"index.md", "log.md"}:
                count += 1
        return {"sha256": hasher.hexdigest(), "count": count, "bytes": sum(f.stat().st_size for f in files)}
    raise SwitchError(f"unsupported format for hash: {fmt}", cause="unsupported")


def load_config(root: Path) -> dict[str, Any]:
    for rel in CONFIG_PATHS:
        path = root / rel
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except (OSError, json.JSONDecodeError):
                return {}
    return {}


def _in_repo_store_dir(root: Path, config: dict[str, Any]) -> Path:
    memory = config.get("memory", {}) if isinstance(config, dict) else {}
    in_repo = memory.get("inRepo", {}) if isinstance(memory, dict) else {}
    return (root / str(in_repo.get("storeDir") or ".cursor/sw-memory")).resolve()


def _memory_project(config: dict[str, Any]) -> str:
    memory = config.get("memory", {}) if isinstance(config, dict) else {}
    project = memory.get("project") if isinstance(memory, dict) else None
    return str(project).strip() if isinstance(project, str) and project.strip() else "default"


def _mempalace_palace_path(root: Path, config: dict[str, Any], override: Path | None = None) -> Path:
    if override is not None:
        return override.expanduser().resolve()
    memory = config.get("memory", {}) if isinstance(config, dict) else {}
    mempalace = memory.get("mempalace", {}) if isinstance(memory, dict) else {}
    raw = mempalace.get("palacePath") if isinstance(mempalace, dict) else None
    if not isinstance(raw, str) or not raw.strip():
        raise SwitchError("memory.mempalace.palacePath required for mempalace interchange", cause="missing")
    path = Path(raw.strip())
    if not path.is_absolute():
        path = (root / path).resolve()
    return path.expanduser().resolve()


def _basic_memory_project_path(root: Path, config: dict[str, Any], override: Path | None = None) -> Path:
    if override is not None:
        return override.expanduser().resolve()
    memory = config.get("memory", {}) if isinstance(config, dict) else {}
    basic = memory.get("basicMemory", {}) if isinstance(memory, dict) else {}
    raw = basic.get("projectPath") if isinstance(basic, dict) else None
    if not isinstance(raw, str) or not raw.strip():
        raise SwitchError("memory.basicMemory.projectPath required for basic-memory interchange", cause="missing")
    path = Path(raw.strip())
    if not path.is_absolute():
        path = (root / path).resolve()
    return path.expanduser().resolve()


def _basic_memory_dirs(config: dict[str, Any]) -> tuple[str, str]:
    memory = config.get("memory", {}) if isinstance(config, dict) else {}
    basic = memory.get("basicMemory", {}) if isinstance(memory, dict) else {}
    if not isinstance(basic, dict):
        return "memories", "rules"
    memories = str(basic.get("memoriesDirectory") or "memories").strip() or "memories"
    rules = str(basic.get("rulesDirectory") or "rules").strip() or "rules"
    return memories, rules


def _load_mempalace_interchange():
    path = Path(__file__).resolve().parent / "mempalace_interchange.py"
    spec = importlib.util.spec_from_file_location("mempalace_interchange", path)
    if spec is None or spec.loader is None:
        raise SwitchError("mempalace_interchange.py not found", cause="missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_basic_memory_interchange():
    path = Path(__file__).resolve().parent / "basic_memory_interchange.py"
    spec = importlib.util.spec_from_file_location("basic_memory_interchange", path)
    if spec is None or spec.loader is None:
        raise SwitchError("basic_memory_interchange.py not found", cause="missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _obsidian_vault_path(root: Path, config: dict[str, Any], override: Path | None = None) -> Path:
    if override is not None:
        return override.expanduser().resolve()
    memory = config.get("memory", {}) if isinstance(config, dict) else {}
    obsidian = memory.get("obsidian", {}) if isinstance(memory, dict) else {}
    raw = obsidian.get("vaultPath") if isinstance(obsidian, dict) else None
    if not isinstance(raw, str) or not raw.strip():
        raise SwitchError("memory.obsidian.vaultPath required for obsidian interchange", cause="missing")
    path = Path(raw.strip())
    if not path.is_absolute():
        path = (root / path).resolve()
    return path.expanduser().resolve()


def _obsidian_dirs(config: dict[str, Any]) -> tuple[str, str]:
    memory = config.get("memory", {}) if isinstance(config, dict) else {}
    obsidian = memory.get("obsidian", {}) if isinstance(memory, dict) else {}
    if not isinstance(obsidian, dict):
        return "memories", "rules"
    memories = str(obsidian.get("memoriesDirectory") or "memories").strip() or "memories"
    rules = str(obsidian.get("rulesDirectory") or "rules").strip() or "rules"
    return memories, rules


def _load_obsidian_interchange():
    path = Path(__file__).resolve().parent / "obsidian_interchange.py"
    spec = importlib.util.spec_from_file_location("obsidian_interchange", path)
    if spec is None or spec.loader is None:
        raise SwitchError("obsidian_interchange.py not found", cause="missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_config_provider(root: Path, provider_id: str, *, dry_run: bool) -> dict[str, Any]:
    for rel in CONFIG_PATHS:
        path = root / rel
        if not path.is_file():
            continue
        config = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise SwitchError(f"config must be object: {rel}", cause="malformed")
        memory = config.setdefault("memory", {})
        if not isinstance(memory, dict):
            raise SwitchError("memory config must be object", cause="malformed")
        previous = memory.get("provider")
        if not dry_run:
            memory["provider"] = provider_id
            path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        return {"configPath": str(rel), "previous": previous, "next": provider_id, "dryRun": dry_run}
    raise SwitchError("workflow config not found", cause="missing")


def export_in_repo_store(store: Path, fmt: str, out: Path) -> dict[str, Any]:
    search = _load_in_repo_search()
    if search.cmd_export(argparse.Namespace(store=str(store), format=fmt, out=str(out))) != 0:
        raise SwitchError("in-repo export failed", cause="export")
    return {"provider": "in-repo", "format": fmt, "out": str(out), **hash_interchange(out, fmt)}


def import_in_repo_store(store: Path, fmt: str, source: Path, *, dry_run: bool) -> dict[str, Any]:
    meta = hash_interchange(source, fmt)
    if dry_run:
        return {"verdict": "pass", "dryRun": True, "format": fmt, "plannedImport": meta["count"], "source": str(source), "store": str(store)}
    search = _load_in_repo_search()
    store.mkdir(parents=True, exist_ok=True)
    if search.cmd_import(argparse.Namespace(store=str(store), format=fmt, source=str(source))) != 0:
        raise SwitchError("in-repo import failed", cause="import")
    return {"verdict": "pass", "dryRun": False, "format": fmt, "imported": meta["count"], "source": str(source), "store": str(store)}


def export_mempalace_palace(palace_path: Path, fmt: str, out: Path, *, wing: str) -> dict[str, Any]:
    adapter = _load_mempalace_interchange()
    export_meta = adapter.export_palace(palace_path, fmt, out, wing=wing)
    return {**export_meta, **hash_interchange(out, fmt)}


def import_mempalace_palace(palace_path: Path, fmt: str, source: Path, *, dry_run: bool, wing: str) -> dict[str, Any]:
    adapter = _load_mempalace_interchange()
    return adapter.import_palace(palace_path, fmt, source, dry_run=dry_run, wing=wing)


def export_basic_memory_project(
    project_path: Path,
    fmt: str,
    out: Path,
    *,
    memories_directory: str,
    rules_directory: str,
) -> dict[str, Any]:
    adapter = _load_basic_memory_interchange()
    export_meta = adapter.export_project(
        project_path,
        fmt,
        out,
        include_rules=False,
        memories_directory=memories_directory,
        rules_directory=rules_directory,
    )
    return {**export_meta, **hash_interchange(out, fmt)}


def import_basic_memory_project(
    project_path: Path,
    fmt: str,
    source: Path,
    *,
    dry_run: bool,
    memories_directory: str,
    rules_directory: str,
) -> dict[str, Any]:
    adapter = _load_basic_memory_interchange()
    # Import accepts rule-class rows into rules/ so migrate fidelity matches the export
    # snapshot; ordinary export still excludes rules/ unless explicitly requested.
    return adapter.import_project(
        project_path,
        fmt,
        source,
        dry_run=dry_run,
        include_rules=True,
        memories_directory=memories_directory,
        rules_directory=rules_directory,
    )


def export_obsidian_vault(
    vault_path: Path,
    fmt: str,
    out: Path,
    *,
    project: str,
    memories_directory: str,
    rules_directory: str,
) -> dict[str, Any]:
    adapter = _load_obsidian_interchange()
    export_meta = adapter.export_vault(
        vault_path,
        fmt,
        out,
        project=project,
        include_rules=False,
        memories_directory=memories_directory,
        rules_directory=rules_directory,
    )
    return {**export_meta, **hash_interchange(out, fmt)}


def import_obsidian_vault(
    vault_path: Path,
    fmt: str,
    source: Path,
    *,
    project: str,
    dry_run: bool,
    memories_directory: str,
    rules_directory: str,
) -> dict[str, Any]:
    adapter = _load_obsidian_interchange()
    return adapter.import_vault(
        vault_path,
        fmt,
        source,
        project=project,
        dry_run=dry_run,
        include_rules=True,
        memories_directory=memories_directory,
        rules_directory=rules_directory,
    )


def export_by_source(
    root: Path,
    *,
    source_id: str,
    fmt: str,
    export_path: Path,
    store_path: Path | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    if source_id == "in-repo":
        store = store_path or _in_repo_store_dir(root, config)
        if not store.is_dir():
            raise SwitchError(f"in-repo store missing: {store}", cause="missing")
        return export_in_repo_store(store, fmt, export_path)
    if source_id == "mempalace":
        palace = _mempalace_palace_path(root, config, store_path)
        if not palace.is_dir():
            raise SwitchError(f"mempalace palace missing: {palace}", cause="missing")
        return export_mempalace_palace(palace, fmt, export_path, wing=_memory_project(config))
    if source_id == "basic-memory":
        project = _basic_memory_project_path(root, config, store_path)
        if not project.is_dir():
            raise SwitchError(f"basic-memory project missing: {project}", cause="missing")
        memories_dir, rules_dir = _basic_memory_dirs(config)
        return export_basic_memory_project(
            project,
            fmt,
            export_path,
            memories_directory=memories_dir,
            rules_directory=rules_dir,
        )
    if source_id == "obsidian":
        vault = _obsidian_vault_path(root, config, store_path)
        if not vault.is_dir():
            raise SwitchError(f"obsidian vault missing: {vault}", cause="missing")
        memories_dir, rules_dir = _obsidian_dirs(config)
        return export_obsidian_vault(
            vault,
            fmt,
            export_path,
            project=_memory_project(config),
            memories_directory=memories_dir,
            rules_directory=rules_dir,
        )
    if not export_path.exists():
        raise SwitchError(f"export artifact required for synthesized source {source_id}: {export_path}", cause="missing")
    return {"provider": source_id, "format": fmt, "out": str(export_path), **hash_interchange(export_path, fmt)}


def import_by_target(
    root: Path,
    *,
    target_id: str,
    fmt: str,
    source_path: Path,
    store_path: Path,
    dry_run: bool,
    config: dict[str, Any],
) -> dict[str, Any]:
    if target_id == "in-repo":
        return import_in_repo_store(store_path, fmt, source_path, dry_run=dry_run)
    if target_id == "mempalace":
        palace = _mempalace_palace_path(root, config, store_path)
        return import_mempalace_palace(palace, fmt, source_path, dry_run=dry_run, wing=_memory_project(config))
    if target_id == "basic-memory":
        project = _basic_memory_project_path(root, config, store_path)
        memories_dir, rules_dir = _basic_memory_dirs(config)
        return import_basic_memory_project(
            project,
            fmt,
            source_path,
            dry_run=dry_run,
            memories_directory=memories_dir,
            rules_directory=rules_dir,
        )
    if target_id == "obsidian":
        vault = _obsidian_vault_path(root, config, store_path)
        memories_dir, rules_dir = _obsidian_dirs(config)
        return import_obsidian_vault(
            vault,
            fmt,
            source_path,
            project=_memory_project(config),
            dry_run=dry_run,
            memories_directory=memories_dir,
            rules_directory=rules_dir,
        )
    raise SwitchError(f"target provider import unsupported: {target_id}", cause="unsupported")


def resolve_switch_target(state: dict[str, Any]) -> str:
    target = state.get("switchedTo") or state.get("target")
    if not isinstance(target, str) or not target.strip():
        raise SwitchError("switch state missing target provider", cause="missing")
    return target.strip()


def migrate_export_step(root: Path, *, source_id: str, target_id: str, fmt: str, export_path: Path, store_path: Path | None = None) -> dict[str, Any]:
    plan = plan_switch(load_catalog(root), source_id, target_id, fmt=fmt)
    if plan["path"] != "migrate":
        fail(f"migration blocked for format {fmt}", cause="capability-mismatch", plan=plan)
    config = load_config(root)
    export_meta = export_by_source(
        root,
        source_id=source_id,
        fmt=fmt,
        export_path=export_path,
        store_path=store_path,
        config=config,
    )
    write_switch_state(root, {
        "phase": "export", "source": source_id, "target": target_id, "format": fmt,
        "exportPath": str(export_path), "exportHash": export_meta["sha256"], "exportCount": export_meta["count"],
        "snapshotPreserved": True, "migration": plan["migration"],
    })
    return {"verdict": "pass", "step": "export+hash", "export": export_meta, "statePath": str(state_path(root)), "lossy": plan["migration"] == "lossy"}


def migrate_switch_step(root: Path, target_id: str, *, dry_run: bool) -> dict[str, Any]:
    state = read_switch_state(root)
    if state is None or not state.get("snapshotPreserved"):
        fail("no preserved export snapshot — run migrate-export first", cause="missing")
    switch = write_config_provider(root, target_id, dry_run=dry_run)
    if not dry_run:
        state["phase"] = "switch"
        state["switchedTo"] = target_id
        write_switch_state(root, state)
    return {"verdict": "pass", "step": "switch", "switch": switch}


def migrate_import_step(root: Path, *, fmt: str, source_path: Path, store_path: Path, dry_run: bool, confirm: bool) -> dict[str, Any]:
    state = read_switch_state(root)
    if state is None or not state.get("snapshotPreserved"):
        fail("no preserved export snapshot", cause="missing")
    target_id = resolve_switch_target(state)
    config = load_config(root)
    if dry_run:
        preview = import_by_target(
            root,
            target_id=target_id,
            fmt=fmt,
            source_path=source_path,
            store_path=store_path,
            dry_run=True,
            config=config,
        )
        state["phase"] = "import-dry-run"
        write_switch_state(root, state)
        return {"verdict": "pass", "step": "import-dry-run", "preview": preview, "target": target_id}
    if not confirm:
        fail("import requires --confirm after dry-run", cause="confirm-required")
    try:
        result = import_by_target(
            root,
            target_id=target_id,
            fmt=fmt,
            source_path=source_path,
            store_path=store_path,
            dry_run=False,
            config=config,
        )
    except SwitchError:
        state["phase"] = "partial-fail"
        write_switch_state(root, state)
        raise
    fidelity = check_fidelity(state, result)
    state["phase"] = "partial-fail" if fidelity["verdict"] == "fail" else "complete"
    state["importResult"] = result
    state["fidelity"] = fidelity
    if state["phase"] == "complete":
        state["snapshotPreserved"] = False
    write_switch_state(root, state)
    return {"verdict": "pass" if fidelity["verdict"] != "fail" else "fail", "step": "import-confirm", "import": result, "fidelity": fidelity, "snapshotPreserved": state["snapshotPreserved"]}


def skip_ack_step(root: Path, source_id: str, target_id: str, *, acknowledged: bool) -> dict[str, Any]:
    caps = display_capabilities(load_catalog(root), source_id, target_id)
    if not acknowledged:
        return {"verdict": "halt", "path": "skip", "message": "Migration skipped — acknowledge to switch without data migration", "capabilities": caps, "requiresAcknowledgement": True}
    switch = write_config_provider(root, target_id, dry_run=False)
    write_switch_state(root, {"phase": "skip-complete", "source": source_id, "target": target_id, "path": "skip", "acknowledged": True, "snapshotPreserved": False})
    return {"verdict": "pass", "path": "skip", "acknowledged": True, "switch": switch, "capabilities": caps}


def check_fidelity(state: dict[str, Any], import_result: dict[str, Any]) -> dict[str, Any]:
    export_count = int(state.get("exportCount") or 0)
    imported = int(import_result.get("imported") or import_result.get("plannedImport") or 0)
    export_hash = str(state.get("exportHash") or "")
    migration = str(state.get("migration") or "supported")
    if export_count == 0 and imported == 0:
        return {"verdict": "pass", "exportCount": 0, "importCount": 0, "exportHash": export_hash, "message": "empty export/import"}
    if imported == export_count:
        verdict = "lossy_warning" if migration == "lossy" else "pass"
        return {"verdict": verdict, "exportCount": export_count, "importCount": imported, "exportHash": export_hash, "message": "count match" if verdict == "pass" else "count match with synthesized interchange warning"}
    return {"verdict": "fail", "exportCount": export_count, "importCount": imported, "exportHash": export_hash, "message": "import count does not match export snapshot"}


def copy_export_snapshot(src: Path, dest: Path, fmt: str) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "jsonl":
        shutil.copy2(src, dest)
        return dest
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    return dest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Provider-switch operator flow (PRD 071 R6)")
    sub = parser.add_subparsers(dest="command", required=True)

    caps = sub.add_parser("capabilities")
    caps.add_argument("--source", required=True)
    caps.add_argument("--target", required=True)
    caps.add_argument("--root", default=".")

    plan_cmd = sub.add_parser("plan")
    plan_cmd.add_argument("--source", required=True)
    plan_cmd.add_argument("--target", required=True)
    plan_cmd.add_argument("--format", choices=sorted(INTERCHANGE_FORMATS))
    plan_cmd.add_argument("--root", default=".")

    export = sub.add_parser("migrate-export")
    export.add_argument("--source", required=True)
    export.add_argument("--target", required=True)
    export.add_argument("--format", choices=sorted(INTERCHANGE_FORMATS), required=True)
    export.add_argument("--export-path", required=True)
    export.add_argument("--store-path")
    export.add_argument("--root", default=".")

    switch = sub.add_parser("migrate-switch")
    switch.add_argument("--target", required=True)
    switch.add_argument("--dry-run", action="store_true")
    switch.add_argument("--root", default=".")

    imp = sub.add_parser("migrate-import")
    imp.add_argument("--format", choices=sorted(INTERCHANGE_FORMATS), required=True)
    imp.add_argument("--source-path", required=True)
    imp.add_argument("--store-path", required=True)
    imp.add_argument("--dry-run", action="store_true")
    imp.add_argument("--confirm", action="store_true")
    imp.add_argument("--root", default=".")

    skip = sub.add_parser("skip-ack")
    skip.add_argument("--source", required=True)
    skip.add_argument("--target", required=True)
    skip.add_argument("--acknowledged", action="store_true")
    skip.add_argument("--root", default=".")

    fidelity_cmd = sub.add_parser("fidelity")
    fidelity_cmd.add_argument("--import-count", type=int, required=True)
    fidelity_cmd.add_argument("--root", default=".")

    state_cmd = sub.add_parser("state")
    state_cmd.add_argument("--clear", action="store_true")
    state_cmd.add_argument("--force", action="store_true")
    state_cmd.add_argument("--root", default=".")
    return parser


def main(argv: list[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    root = Path(ns.root).resolve()
    try:
        if ns.command == "capabilities":
            emit(display_capabilities(load_catalog(root), ns.source, ns.target))
        if ns.command == "plan":
            emit(plan_switch(load_catalog(root), ns.source, ns.target, fmt=ns.format))
        if ns.command == "migrate-export":
            emit(migrate_export_step(root, source_id=ns.source, target_id=ns.target, fmt=ns.format, export_path=Path(ns.export_path), store_path=Path(ns.store_path) if ns.store_path else None))
        if ns.command == "migrate-switch":
            emit(migrate_switch_step(root, ns.target, dry_run=ns.dry_run))
        if ns.command == "migrate-import":
            emit(migrate_import_step(root, fmt=ns.format, source_path=Path(ns.source_path), store_path=Path(ns.store_path), dry_run=ns.dry_run, confirm=ns.confirm))
        if ns.command == "skip-ack":
            emit(skip_ack_step(root, ns.source, ns.target, acknowledged=ns.acknowledged))
        if ns.command == "fidelity":
            state = read_switch_state(root)
            if state is None:
                fail("no switch state", cause="missing")
            emit(check_fidelity(state, {"imported": ns.import_count}))
        if ns.command == "state":
            if ns.clear:
                emit({"verdict": "pass", "cleared": clear_switch_state(root, force=ns.force)})
            emit({"verdict": "pass", "state": read_switch_state(root)})
    except CatalogError as exc:
        fail(str(exc), cause=exc.cause)
    except SwitchError as exc:
        fail(str(exc), cause=exc.cause)
    return 2


if __name__ == "__main__":
    from _sw.cli import run_module_main
    run_module_main(main)
