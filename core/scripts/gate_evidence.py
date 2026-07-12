#!/usr/bin/env python3
"""Gate evidence resolver, binding modes, and sole-writer validation (PRD 065 R7, R21, R22)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

SCHEMA_REL = Path("core/sw-reference/gate-evidence.schema.json")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA64 = re.compile(r"^[0-9a-f]{64}$")
VALID_BINDING = frozenset({"tree-stable", "head-exact"})
EVIDENCE_SCHEMA_VERSION = 1

# Tracked-path exclusions for tree-stable binding (run + evidence dirs).
TREE_EXCLUDE_PREFIXES = (
    ".cursor/sw-deliver-runs/",
    ".cursor/sw-execute-runs/",
    ".cursor/sw-deliver-locks/",
    ".cursor/sw-tmp/",
    ".cursor/sw-debug-runs/",
    ".cursor/sw-feedback-runs/",
    ".cursor/sw-doc-runs/",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def repo_root(start: Path | None = None) -> Path:
    start = (start or Path.cwd()).resolve()
    proc = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return start


def repo_root_for_path(path: Path) -> Path:
    proc = subprocess.run(
        ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return repo_root(path)


def schema_path(root: Path | None = None) -> Path:
    return repo_root(root) / SCHEMA_REL


def evidence_dir(root: Path, phase_slug: str) -> Path:
    return repo_root(root) / ".cursor" / "sw-deliver-runs" / phase_slug / "gate-evidence"


def evidence_record_path(root: Path, phase_slug: str, gate_id: str) -> Path:
    return evidence_dir(root, phase_slug) / f"{gate_id}.status.json"


def resolve_head_sha(root: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo_root(root)), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _git_index_entries(root: Path) -> list[tuple[str, str, str]]:
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "-z"],
        capture_output=True,
    )
    entries: list[tuple[str, str, str]] = []
    for chunk in proc.stdout.split(b"\0"):
        if not chunk:
            continue
        decoded = chunk.decode("utf-8", errors="replace")
        if "\t" not in decoded:
            continue
        meta, path = decoded.split("\t", 1)
        meta_parts = meta.split()
        if len(meta_parts) < 2:
            continue
        entries.append((meta_parts[0], meta_parts[1], path))
    return entries


def _paths_to_tree_map(entries: list[tuple[str, str, str]]) -> dict:
    root_map: dict = {}
    for mode, sha, path in entries:
        parts = path.split("/")
        cur = root_map
        for index, part in enumerate(parts):
            if index == len(parts) - 1:
                cur[part] = (mode, sha)
            else:
                cur = cur.setdefault(part, {})
    return root_map


def _mktree_from_map(node_map: dict, root: Path) -> str:
    lines: list[str] = []
    for name in sorted(node_map.keys()):
        node = node_map[name]
        if isinstance(node, tuple):
            mode, sha = node
            lines.append(f"{mode} blob {sha}\t{name}")
        elif isinstance(node, dict):
            sub = _mktree_from_map(node, root)
            lines.append(f"040000 tree {sub}\t{name}")
        else:
            raise TypeError(f"invalid tree node for {name!r}")
    payload = ("\0".join(lines) + "\0").encode("utf-8") if lines else b""
    proc = subprocess.run(
        ["git", "-C", str(root), "mktree", "-z"],
        input=payload,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or b"").decode("utf-8", errors="replace").strip() or "git mktree failed")
    return proc.stdout.decode("utf-8", errors="replace").strip()


def compute_tree_hash(root: Path | None = None) -> str:
    """tree-stable hash: git write-tree equivalent over tracked paths excluding run/evidence dirs."""
    root = repo_root(root)
    entries: list[tuple[str, str, str]] = []
    for mode, sha, path in _git_index_entries(root):
        if any(path.startswith(prefix) for prefix in TREE_EXCLUDE_PREFIXES):
            continue
        entries.append((mode, sha, path))
    if not entries:
        proc = subprocess.run(
            ["git", "-C", str(root), "hash-object", "-t", "tree", "-w", "--stdin"],
            input=b"",
            capture_output=True,
        )
        if proc.returncode != 0:
            raise RuntimeError("failed to hash empty tree")
        return proc.stdout.decode("utf-8", errors="replace").strip()
    return _mktree_from_map(_paths_to_tree_map(entries), root)


def execution_subset(execution: Any) -> Any:
    if not isinstance(execution, dict):
        return "__invalid__"
    keys = ("argv", "exitCode", "stdoutDigest", "stderrDigest", "duration")
    return {k: execution[k] for k in sorted(keys) if k in execution}


def canonical_provenance_payload(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": record.get("schemaVersion"),
        "gateId": record.get("gateId"),
        "class": record.get("class"),
        "bindingMode": record.get("bindingMode"),
        "evaluationPoint": record.get("evaluationPoint"),
        "headSha": record.get("headSha"),
        "treeHash": record.get("treeHash"),
        "verdict": record.get("verdict"),
        "execution": execution_subset(record.get("execution")),
        "artifactRefs": record.get("artifactRefs"),
    }


def compute_provenance_marker(record: dict[str, Any]) -> str:
    payload = canonical_provenance_payload(record)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def attach_provenance_marker(record: dict[str, Any]) -> dict[str, Any]:
    doc = dict(record)
    doc["provenanceMarker"] = compute_provenance_marker(doc)
    return doc


def validate_provenance_marker(record: dict[str, Any]) -> tuple[bool, str | None]:
    marker = record.get("provenanceMarker")
    if not isinstance(marker, str) or not SHA64.match(marker):
        return False, "gate-evidence:missing-provenance"
    if marker != compute_provenance_marker(record):
        return False, "gate-evidence:forged-provenance"
    return True, None


def _load_schema(root: Path) -> dict[str, Any]:
    return json.loads(schema_path(root).read_text(encoding="utf-8"))


def _basic_validate_record(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = (
        "schemaVersion",
        "gateId",
        "class",
        "bindingMode",
        "evaluationPoint",
        "headSha",
        "treeHash",
        "verdict",
        "execution",
        "timestamp",
        "artifactRefs",
        "provenanceMarker",
    )
    for key in required:
        if key not in record:
            errors.append(f"missing:{key}")
    execution = record.get("execution")
    if not isinstance(execution, dict):
        errors.append("invalid:execution")
    else:
        for key in ("argv", "exitCode", "stdoutDigest", "stderrDigest", "duration"):
            if key not in execution:
                errors.append(f"missing:execution.{key}")
    if record.get("bindingMode") not in VALID_BINDING:
        errors.append("invalid:bindingMode")
    if isinstance(record.get("headSha"), str) and not SHA40.match(record["headSha"]):
        errors.append("invalid:headSha")
    if isinstance(record.get("treeHash"), str) and not SHA40.match(record["treeHash"]):
        errors.append("invalid:treeHash")
    return errors


def validate_record_shape(record: dict[str, Any], root: Path | None = None) -> tuple[bool, str | None]:
    basic_errors = _basic_validate_record(record)
    if basic_errors:
        return False, f"gate-evidence:schema-invalid:{basic_errors[0]}"
    try:
        import jsonschema
    except ModuleNotFoundError:
        try:
            from _sw.vendor_paths import bootstrap_vendor_paths

            bootstrap_vendor_paths()
            import jsonschema
        except Exception:
            jsonschema = None  # type: ignore[assignment]
    if jsonschema is not None:
        try:
            schema = _load_schema(repo_root(root))
            jsonschema.validate(record, schema)
        except Exception as exc:
            return False, f"gate-evidence:schema-invalid:{exc.__class__.__name__}"
    ok, cause = validate_provenance_marker(record)
    if not ok:
        return False, cause
    return True, None


def read_record_file(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Partial/truncated files fail closed."""
    if not path.is_file():
        return None, "gate-evidence:missing"
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return None, "gate-evidence:partial"
    try:
        record = json.loads(raw)
    except json.JSONDecodeError:
        return None, "gate-evidence:partial"
    if not isinstance(record, dict):
        return None, "gate-evidence:partial"
    ok, cause = validate_record_shape(record, repo_root_for_path(path))
    if not ok:
        return None, cause
    return record, None


