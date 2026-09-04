#!/usr/bin/env python3
"""Architecture doctrine assessment evaluator (PRD 326 R13–R15; PRD 330 R4–R5, R10).

Shipwright-self ``AD-<n>`` statements live in ``core/sw-reference/architecture-doctrine.md``.
Consumer architecture vocabulary and assessment data are evaluated from repo-local
``.sw/project-doctrine.json`` (sole ProjectDoctrine SoT). Codebase-design is a read-only
reference/assessment input — never a second SoT and never a ``/sw-codebase-design`` command.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from yaml_structured import safe_load

DOCTRINE_REL = Path("core/sw-reference/architecture-doctrine.md")
SCHEMA_REL = Path("core/sw-reference/architecture-assessment.schema.json")
DEFAULT_ASSESSMENT_REL = Path(".cursor/architecture-assessment.yaml")
CONSUMER_DOCTRINE_REL = Path(".sw/project-doctrine.json")
CONSUMER_VOCABULARY_KEYS = ("modules", "interfaces", "seams", "adapters", "locality")
CONSUMER_FORBIDDEN_ROOT_KEYS = frozenset({"productRoadmap", "orgChart", "runtimeRunbook"})
# Codebase-design is reference/assessment input only (PRD 330 R4 / D3) — not a workflow command.
CODEBASE_DESIGN_IS_COMMAND = False
BUNDLED_AD_ID_RE = re.compile(r"^AD-[0-9]+$")
CONSUMER_ENTRY_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
DOCTRINE_VERSION_RE = re.compile(r"^\*\*Version:\*\*\s*(\d+)\s*$", re.MULTILINE)
DOCTRINE_HEADING_RE = re.compile(r"^##\s+(AD-\d+):\s*(.+)$", re.MULTILINE)
FIELD_RE = re.compile(r"^-\s+\*\*(Rationale|Signal|manual):\*\*\s*(.*)$", re.MULTILINE)
VERDICTS = frozenset({"pass", "fail", "waived", "manual"})


def emit(obj: dict[str, Any], code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(code)


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def parse_iso_date(value: str) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def load_workflow_config(root: Path) -> dict[str, Any]:
    from shipwright_paths import load_workflow_config as _load_workflow_config

    return _load_workflow_config(root)
def cfg_value(cfg: dict[str, Any], *path: str, default: Any = None) -> Any:
    value: Any = cfg
    for part in path:
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def assessment_mode(root: Path) -> str:
    cfg = load_workflow_config(root)
    mode = str(cfg_value(cfg, "architecture", "assessment", "mode", default="off") or "off").strip().lower()
    return mode if mode in {"off", "advisory", "blocking"} else "off"


def assessment_path(root: Path) -> Path:
    cfg = load_workflow_config(root)
    rel = cfg_value(cfg, "architecture", "assessment", "path", default=str(DEFAULT_ASSESSMENT_REL))
    return root / str(rel or DEFAULT_ASSESSMENT_REL)


def doctrine_path(root: Path) -> Path:
    return root / DOCTRINE_REL


def split_doctrine_sections(text: str) -> list[tuple[str, str, str]]:
    matches = list(DOCTRINE_HEADING_RE.finditer(text))
    sections: list[tuple[str, str, str]] = []
    for index, match in enumerate(matches):
        stmt_id = match.group(1)
        title = match.group(2).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append((stmt_id, title, text[start:end]))
    return sections


def parse_doctrine_text(text: str) -> dict[str, Any]:
    if not text.strip():
        return {"verdict": "fail", "error": "empty-doctrine-artifact", "statements": []}

    version_match = DOCTRINE_VERSION_RE.search(text)
    version = int(version_match.group(1)) if version_match else None

    statements: list[dict[str, Any]] = []
    seen: set[str] = set()
    for stmt_id, title, body in split_doctrine_sections(text):
        if stmt_id in seen:
            return {
                "verdict": "fail",
                "error": "duplicate-doctrine-id",
                "duplicateId": stmt_id,
                "statements": statements,
            }
        seen.add(stmt_id)

        rationale = ""
        signal = ""
        manual = False
        for field_match in FIELD_RE.finditer(body):
            key = field_match.group(1)
            value = field_match.group(2).strip()
            if key == "Rationale":
                rationale = value
            elif key == "Signal":
                signal = value
            elif key == "manual":
                manual = value.lower() in {"true", "yes", "1"}

        if not rationale:
            return {
                "verdict": "fail",
                "error": "missing-rationale",
                "id": stmt_id,
                "statements": statements,
            }
        if not manual and not signal:
            return {
                "verdict": "fail",
                "error": "missing-signal",
                "id": stmt_id,
                "statements": statements,
            }

        statements.append(
            {
                "id": stmt_id,
                "title": title,
                "rationale": rationale,
                "signal": signal or None,
                "manual": manual,
            }
        )

    if not statements:
        return {"verdict": "fail", "error": "empty-doctrine-artifact", "statements": []}

    numbers = sorted(int(stmt["id"].split("-", 1)[1]) for stmt in statements)
    expected = list(range(1, numbers[-1] + 1))
    if numbers != expected:
        return {
            "verdict": "fail",
            "error": "missing-doctrine-id",
            "expected": [f"AD-{n}" for n in expected],
            "present": [stmt["id"] for stmt in statements],
            "statements": statements,
        }

    return {
        "verdict": "pass",
        "version": version,
        "statements": sorted(statements, key=lambda item: int(item["id"].split("-", 1)[1])),
    }


def parse_doctrine(root: Path, *, path: Path | None = None) -> dict[str, Any]:
    doc_path = path or doctrine_path(root)
    if not doc_path.is_file():
        return {"verdict": "fail", "error": "doctrine-artifact-missing", "path": str(doc_path)}
    return parse_doctrine_text(doc_path.read_text(encoding="utf-8"))


def consumer_doctrine_path(root: Path) -> Path:
    return root / CONSUMER_DOCTRINE_REL


def load_consumer_doctrine(root: Path, *, path: Path | None = None) -> dict[str, Any]:
    doc_path = path or consumer_doctrine_path(root)
    if not doc_path.is_file():
        return {"verdict": "skip", "error": "consumer-doctrine-missing", "path": str(doc_path)}
    try:
        document = json.loads(doc_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"verdict": "fail", "error": "consumer-doctrine-parse-error", "detail": str(exc)}
    if not isinstance(document, dict):
        return {"verdict": "fail", "error": "consumer-doctrine-invalid"}
    try:
        rel = str(doc_path.resolve().relative_to(root.resolve()))
    except ValueError:
        rel = str(doc_path)
    return {"verdict": "pass", "document": document, "path": rel}


def extract_consumer_vocabulary(document: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    architecture = document.get("architecture")
    if not isinstance(architecture, dict):
        return {key: [] for key in CONSUMER_VOCABULARY_KEYS}
    vocabulary: dict[str, list[dict[str, Any]]] = {}
    for key in CONSUMER_VOCABULARY_KEYS:
        entries = architecture.get(key)
        vocabulary[key] = list(entries) if isinstance(entries, list) else []
    return vocabulary


def consumer_entry_ids(vocabulary: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    by_id: dict[str, str] = {}
    for category, entries in vocabulary.items():
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            entry_id = entry.get("id")
            if not isinstance(entry_id, str) or not CONSUMER_ENTRY_ID_RE.fullmatch(entry_id):
                continue
            if entry_id in by_id:
                by_id[entry_id] = f"{by_id[entry_id]},{category}[{index}]"
            else:
                by_id[entry_id] = category
    return by_id


def validate_consumer_doctrine_document(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in CONSUMER_FORBIDDEN_ROOT_KEYS:
        if key in document:
            errors.append(f"forbidden root key: {key}")
    if document.get("version") != "ProjectDoctrine@v1":
        errors.append("version must be ProjectDoctrine@v1")
    architecture = document.get("architecture")
    if architecture is not None:
        if not isinstance(architecture, dict):
            errors.append("architecture must be an object")
        else:
            for key in architecture:
                if key not in CONSUMER_VOCABULARY_KEYS:
                    errors.append(f"unknown architecture key: {key}")
            for category in CONSUMER_VOCABULARY_KEYS:
                entries = architecture.get(category)
                if entries is None:
                    continue
                if not isinstance(entries, list):
                    errors.append(f"architecture.{category} must be a list")
                    continue
                for index, entry in enumerate(entries):
                    prefix = f"architecture.{category}[{index}]"
                    if not isinstance(entry, dict):
                        errors.append(f"{prefix} must be an object")
                        continue
                    entry_id = entry.get("id")
                    name = entry.get("name")
                    if not isinstance(entry_id, str) or not CONSUMER_ENTRY_ID_RE.fullmatch(entry_id):
                        errors.append(f"{prefix}: invalid id")
                    elif BUNDLED_AD_ID_RE.fullmatch(entry_id):
                        errors.append(
                            f"{prefix}: id {entry_id!r} reuses bundled Shipwright-self AD id"
                        )
                    if not isinstance(name, str) or not name.strip():
                        errors.append(f"{prefix}: name required")
    assessment = document.get("assessment")
    if assessment is not None and not isinstance(assessment, dict):
        errors.append("assessment must be an object")
    return errors


def _normalize_consumer_assessment_document(loaded: dict[str, Any]) -> dict[str, Any]:
    """Normalize read-only assessment YAML to ``entries`` (never mutates doctrine SoT)."""
    if isinstance(loaded.get("entries"), list):
        return {"entries": list(loaded["entries"])}
    # Allow Shipwright-style ``assessments`` key as a read-only alias for consumer YAML.
    if isinstance(loaded.get("assessments"), list):
        return {"entries": list(loaded["assessments"])}
    return loaded


def load_consumer_assessment_yaml(root: Path, document: dict[str, Any]) -> dict[str, Any]:
    """Load consumer assessment data as a read-only input (does not write doctrine)."""
    assessment = document.get("assessment")
    if not isinstance(assessment, dict):
        return {"verdict": "skip", "error": "consumer-assessment-missing"}
    artifact_path = assessment.get("artifactPath")
    if isinstance(artifact_path, str) and artifact_path.strip():
        yaml_path = root / artifact_path.strip()
        if not yaml_path.is_file():
            return {"verdict": "fail", "error": "consumer-assessment-artifact-missing", "path": str(yaml_path)}
        try:
            loaded = safe_load(yaml_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            return {"verdict": "fail", "error": "consumer-assessment-parse-error", "detail": str(exc)}
        if not isinstance(loaded, dict):
            return {"verdict": "fail", "error": "consumer-assessment-invalid"}
        normalized = _normalize_consumer_assessment_document(loaded)
        return {
            "verdict": "pass",
            "document": normalized,
            "source": "artifact",
            "path": str(yaml_path),
            "readOnly": True,
        }
    entries = assessment.get("entries")
    if isinstance(entries, list):
        return {
            "verdict": "pass",
            "document": {"entries": entries},
            "source": "doctrine",
            "readOnly": True,
        }
    return {"verdict": "skip", "error": "consumer-assessment-missing"}


def evaluate_consumer_assessments(
    root: Path,
    *,
    doctrine: dict[str, Any] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    loaded = doctrine or load_consumer_doctrine(root)
    if loaded.get("verdict") == "skip":
        return {
            "verdict": "skip",
            "failed": [],
            "waived": [],
            "manual": [],
            "entries": [],
        }
    if loaded.get("verdict") != "pass":
        return {
            "verdict": "fail",
            "error": loaded.get("error", "consumer-doctrine-invalid"),
            "failed": [],
            "waived": [],
            "manual": [],
        }

    document = loaded["document"]
    errors = validate_consumer_doctrine_document(document)
    if errors:
        return {
            "verdict": "fail",
            "error": "consumer-doctrine-schema-invalid",
            "errors": errors,
            "failed": [],
            "waived": [],
            "manual": [],
        }

    vocabulary = extract_consumer_vocabulary(document)
    known_ids = set(consumer_entry_ids(vocabulary))
    assessment_result = load_consumer_assessment_yaml(root, document)
    if assessment_result.get("verdict") == "skip":
        return {
            "verdict": "pass",
            "failed": [],
            "waived": [],
            "manual": [],
            "entries": sorted(known_ids),
            "vocabulary": {key: len(vocabulary[key]) for key in CONSUMER_VOCABULARY_KEYS},
        }
    if assessment_result.get("verdict") != "pass":
        return {
            "verdict": "fail",
            "error": assessment_result.get("error", "consumer-assessment-invalid"),
            "failed": [],
            "waived": [],
            "manual": [],
        }

    assessment_doc = assessment_result["document"]
    entries = assessment_doc.get("entries") if isinstance(assessment_doc.get("entries"), list) else []
    failed: list[str] = []
    waived: list[str] = []
    manual: list[str] = []
    seen: set[str] = set()

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            failed.append(f"entry[{index}]")
            continue
        entry_id = str(entry.get("id") or "")
        verdict = str(entry.get("verdict") or "")
        if not entry_id or not CONSUMER_ENTRY_ID_RE.fullmatch(entry_id):
            failed.append(entry_id or f"entry[{index}]")
            continue
        if entry_id in seen:
            failed.append(entry_id)
            continue
        seen.add(entry_id)
        if entry_id not in known_ids:
            failed.append(entry_id)
            continue
        if verdict == "pass":
            continue
        if verdict == "manual":
            manual.append(entry_id)
            continue
        if verdict == "waived":
            waiver = entry.get("waiver") if isinstance(entry.get("waiver"), dict) else {}
            if waiver_is_expired(waiver, today=today):
                failed.append(entry_id)
            else:
                waived.append(entry_id)
            continue
        failed.append(entry_id)

    overall = "pass" if not failed else "fail"
    return {
        "verdict": overall,
        "failed": sorted(failed),
        "waived": sorted(waived),
        "manual": sorted(manual),
        "entries": sorted(known_ids),
        "vocabulary": {key: len(vocabulary[key]) for key in CONSUMER_VOCABULARY_KEYS},
    }


def validate_assessment_document(document: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["assessment must be a mapping"]

    allowed_top = {"doctrineVersion", "assessments"}
    for key in document:
        if key not in allowed_top:
            errors.append(f"unknown top-level key: {key}")

    version = document.get("doctrineVersion")
    if not isinstance(version, int) or version < 1:
        errors.append("doctrineVersion must be an integer >= 1")

    assessments = document.get("assessments")
    if not isinstance(assessments, list):
        errors.append("assessments must be a list")
        return errors

    seen: set[str] = set()
    for index, entry in enumerate(assessments):
        prefix = f"assessments[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{prefix} must be an object")
            continue
        allowed_entry = {"id", "verdict", "evidence", "waiver"}
        for key in entry:
            if key not in allowed_entry:
                errors.append(f"{prefix}: unknown key {key}")

        stmt_id = entry.get("id")
        if not isinstance(stmt_id, str) or not re.fullmatch(r"AD-[0-9]+", stmt_id):
            errors.append(f"{prefix}: invalid id")
        elif stmt_id in seen:
            errors.append(f"{prefix}: duplicate id {stmt_id}")
        else:
            seen.add(stmt_id)

        verdict = entry.get("verdict")
        if verdict not in VERDICTS:
            errors.append(f"{prefix}: invalid verdict")

        waiver = entry.get("waiver")
        if verdict == "waived":
            if not isinstance(waiver, dict):
                errors.append(f"{prefix}: waived requires waiver object")
            else:
                allowed_waiver = {"actor", "reason", "expires"}
                for key in waiver:
                    if key not in allowed_waiver:
                        errors.append(f"{prefix}.waiver: unknown key {key}")
                for required in ("actor", "reason", "expires"):
                    value = waiver.get(required) if isinstance(waiver, dict) else None
                    if not isinstance(value, str) or not value.strip():
                        errors.append(f"{prefix}.waiver: {required} required")
        elif waiver is not None:
            errors.append(f"{prefix}: waiver only allowed when verdict is waived")

    return errors


def load_assessment_yaml(root: Path, *, path: Path | None = None) -> dict[str, Any]:
    yaml_path = path or assessment_path(root)
    if not yaml_path.is_file():
        return {"verdict": "fail", "error": "assessment-missing", "path": str(yaml_path)}
    try:
        document = safe_load(yaml_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"verdict": "fail", "error": "assessment-parse-error", "detail": str(exc)}
    errors = validate_assessment_document(document)
    if errors:
        return {"verdict": "fail", "error": "assessment-schema-invalid", "errors": errors}
    return {"verdict": "pass", "document": document}


def waiver_is_expired(waiver: dict[str, Any], *, today: date | None = None) -> bool:
    today = today or utc_today()
    expires = parse_iso_date(str(waiver.get("expires") or ""))
    if expires is None:
        return True
    return expires < today


def is_agent_dispatch_path() -> bool:
    parent = os.environ.get("SW_DISPATCH_PARENT_COMMAND", "").strip().lower()
    if parent in {"sw-doc"}:
        return True
    if os.environ.get("SW_DOC_ORCHESTRATOR", "").strip().lower() in {"1", "true", "yes"}:
        return True
    if os.environ.get("SW_AUTONOMOUS_DISPATCH", "").strip().lower() in {"1", "true", "yes"}:
        return True
    chain = os.environ.get("SW_DISPATCH_CHAIN", "").lower()
    return "sw-doc" in chain and "sw-tasks" in chain


def evaluate_signal(root: Path, statement: dict[str, Any]) -> bool:
    if statement.get("manual"):
        return True
    stmt_id = str(statement.get("id") or "")
    if stmt_id == "AD-1":
        proc = subprocess.run(
            ["python3", "scripts/zero-shell-guard.py"],
            cwd=str(root),
            capture_output=True,
            text=True,
        )
        return proc.returncode == 0
    if stmt_id == "AD-2":
        manifest = root / "core/sw-reference/gate-manifest.json"
        if not manifest.is_file():
            return False
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False
        gates = data.get("gates") if isinstance(data.get("gates"), list) else []
        for gate in gates:
            if isinstance(gate, dict) and gate.get("id") == "check-gate":
                entry = gate.get("entrypoint") if isinstance(gate.get("entrypoint"), dict) else {}
                return str(entry.get("script") or "") == "scripts/check-gate.py"
        return False
    if stmt_id == "AD-3":
        host = root / "scripts/host_lib.py"
        if not host.is_file():
            return False
        host_text = host.read_text(encoding="utf-8", errors="replace")
        return "credentials.resolver" in host_text
    if stmt_id == "AD-4":
        worktree = root / "scripts/worktree.py"
        if not worktree.is_file():
            return False
        text = worktree.read_text(encoding="utf-8", errors="replace")
        return "def cmd_provision" in text
    if stmt_id == "AD-5":
        return (root / "scripts/docs-merge.py").is_file() and (
            root / "scripts/docs-edit-route.py"
        ).is_file()
    signal = str(statement.get("signal") or "").strip()
    if signal.startswith("`") and signal.endswith("`"):
        command = signal.strip("`").strip()
        parts = command.split()
        if not parts:
            return False
        proc = subprocess.run(parts, cwd=str(root), capture_output=True, text=True)
        return proc.returncode == 0
    return False


def evaluate_assessments(
    root: Path,
    *,
    doctrine: dict[str, Any] | None = None,
    assessment: dict[str, Any] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    doctrine_result = doctrine or parse_doctrine(root)
    if doctrine_result.get("verdict") != "pass":
        return {
            "verdict": "fail",
            "error": doctrine_result.get("error", "doctrine-invalid"),
            "failed": [],
            "waived": [],
            "manual": [],
        }

    assessment_result = assessment or load_assessment_yaml(root)
    if assessment_result.get("verdict") != "pass":
        return {
            "verdict": "fail",
            "error": assessment_result.get("error", "assessment-invalid"),
            "failed": [],
            "waived": [],
            "manual": [],
        }

    document = assessment_result["document"]
    doctrine_version = doctrine_result.get("version")
    if doctrine_version is not None and document.get("doctrineVersion") != doctrine_version:
        return {
            "verdict": "fail",
            "error": "doctrine-version-mismatch",
            "failed": [],
            "waived": [],
            "manual": [],
            "expected": doctrine_version,
            "actual": document.get("doctrineVersion"),
        }

    by_id = {str(entry.get("id")): entry for entry in document.get("assessments", [])}
    failed: list[str] = []
    waived: list[str] = []
    manual: list[str] = []

    for statement in doctrine_result.get("statements", []):
        stmt_id = str(statement.get("id"))
        entry = by_id.get(stmt_id)
        if entry is None:
            failed.append(stmt_id)
            continue

        verdict = str(entry.get("verdict") or "")
        if verdict == "pass":
            if not statement.get("manual") and not evaluate_signal(root, statement):
                failed.append(stmt_id)
            continue
        if verdict == "manual":
            manual.append(stmt_id)
            continue
        if verdict == "waived":
            waiver = entry.get("waiver") if isinstance(entry.get("waiver"), dict) else {}
            if waiver_is_expired(waiver, today=today):
                failed.append(stmt_id)
            else:
                waived.append(stmt_id)
            continue
        if verdict == "fail":
            failed.append(stmt_id)
            continue
        failed.append(stmt_id)

    overall = "pass" if not failed else "fail"
    return {
        "verdict": overall,
        "failed": sorted(failed),
        "waived": sorted(waived),
        "manual": sorted(manual),
        "doctrineVersion": document.get("doctrineVersion"),
    }


def evaluate(root: Path, *, today: date | None = None) -> dict[str, Any]:
    mode = assessment_mode(root)
    if mode == "off":
        return {"verdict": "skip", "mode": mode, "failed": [], "waived": [], "manual": []}
    result = evaluate_assessments(root, today=today)
    result["mode"] = mode
    consumer = evaluate_consumer_assessments(root, today=today)
    result["consumer"] = consumer
    if consumer.get("verdict") == "fail" and mode == "blocking":
        result["verdict"] = "fail"
        result["failed"] = sorted(set(result.get("failed", [])) | set(consumer.get("failed", [])))
    return result


def exit_code_for_result(result: dict[str, Any]) -> int:
    mode = str(result.get("mode") or "off")
    verdict = str(result.get("verdict") or "")
    if mode == "off" or verdict == "skip":
        return 0
    if mode == "advisory":
        return 0
    if mode == "blocking" and verdict == "fail":
        return 20
    return 0


def cmd_validate_doctrine(root: Path, args: argparse.Namespace) -> int:
    path = Path(args.path) if args.path else doctrine_path(root)
    result = parse_doctrine(root, path=path)
    emit(result, 0 if result.get("verdict") == "pass" else 20)


def cmd_validate_consumer_doctrine(root: Path, args: argparse.Namespace) -> int:
    path = Path(args.path) if args.path else consumer_doctrine_path(root)
    loaded = load_consumer_doctrine(root, path=path)
    if loaded.get("verdict") == "skip":
        emit(loaded, 0)
    if loaded.get("verdict") != "pass":
        emit(loaded, 20)
    errors = validate_consumer_doctrine_document(loaded["document"])
    if errors:
        emit(
            {
                "verdict": "fail",
                "error": "consumer-doctrine-schema-invalid",
                "errors": errors,
            },
            20,
        )
    vocabulary = extract_consumer_vocabulary(loaded["document"])
    emit(
        {
            "verdict": "pass",
            "path": loaded.get("path"),
            "vocabulary": {key: len(vocabulary[key]) for key in CONSUMER_VOCABULARY_KEYS},
        },
        0,
    )


def cmd_evaluate_consumer(root: Path, args: argparse.Namespace) -> int:
    today = parse_iso_date(args.today) if getattr(args, "today", None) else None
    result = evaluate_consumer_assessments(root, today=today)
    code = 0
    if result.get("verdict") == "fail":
        code = 20
    emit(result, code)


def cmd_validate_assessment(root: Path, args: argparse.Namespace) -> int:
    path = Path(args.path) if args.path else assessment_path(root)
    result = load_assessment_yaml(root, path=path)
    emit(result, 0 if result.get("verdict") == "pass" else 20)


def cmd_evaluate(root: Path, args: argparse.Namespace) -> int:
    today = parse_iso_date(args.today) if getattr(args, "today", None) else None
    result = evaluate(root, today=today)
    emit(result, exit_code_for_result(result))


def cmd_record_waiver(root: Path, args: argparse.Namespace) -> int:
    if is_agent_dispatch_path():
        emit(
            {
                "verdict": "fail",
                "action": "architecture-assessment-record-waiver",
                "error": "waiver refused on autonomous dispatch paths",
                "cause": "agent-dispatch-override-denied",
            },
            20,
        )

    actor = str(getattr(args, "actor", "") or "").strip()
    reason = str(getattr(args, "reason", "") or "").strip()
    expires = str(getattr(args, "expires", "") or "").strip()
    stmt_id = str(getattr(args, "id", "") or "").strip()
    if not actor or not reason or not expires:
        emit(
            {
                "verdict": "fail",
                "action": "architecture-assessment-record-waiver",
                "error": "actor, reason, and expires are required",
                "cause": "missing-attribution",
            },
            20,
        )
    if not re.fullmatch(r"AD-[0-9]+", stmt_id):
        emit(
            {
                "verdict": "fail",
                "action": "architecture-assessment-record-waiver",
                "error": "invalid doctrine id",
            },
            20,
        )

    doctrine = parse_doctrine(root)
    if doctrine.get("verdict") != "pass":
        emit({"verdict": "fail", "error": "doctrine-invalid", "detail": doctrine}, 20)

    yaml_path = assessment_path(root)
    if yaml_path.is_file():
        loaded = load_assessment_yaml(root, path=yaml_path)
        if loaded.get("verdict") != "pass":
            emit(loaded, 20)
        document = loaded["document"]
    else:
        version = doctrine.get("version") or 1
        document = {"doctrineVersion": version, "assessments": []}

    assessments = list(document.get("assessments") or [])
    updated = False
    for entry in assessments:
        if str(entry.get("id")) == stmt_id:
            entry["verdict"] = "waived"
            entry["waiver"] = {"actor": actor, "reason": reason, "expires": expires}
            updated = True
            break
    if not updated:
        assessments.append(
            {
                "id": stmt_id,
                "verdict": "waived",
                "waiver": {"actor": actor, "reason": reason, "expires": expires},
            }
        )
    document["assessments"] = sorted(assessments, key=lambda item: int(str(item["id"]).split("-", 1)[1]))
    yaml_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [f"doctrineVersion: {document['doctrineVersion']}", "assessments:"]
    for entry in document["assessments"]:
        lines.append(f"  - id: {entry['id']}")
        lines.append(f"    verdict: {entry['verdict']}")
        if entry.get("evidence"):
            lines.append(f"    evidence: {json.dumps(entry['evidence'])}")
        waiver = entry.get("waiver")
        if isinstance(waiver, dict):
            lines.append("    waiver:")
            lines.append(f"      actor: {json.dumps(waiver.get('actor'))}")
            lines.append(f"      reason: {json.dumps(waiver.get('reason'))}")
            lines.append(f"      expires: {json.dumps(waiver.get('expires'))}")
    yaml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    emit(
        {
            "verdict": "pass",
            "action": "architecture-assessment-record-waiver",
            "id": stmt_id,
            "path": str(yaml_path.relative_to(root)),
        },
        0,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="architecture_assessment.py")
    parser.add_argument("--root", default=".", help="Repository root")
    sub = parser.add_subparsers(dest="command")

    validate_doctrine = sub.add_parser("validate-doctrine")
    validate_doctrine.add_argument("--path")

    validate_consumer = sub.add_parser("validate-consumer-doctrine")
    validate_consumer.add_argument("--path")

    validate_assessment = sub.add_parser("validate-assessment")
    validate_assessment.add_argument("--path")

    evaluate_cmd = sub.add_parser("evaluate")
    evaluate_cmd.add_argument("--today", help="ISO date override for waiver expiry tests")

    evaluate_consumer_cmd = sub.add_parser("evaluate-consumer")
    evaluate_consumer_cmd.add_argument("--today", help="ISO date override for waiver expiry tests")

    record_waiver = sub.add_parser("record-waiver")
    record_waiver.add_argument("id")
    record_waiver.add_argument("--actor", default="")
    record_waiver.add_argument("--reason", default="")
    record_waiver.add_argument("--expires", default="")

    parser.set_defaults(command="evaluate")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    command = args.command or "evaluate"
    if command == "validate-doctrine":
        return cmd_validate_doctrine(root, args)
    if command == "validate-consumer-doctrine":
        return cmd_validate_consumer_doctrine(root, args)
    if command == "validate-assessment":
        return cmd_validate_assessment(root, args)
    if command == "record-waiver":
        return cmd_record_waiver(root, args)
    if command == "evaluate-consumer":
        return cmd_evaluate_consumer(root, args)
    return cmd_evaluate(root, args)


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
