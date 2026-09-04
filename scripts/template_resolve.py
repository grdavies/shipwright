#!/usr/bin/env python3
"""Three-layer template resolution stack (PRD 342 R37–R39).

Resolution order (first match wins per template path):
  1. repository overrides under ``.shipwright/templates``
  2. installed template packs under ``.shipwright/template-packs``
  3. core defaults under ``core/sw-reference/templates``

Legacy SW templates under the retired state-root templates family are not
consulted — unit 5 retires that unread orphan (see
``.shipwright/template-stack-disposition.json``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Literal

from shipwright_paths import STATE_ROOT_LEGACY_SW, STATE_ROOT_PRIMARY

LayerName = Literal["override", "pack", "core"]

LAYER_OVERRIDE: LayerName = "override"
LAYER_PACK: LayerName = "pack"
LAYER_CORE: LayerName = "core"

PACKS_DIR_REL = f"{STATE_ROOT_PRIMARY}/template-packs"
CORE_TEMPLATES_REL = "core/sw-reference/templates"
OVERRIDES_DIR_REL = f"{STATE_ROOT_PRIMARY}/templates"
LEGACY_TEMPLATES_REL = f"{STATE_ROOT_LEGACY_SW}/templates"
BASELINES_REL = f"{STATE_ROOT_PRIMARY}/template-core-baselines.json"
DISPOSITION_REL = f"{STATE_ROOT_PRIMARY}/template-stack-disposition.json"
MANIFEST_NAME = "manifest.json"


@dataclass(frozen=True)
class ResolvedTemplate:
    """One resolved template with provenance (R39)."""

    path: str
    layer: LayerName
    source: str
    bytes: bytes

    @property
    def text(self) -> str:
        return self.bytes.decode("utf-8")

    def as_dict(self, *, include_bytes: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "path": self.path,
            "layer": self.layer,
            "source": self.source,
            "sha256": hashlib.sha256(self.bytes).hexdigest(),
            "size": len(self.bytes),
        }
        if include_bytes:
            payload["bytes"] = self.bytes
        return payload


def preferred_overrides_dir(root: Path) -> Path:
    """Override layer root (``.shipwright/templates`` only — never legacy)."""
    return root / OVERRIDES_DIR_REL


def core_templates_dir(root: Path) -> Path:
    return root / CORE_TEMPLATES_REL


def packs_dir(root: Path) -> Path:
    return root / PACKS_DIR_REL


def legacy_templates_dir(root: Path) -> Path:
    return root / LEGACY_TEMPLATES_REL


def baselines_path(root: Path) -> Path:
    return root / BASELINES_REL


def disposition_path(root: Path) -> Path:
    return root / DISPOSITION_REL


def _iter_files(directory: Path) -> Iterator[Path]:
    if not directory.is_dir():
        return
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith(".") or path.name == MANIFEST_NAME:
            continue
        yield path


def _rel_under(base: Path, path: Path) -> str:
    return path.relative_to(base).as_posix()


def list_core_template_paths(root: Path) -> list[str]:
    base = core_templates_dir(root)
    return [_rel_under(base, p) for p in _iter_files(base)]


def list_installed_packs(root: Path) -> list[dict[str, Any]]:
    """Return installed pack manifests (id, version, paths, installDir)."""
    base = packs_dir(root)
    packs: list[dict[str, Any]] = []
    if not base.is_dir():
        return packs
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        manifest_file = child / MANIFEST_NAME
        if not manifest_file.is_file():
            continue
        try:
            data = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        packs.append(
            {
                "id": str(data.get("id") or child.name),
                "version": str(data.get("version") or ""),
                "paths": list(data.get("paths") or []),
                "installDir": child.as_posix(),
            }
        )
    return packs


def _pack_template_file(pack_dir: Path, rel: str) -> Path | None:
    candidate = pack_dir / rel
    return candidate if candidate.is_file() else None


def resolve_template(root: Path, rel_path: str) -> ResolvedTemplate:
    """Resolve a single template path through the three-layer stack (R37)."""
    rel = rel_path.replace("\\", "/").lstrip("/")

    override = preferred_overrides_dir(root) / rel
    if override.is_file():
        return ResolvedTemplate(
            path=rel,
            layer=LAYER_OVERRIDE,
            source=override.as_posix(),
            bytes=override.read_bytes(),
        )

    for pack in list_installed_packs(root):
        paths = {str(p).replace("\\", "/") for p in pack.get("paths") or []}
        if rel not in paths:
            continue
        pack_dir = Path(str(pack["installDir"]))
        hit = _pack_template_file(pack_dir, rel)
        if hit is None:
            continue
        return ResolvedTemplate(
            path=rel,
            layer=LAYER_PACK,
            source=hit.as_posix(),
            bytes=hit.read_bytes(),
        )

    core = core_templates_dir(root) / rel
    if core.is_file():
        return ResolvedTemplate(
            path=rel,
            layer=LAYER_CORE,
            source=core.as_posix(),
            bytes=core.read_bytes(),
        )

    raise FileNotFoundError(f"template not found in any layer: {rel}")


def resolve_all(root: Path) -> list[ResolvedTemplate]:
    """Resolve every core template name (plus override/pack-only extras)."""
    names: set[str] = set(list_core_template_paths(root))
    overrides = preferred_overrides_dir(root)
    for path in _iter_files(overrides):
        names.add(_rel_under(overrides, path))
    for pack in list_installed_packs(root):
        for rel in pack.get("paths") or []:
            names.add(str(rel).replace("\\", "/"))
    resolved: list[ResolvedTemplate] = []
    for name in sorted(names):
        try:
            resolved.append(resolve_template(root, name))
        except FileNotFoundError:
            continue
    return resolved


def provenance_report(root: Path) -> dict[str, Any]:
    """Operator-facing provenance map: path → supplying layer (R39)."""
    items = [item.as_dict() for item in resolve_all(root)]
    return {
        "verdict": "pass",
        "layers": [LAYER_OVERRIDE, LAYER_PACK, LAYER_CORE],
        "templates": items,
        "counts": {
            LAYER_OVERRIDE: sum(1 for i in items if i["layer"] == LAYER_OVERRIDE),
            LAYER_PACK: sum(1 for i in items if i["layer"] == LAYER_PACK),
            LAYER_CORE: sum(1 for i in items if i["layer"] == LAYER_CORE),
        },
    }


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record_core_baselines(root: Path, *, paths: list[str] | None = None) -> dict[str, str]:
    """Snapshot current core digests for override-drift diagnosis (R41)."""
    core = core_templates_dir(root)
    targets = paths if paths is not None else list_core_template_paths(root)
    baselines: dict[str, str] = {}
    existing_path = baselines_path(root)
    if existing_path.is_file():
        try:
            prior = json.loads(existing_path.read_text(encoding="utf-8"))
            if isinstance(prior, dict):
                baselines.update({str(k): str(v) for k, v in prior.items()})
        except (OSError, json.JSONDecodeError):
            pass
    for rel in targets:
        file_path = core / rel
        if file_path.is_file():
            baselines[rel] = sha256_file(file_path)
    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing_path.write_text(
        json.dumps(baselines, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return baselines


def load_core_baselines(root: Path) -> dict[str, str]:
    path = baselines_path(root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def diagnose_override_drift(root: Path) -> list[dict[str, Any]]:
    """Report overrides that shadow a core template whose default changed (R41)."""
    overrides = preferred_overrides_dir(root)
    core = core_templates_dir(root)
    baselines = load_core_baselines(root)
    findings: list[dict[str, Any]] = []
    for path in _iter_files(overrides):
        rel = _rel_under(overrides, path)
        core_file = core / rel
        if not core_file.is_file():
            continue
        current = sha256_file(core_file)
        recorded = baselines.get(rel)
        if recorded is None:
            continue
        if recorded != current:
            findings.append(
                {
                    "path": rel,
                    "issue": "override-drift",
                    "override": path.as_posix(),
                    "core": core_file.as_posix(),
                    "baselineSha256": recorded,
                    "coreSha256": current,
                }
            )
    return findings


def legacy_templates_present(root: Path) -> bool:
    """True when a leftover legacy SW templates tree still exists on disk."""
    legacy = legacy_templates_dir(root)
    if not legacy.exists():
        return False
    if legacy.is_dir():
        return any(p.is_file() for p in legacy.rglob("*"))
    return True


def load_disposition(root: Path) -> dict[str, Any] | None:
    path = disposition_path(root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None, help="Repository root")
    sub = parser.add_subparsers(dest="command")
    resolve_p = sub.add_parser("resolve", help="Resolve one template path")
    resolve_p.add_argument("path", help="Template relative path (e.g. pr-body.md)")
    sub.add_parser("report", help="Provenance report for all templates")
    sub.add_parser("drift", help="Override-drift findings (R41)")
    args = parser.parse_args(argv)
    root = (args.root or Path.cwd()).resolve()
    command = args.command or "report"

    if command == "resolve":
        try:
            resolved = resolve_template(root, args.path)
        except FileNotFoundError as exc:
            print(json.dumps({"verdict": "fail", "error": str(exc)}))
            return 1
        print(json.dumps({"verdict": "pass", "template": resolved.as_dict()}, indent=2))
        return 0

    if command == "drift":
        findings = diagnose_override_drift(root)
        print(
            json.dumps(
                {
                    "verdict": "pass" if not findings else "warn",
                    "findings": findings,
                },
                indent=2,
            )
        )
        return 0 if not findings else 1

    print(json.dumps(provenance_report(root), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