def binding_matches(
    record: dict[str, Any],
    *,
    head_sha: str,
    tree_hash: str,
) -> tuple[bool, str | None]:
    mode = str(record.get("bindingMode") or "")
    if mode not in VALID_BINDING:
        return False, "gate-evidence:invalid-binding-mode"
    if mode == "head-exact":
        if str(record.get("headSha") or "") != head_sha:
            return False, "gate-evidence:head-mismatch"
        return True, None
    if str(record.get("treeHash") or "") != tree_hash:
        return False, "gate-evidence:tree-mismatch"
    return True, None


def is_binding_valid(
    record: dict[str, Any],
    root: Path,
    *,
    head_sha: str | None = None,
    tree_hash: str | None = None,
) -> tuple[bool, str | None]:
    ok, cause = validate_record_shape(record, root)
    if not ok:
        return False, cause
    head = head_sha or resolve_head_sha(root)
    tree = tree_hash or compute_tree_hash(root)
    return binding_matches(record, head_sha=head, tree_hash=tree)


def validate_outcome_path_non_overlap(outcome_path: Path, evidence_root: Path) -> tuple[bool, str | None]:
    try:
        outcome = outcome_path.resolve()
        evidence = evidence_root.resolve()
    except OSError:
        return False, "gate-evidence:path-resolve-failed"
    if outcome == evidence:
        return False, "gate-evidence:outcome-overlap"
    try:
        outcome.relative_to(evidence)
        return False, "gate-evidence:outcome-overlap"
    except ValueError:
        pass
    try:
        evidence.relative_to(outcome)
        return False, "gate-evidence:outcome-overlap"
    except ValueError:
        pass
    return True, None


