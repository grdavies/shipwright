#!/usr/bin/env python3
"""Compile agent, skill, and command instruction sources into a normalized artifact (PRD 326 R9/R10)."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from yaml_structured import safe_load

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
SKILL_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
MAX_SKILL_NAME_LEN = 64
MAX_SKILL_DESCRIPTION_LEN = 1024

COMPILED_ARTIFACT_REL = "core/sw-reference/instruction-artifacts.json"
INHERIT_MODEL = "inherit"
AGENT_GLOB = "core/agents/sw-*.md"
SKILL_GLOB = "core/skills/*/SKILL.md"
COMMAND_GLOB = "core/commands/sw-*.md"


class InstructionCompileError(Exception):
    def __init__(self, source_path: str, message: str) -> None:
        super().__init__(message)
        self.source_path = source_path
        self.message = message


@dataclass(frozen=True)
class CompilerFinding:
    code: str
    message: str
    severity: str = "fail"


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parent.parent


def normalize_body(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines) + ("\n" if lines else "")


def body_digest(body: str) -> str:
    normalized = normalize_body(body)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def parse_frontmatter(text: str, *, source_path: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise InstructionCompileError(source_path, "missing or malformed frontmatter")
    parsed = safe_load(match.group(1))
    if not isinstance(parsed, dict):
        raise InstructionCompileError(source_path, "invalid frontmatter")
    body = text[match.end() :]
    return parsed, body


def load_model_policy(repo_root: Path):
    from host_lib import load_workflow_config
    from model_policy_lib import ModelPolicy

    config = load_workflow_config(repo_root)
    models = config.get("models") if isinstance(config, dict) else {}
    tiers = models.get("tiers") if isinstance(models, dict) and isinstance(models.get("tiers"), dict) else {}
    return ModelPolicy.from_tiers({str(key): str(value) for key, value in tiers.items()})


def validate_agent_model(
    model: str,
    *,
    source_path: str,
    policy,
) -> None:
    if model == INHERIT_MODEL:
        return
    if model in policy.tier_order:
        raise InstructionCompileError(
            source_path,
            f"semantic tier name {model!r} in model frontmatter — use inherit or a concrete platform model ID",
        )


def capability_ids(*, kind: str, record_id: str, frontmatter: Mapping[str, Any]) -> list[str]:
    metadata = frontmatter.get("metadata")
    if not isinstance(metadata, dict):
        return []
    capability = metadata.get("shipwright-capability")
    if not isinstance(capability, dict):
        return []
    if kind == "agent":
        return [f"persona.{record_id}"]
    if kind == "skill":
        return [f"skill.{record_id}"]
    return []


def compile_source(
    path: Path,
    *,
    kind: str,
    repo_root: Path,
    policy=None,
    skip_model_policy: bool = False,
) -> dict[str, Any]:
    rel = path.relative_to(repo_root).as_posix()
    text = path.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter(text, source_path=rel)

    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.strip():
        raise InstructionCompileError(rel, "missing description frontmatter")

    if kind == "agent":
        record_id = frontmatter.get("name")
        if not isinstance(record_id, str) or not record_id.strip():
            raise InstructionCompileError(rel, "missing name frontmatter")
        model_value = frontmatter.get("model")
        if not isinstance(model_value, str) or not model_value.strip():
            raise InstructionCompileError(rel, "missing model frontmatter")
        if not skip_model_policy:
            if policy is None:
                policy = load_model_policy(repo_root)
            validate_agent_model(model_value.strip(), source_path=rel, policy=policy)
        model: str | None = model_value.strip()
    elif kind == "skill":
        record_id = frontmatter.get("name")
        if not isinstance(record_id, str) or not record_id.strip():
            raise InstructionCompileError(rel, "missing name frontmatter")
        model = None
    else:
        record_id = path.stem
        model = None

    caps = capability_ids(kind=kind, record_id=str(record_id), frontmatter=frontmatter)
    return {
        "id": str(record_id),
        "kind": kind,
        "description": description.strip(),
        "model": model,
        "bodyDigest": body_digest(body),
        "capabilities": caps,
        "sourcePath": rel,
    }


def discover_sources(repo_root: Path) -> list[tuple[str, Path]]:
    discovered: list[tuple[str, Path]] = []
    for path in sorted(repo_root.glob(AGENT_GLOB)):
        discovered.append(("agent", path))
    for path in sorted(repo_root.glob(SKILL_GLOB)):
        discovered.append(("skill", path))
    for path in sorted(repo_root.glob(COMMAND_GLOB)):
        discovered.append(("command", path))
    return discovered


def compile_repository(repo_root: Path) -> dict[str, Any]:
    policy = load_model_policy(repo_root)
    artifacts: list[dict[str, Any]] = []
    for kind, path in discover_sources(repo_root):
        artifacts.append(compile_source(path, kind=kind, repo_root=repo_root, policy=policy))
    artifacts.sort(key=lambda item: (item["kind"], item["id"]))
    return {"version": 1, "artifacts": artifacts}


def compile_repository_for_drift(repo_root: Path) -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    for kind, path in discover_sources(repo_root):
        artifacts.append(
            compile_source(
                path,
                kind=kind,
                repo_root=repo_root,
                skip_model_policy=True,
            )
        )
    artifacts.sort(key=lambda item: (item["kind"], item["id"]))
    return {"version": 1, "artifacts": artifacts}


def serialize_document(document: Mapping[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def write_compiled_artifact(repo_root: Path, *, output_path: Path | None = None) -> dict[str, Any]:
    document = compile_repository(repo_root)
    target = output_path or (repo_root / COMPILED_ARTIFACT_REL)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(serialize_document(document), encoding="utf-8")
    return document


def load_compiled_artifacts(repo_root: Path) -> dict[str, Any]:
    path = repo_root / COMPILED_ARTIFACT_REL
    if not path.is_file():
        raise FileNotFoundError(f"missing compiled artifact: {path}")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("compiled artifact must be an object")
    return document


def _description_shape_ok(description: str) -> bool:
    if not description or not description.strip():
        return False
    if len(description) > MAX_SKILL_DESCRIPTION_LEN:
        return False
    return "use when" in description.lower()


def artifact_index(document: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for item in document.get("artifacts") or []:
        if isinstance(item, dict) and item.get("sourcePath"):
            indexed[str(item["sourcePath"])] = item
    return indexed


def instruction_drift_check(repo_root: Path) -> tuple[int, dict[str, Any] | None]:
    artifact_path = repo_root / COMPILED_ARTIFACT_REL
    if not artifact_path.is_file():
        return 0, None
    exit_code, payload = check_compiled_artifact(repo_root)
    if exit_code == 0:
        return 0, None
    if payload.get("reason") == "instruction-artifact-drift":
        return 20, {"verdict": "fail", "reason": "instruction-drift"}
    return exit_code, payload


def lint_skill_spec(
    *,
    source_path: str,
    record_id: str,
    description: str,
    skill_dir: str,
) -> list[CompilerFinding]:
    findings: list[CompilerFinding] = []
    if not record_id:
        findings.append(CompilerFinding("name-missing", "missing or empty name"))
    else:
        if len(record_id) > MAX_SKILL_NAME_LEN:
            findings.append(
                CompilerFinding("name-length", f"name exceeds {MAX_SKILL_NAME_LEN} characters")
            )
        if not SKILL_NAME_RE.fullmatch(record_id) or "--" in record_id:
            findings.append(
                CompilerFinding("name-regex", f"name {record_id!r} fails Agent Skills name regex")
            )
        if record_id != skill_dir:
            findings.append(
                CompilerFinding(
                    "name-dir-mismatch",
                    f"name {record_id!r} does not match directory {skill_dir!r}",
                )
            )
    if not description:
        findings.append(CompilerFinding("description-missing", "missing description"))
    else:
        if len(description) > MAX_SKILL_DESCRIPTION_LEN:
            findings.append(
                CompilerFinding(
                    "description-length",
                    f"description length {len(description)} exceeds {MAX_SKILL_DESCRIPTION_LEN}",
                )
            )
        if not _description_shape_ok(description):
            findings.append(
                CompilerFinding(
                    "description-shape",
                    'description must include what+when shape with explicit "Use when" trigger',
                )
            )
    return findings


def lint_skill_file(
    path: Path,
    *,
    repo_root: Path | None = None,
    source_path: str | None = None,
) -> list[CompilerFinding]:
    resolved = path.resolve()
    skill_dir = resolved.parent.name
    rel = source_path
    if rel is None and repo_root is not None:
        try:
            rel = resolved.relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            rel = resolved.as_posix()
    if rel is None:
        rel = resolved.as_posix()
    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        return [CompilerFinding("read-error", str(exc))]
    try:
        frontmatter, _body = parse_frontmatter(text, source_path=rel)
    except InstructionCompileError as exc:
        return [CompilerFinding("malformed-frontmatter", exc.message)]
    record_id = frontmatter.get("name")
    description = frontmatter.get("description")
    return lint_skill_spec(
        source_path=rel,
        record_id=str(record_id).strip() if isinstance(record_id, str) else "",
        description=description.strip() if isinstance(description, str) else "",
        skill_dir=skill_dir,
    )


def check_compiled_artifact(repo_root: Path) -> tuple[int, dict[str, Any]]:
    expected_path = repo_root / COMPILED_ARTIFACT_REL
    if not expected_path.is_file():
        return 20, {
            "verdict": "fail",
            "reason": "instruction-artifact-missing",
            "path": COMPILED_ARTIFACT_REL,
        }
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    actual = compile_repository_for_drift(repo_root)
    if serialize_document(expected) == serialize_document(actual):
        return 0, {"verdict": "pass", "artifact": COMPILED_ARTIFACT_REL}

    expected_by_source = {
        str(item.get("sourcePath")): item
        for item in (expected.get("artifacts") or [])
        if isinstance(item, dict) and item.get("sourcePath")
    }
    actual_by_source = {
        str(item.get("sourcePath")): item
        for item in (actual.get("artifacts") or [])
        if isinstance(item, dict) and item.get("sourcePath")
    }
    mismatches: list[dict[str, str]] = []
    for source_path in sorted(set(expected_by_source) | set(actual_by_source)):
        expected_item = expected_by_source.get(source_path)
        actual_item = actual_by_source.get(source_path)
        if expected_item is None or actual_item is None:
            mismatches.append(
                {
                    "sourcePath": source_path,
                    "reason": "missing-entry",
                }
            )
            continue
        if expected_item.get("bodyDigest") != actual_item.get("bodyDigest"):
            mismatches.append(
                {
                    "id": str(actual_item.get("id") or expected_item.get("id") or ""),
                    "sourcePath": source_path,
                    "expectedDigest": str(expected_item.get("bodyDigest") or ""),
                    "actualDigest": str(actual_item.get("bodyDigest") or ""),
                }
            )
    return 20, {
        "verdict": "fail",
        "reason": "instruction-artifact-drift",
        "mismatches": mismatches,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile Shipwright instruction artifacts (PRD 326 R9/R10)")
    parser.add_argument("--root", type=Path, default=None, help="Repository root")
    parser.add_argument("--check", action="store_true", help="Recompile and diff against committed artifact")
    parser.add_argument("--output", type=Path, default=None, help="Optional output path (write mode only)")
    args = parser.parse_args(argv)

    repo_root = (args.root or repo_root_from_script()).resolve()
    try:
        if args.check:
            exit_code, payload = check_compiled_artifact(repo_root)
            json.dump(payload, sys.stdout, indent=2, sort_keys=True)
            sys.stdout.write("\n")
            return exit_code
        document = write_compiled_artifact(repo_root, output_path=args.output)
        json.dump({"verdict": "pass", "artifact": COMPILED_ARTIFACT_REL, "count": len(document["artifacts"])}, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    except InstructionCompileError as exc:
        payload = {
            "verdict": "fail",
            "reason": "malformed-frontmatter",
            "sourcePath": exc.source_path,
            "message": exc.message,
        }
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 20


if __name__ == "__main__":
    sys.exit(main())
