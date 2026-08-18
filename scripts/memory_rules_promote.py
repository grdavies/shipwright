#!/usr/bin/env python3
"""Human-gated rule-class promotion via the configured memory provider adapter (PRD 277)."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Callable

from host_lib import load_workflow_config
from memory_lib import memory_section
from memory_provider_catalog import load_catalog
from memory_provider_register import RegistrationError, validate_registration

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent

AUDIT_COMMAND = "sw-memory-audit"
RULE_CATEGORY = "rule"
SUPPORTED_PROVIDERS = (
    "in-repo",
    "recallium",
    "mempalace",
    "basic-memory",
    "obsidian",
)
PROVIDER_RULE_CAPABILITIES: dict[str, dict[str, bool]] = {
    provider: {
        "rulesPromote": True,
        "rulesLoad": True,
        "rulesRevoke": True,
        "rulesAtStartup": True,
    }
    for provider in SUPPORTED_PROVIDERS
}

AdapterWriter = Callable[[Path, dict[str, Any]], dict[str, Any]]

_IRMS_PATH = Path(__file__).resolve().parent / "in-repo-memory-search.py"
_IRMS_SPEC = importlib.util.spec_from_file_location("in_repo_memory_search", _IRMS_PATH)
if _IRMS_SPEC is None or _IRMS_SPEC.loader is None:
    raise ImportError("in-repo-memory-search.py not found")
_IRMS = importlib.util.module_from_spec(_IRMS_SPEC)
_IRMS_SPEC.loader.exec_module(_IRMS)
write_memory_record = _IRMS.write_memory_record


class RuleWriteRefused(Exception):
    """Ordinary store/sync/import attempted a rule-class write without audit approval."""

    def __init__(self, message: str, *, cause: str = "rule-write-unapproved") -> None:
        super().__init__(message)
        self.cause = cause


def content_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def validate_audit_approval(
    approval: dict[str, Any] | None,
    *,
    rule_id: str,
    body: str,
) -> dict[str, Any]:
    if not isinstance(approval, dict) or not approval:
        raise RuleWriteRefused(
            "rule-class writes require /sw-memory-audit approval",
            cause="rule-write-unapproved",
        )
    command = str(approval.get("command") or "").strip()
    if command != AUDIT_COMMAND:
        raise RuleWriteRefused(
            f"rule-class writes require {AUDIT_COMMAND} approval, got {command!r}",
            cause="rule-write-unapproved",
        )
    approved_id = str(approval.get("ruleId") or approval.get("id") or "").strip()
    if approved_id != rule_id:
        raise RuleWriteRefused(
            "approval ruleId does not match write target",
            cause="rule-write-id-mismatch",
        )
    expected = str(approval.get("contentHash") or "").strip()
    actual = content_hash(body)
    if expected != actual:
        raise RuleWriteRefused(
            "approval contentHash does not match body",
            cause="rule-write-hash-mismatch",
        )
    if not str(approval.get("approvedBy") or "").strip():
        raise RuleWriteRefused(
            "approval missing approvedBy",
            cause="rule-write-unapproved",
        )
    return approval


def refuse_unapproved_rule_write(
    *,
    category: str,
    approval: dict[str, Any] | None = None,
    rule_id: str = "",
    body: str = "",
) -> None:
    if str(category or "").strip() != RULE_CATEGORY:
        return
    validate_audit_approval(approval, rule_id=rule_id, body=body)


def configured_provider(root: Path) -> str:
    cfg = load_workflow_config(root)
    provider = str(memory_section(cfg).get("provider") or "").strip()
    if not provider:
        raise RuleWriteRefused("memory.provider is not configured", cause="provider-unconfigured")
    return provider


def assert_provider_registered(root: Path, provider: str) -> dict[str, Any]:
    try:
        return validate_registration(root, provider, catalog=load_catalog(root))
    except RegistrationError as exc:
        raise RuleWriteRefused(str(exc), cause=exc.cause) from exc


def adapter_path_for(provider: str) -> str:
    return f"providers/{provider}.md"


def _in_repo_writer(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    store = root / ".cursor" / "sw-memory"
    record = {
        "id": payload["ruleId"],
        "category": RULE_CATEGORY,
        "fields": {
            "category": RULE_CATEGORY,
            "id": payload["ruleId"],
            "contentHash": payload["contentHash"],
            "provenance": "sw-memory-audit",
        },
        "body": payload["body"],
    }
    path = write_memory_record(store, record)
    return {
        "verdict": "ok",
        "writtenVia": "in-repo-adapter",
        "path": str(path),
        "adapterDoc": adapter_path_for("in-repo"),
    }


def default_adapter_writer(provider: str) -> AdapterWriter:
    if provider == "in-repo":
        return _in_repo_writer

    def _adapter_doc_writer(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
        del root
        return {
            "verdict": "ok",
            "writtenVia": "configured-provider-adapter",
            "adapterDoc": adapter_path_for(provider),
            "ruleId": payload["ruleId"],
            "contentHash": payload["contentHash"],
            "note": "body routed through adapter store/rules-load — not dual-homed locally",
        }

    return _adapter_doc_writer


def promote_rule(
    root: Path,
    *,
    rule_id: str,
    body: str,
    approval: dict[str, Any],
    writer: AdapterWriter | None = None,
) -> dict[str, Any]:
    provider = configured_provider(root)
    if provider not in SUPPORTED_PROVIDERS:
        raise RuleWriteRefused(
            f"unsupported memory.provider for rules-promote: {provider}",
            cause="provider-unsupported",
        )
    assert_provider_registered(root, provider)
    if not PROVIDER_RULE_CAPABILITIES[provider]["rulesPromote"]:
        raise RuleWriteRefused(
            f"provider {provider} missing rulesPromote capability",
            cause="capability-missing",
        )
    validate_audit_approval(approval, rule_id=rule_id, body=body)
    payload = {
        "ruleId": rule_id,
        "body": body,
        "contentHash": content_hash(body),
        "approval": approval,
        "provider": provider,
    }
    adapter_writer = writer or default_adapter_writer(provider)
    result = adapter_writer(root, payload)
    result["provider"] = provider
    result["capabilities"] = PROVIDER_RULE_CAPABILITIES[provider]
    result["adapterDoc"] = result.get("adapterDoc") or adapter_path_for(provider)
    return result


def ordinary_store(
    *,
    category: str,
    rule_id: str = "",
    body: str = "",
    approval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    refuse_unapproved_rule_write(category=category, approval=approval, rule_id=rule_id, body=body)
    return {"verdict": "ok", "action": "store", "category": category}


def memory_sync_store(
    *,
    category: str,
    rule_id: str = "",
    body: str = "",
    approval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    refuse_unapproved_rule_write(category=category, approval=approval, rule_id=rule_id, body=body)
    return {"verdict": "ok", "action": "memory-sync", "category": category}


def import_store(
    *,
    category: str,
    rule_id: str = "",
    body: str = "",
    approval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    refuse_unapproved_rule_write(category=category, approval=approval, rule_id=rule_id, body=body)
    return {"verdict": "ok", "action": "import", "category": category}


def _parse_approval(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    path = Path(raw)
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = json.loads(raw)
    return data if isinstance(data, dict) else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Promote a rule-class memory via audit approval")
    parser.add_argument("--root", default=".", help="workspace root")
    parser.add_argument("--rule-id", required=True)
    parser.add_argument("--body", default="", help="rule body, or - for stdin")
    parser.add_argument("--approval-json", help="approval object or path")
    args = parser.parse_args(argv)
    body = sys.stdin.read() if args.body == "-" else args.body
    root = Path(args.root).resolve()
    try:
        result = promote_rule(
            root,
            rule_id=args.rule_id,
            body=body,
            approval=_parse_approval(args.approval_json),
        )
    except RuleWriteRefused as exc:
        print(json.dumps({"verdict": "fail", "error": str(exc), "cause": exc.cause}, indent=2))
        return 20
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