def write_evidence_atomic(path: Path, record: dict[str, Any], *, mode: int = 0o600) -> dict[str, Any]:
    stamped = attach_provenance_marker(dict(record))
    if "writtenAt" not in stamped:
        stamped["writtenAt"] = utc_now()
    if "timestamp" not in stamped:
        stamped["timestamp"] = stamped["writtenAt"]
    if stamped.get("schemaVersion") is None:
        stamped["schemaVersion"] = EVIDENCE_SCHEMA_VERSION
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(stamped, ensure_ascii=False, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}-", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return stamped


def build_evidence_record(
    *,
    gate_id: str,
    gate_class: str,
    binding_mode: str,
    evaluation_point: str,
    verdict: str,
    execution: dict[str, Any],
    artifact_refs: list[str] | None = None,
    root: Path | None = None,
    head_sha: str | None = None,
    tree_hash: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    root = repo_root(root)
    return {
        "schemaVersion": EVIDENCE_SCHEMA_VERSION,
        "gateId": gate_id,
        "class": gate_class,
        "bindingMode": binding_mode,
        "evaluationPoint": evaluation_point,
        "headSha": head_sha or resolve_head_sha(root),
        "treeHash": tree_hash or compute_tree_hash(root),
        "verdict": verdict,
        "execution": execution,
        "timestamp": timestamp or utc_now(),
        "artifactRefs": artifact_refs or [],
    }


def resolve_gate_from_manifest(gate_id: str, root: Path) -> dict[str, Any] | None:
    try:
        from gate_manifest import gates_by_id, load_manifest

        manifest = load_manifest(root)
        return gates_by_id(manifest).get(gate_id)
    except Exception:
        return None


def resolve_authoritative_record(
    root: Path,
    phase_slug: str,
    gate_id: str,
    *,
    head_sha: str | None = None,
    tree_hash: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Unknown gate ids are inert; freshest binding-valid record wins."""
    gate = resolve_gate_from_manifest(gate_id, root)
    if gate is None:
        return None, None
    path = evidence_record_path(root, phase_slug, gate_id)
    record, cause = read_record_file(path)
    if record is None:
        return None, cause
    ok, bind_cause = is_binding_valid(record, root, head_sha=head_sha, tree_hash=tree_hash)
    if not ok:
        return None, bind_cause
    return record, None


def list_binding_valid_records(
    root: Path,
    phase_slug: str,
    *,
    head_sha: str | None = None,
    tree_hash: str | None = None,
) -> list[dict[str, Any]]:
    try:
        from gate_manifest import gates_by_id, load_manifest

        manifest = load_manifest(root)
        gate_ids = sorted(gates_by_id(manifest))
    except Exception:
        return []
    head = head_sha or resolve_head_sha(root)
    tree = tree_hash or compute_tree_hash(root)
    out: list[dict[str, Any]] = []
    for gate_id in gate_ids:
        record, _ = resolve_authoritative_record(
            root, phase_slug, gate_id, head_sha=head, tree_hash=tree
        )
        if record is not None:
            out.append(record)
    out.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
    return out


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_text(text: str) -> str:
    return digest_bytes(text.encode("utf-8"))


def cmd_write(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    execution = json.loads(args.execution_json)
    artifact_refs = json.loads(args.artifact_refs_json) if args.artifact_refs_json else []
    record = build_evidence_record(
        gate_id=args.gate_id,
        gate_class=args.gate_class,
        binding_mode=args.binding_mode,
        evaluation_point=args.evaluation_point,
        verdict=args.verdict,
        execution=execution,
        artifact_refs=artifact_refs,
        root=root,
        head_sha=args.head_sha or None,
        tree_hash=args.tree_hash or None,
    )
    out = Path(args.out) if args.out else evidence_record_path(root, args.phase_slug, args.gate_id)
    if args.outcome_path:
        ok, cause = validate_outcome_path_non_overlap(Path(args.outcome_path), out.parent)
        if not ok:
            print(json.dumps({"verdict": "fail", "cause": cause}, indent=2))
            return 2
    stamped = write_evidence_atomic(out, record)
    print(json.dumps({"verdict": "pass", "path": str(out), "record": stamped}, indent=2))
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    record, cause = resolve_authoritative_record(root, args.phase_slug, args.gate_id)
    payload: dict[str, Any] = {"verdict": "pass" if record else "fail", "gateId": args.gate_id}
    if record:
        payload["record"] = record
    else:
        payload["cause"] = cause or "gate-evidence:not-found"
    print(json.dumps(payload, indent=2))
    return 0 if record else 2


def cmd_validate(args: argparse.Namespace) -> int:
    record, cause = read_record_file(Path(args.path))
    if record is None:
        print(json.dumps({"verdict": "fail", "cause": cause}, indent=2))
        return 2
    ok, bind_cause = is_binding_valid(record, repo_root(args.root))
    if not ok:
        print(json.dumps({"verdict": "fail", "cause": bind_cause}, indent=2))
        return 2
    print(json.dumps({"verdict": "pass"}, indent=2))
    return 0


def cmd_tree_hash(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    print(json.dumps({"verdict": "pass", "treeHash": compute_tree_hash(root)}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate evidence resolver and writer")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)

    write_p = sub.add_parser("write", help="Write an evidence record atomically")
    write_p.add_argument("--phase-slug", required=True)
    write_p.add_argument("--gate-id", required=True)
    write_p.add_argument("--gate-class", required=True)
    write_p.add_argument("--binding-mode", required=True, choices=sorted(VALID_BINDING))
    write_p.add_argument("--evaluation-point", required=True)
    write_p.add_argument("--verdict", required=True, choices=["pass", "fail", "skip"])
    write_p.add_argument("--execution-json", required=True)
    write_p.add_argument("--artifact-refs-json", default="")
    write_p.add_argument("--head-sha", default="")
    write_p.add_argument("--tree-hash", default="")
    write_p.add_argument("--out", default="")
    write_p.add_argument("--outcome-path", default="")
    write_p.set_defaults(func=cmd_write)

    resolve_p = sub.add_parser("resolve", help="Resolve authoritative binding-valid record")
    resolve_p.add_argument("--phase-slug", required=True)
    resolve_p.add_argument("--gate-id", required=True)
    resolve_p.set_defaults(func=cmd_resolve)

    validate_p = sub.add_parser("validate", help="Validate record shape + binding")
    validate_p.add_argument("--path", required=True)
    validate_p.set_defaults(func=cmd_validate)

    tree_p = sub.add_parser("tree-hash", help="Compute tree-stable hash")
    tree_p.set_defaults(func=cmd_tree_hash)

    ns = parser.parse_args(argv)
    return int(ns.func(ns))


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)

