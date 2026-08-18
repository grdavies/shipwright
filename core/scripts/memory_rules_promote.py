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

ALLOWLIST_REL = Path(".cursor") / "sw-memory-rule-allowlist.json"
NEEDS_RECONCILE_REL = Path(".cursor") / "sw-memory" / "needs-reconcile.json"
REVOKED_REL = Path(".cursor") / "sw-memory" / "revoked-rules.json"
RULES_CACHE_REL = Path(".cursor") / "sw-memory" / "rules-cache.json"
IN_REPO_RULES_REL = Path(".cursor") / "sw-memory" / "rules"

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
    if not str(approval.get("provenance") or "").strip():
        raise RuleWriteRefused(
            "approval missing provenance",
            cause="rule-write-provenance-missing",
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


def load_allowlist_ids(root: Path) -> list[str]:
    path = root / ALLOWLIST_REL
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise RuleWriteRefused("rule allowlist must be a JSON array", cause="allowlist-corrupt")
    return [str(item) for item in data]


def write_allowlist_ids(root: Path, ids: list[str]) -> None:
    path = root / ALLOWLIST_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    unique: list[str] = []
    for item in ids:
        if item not in unique:
            unique.append(item)
    path.write_text(json.dumps(unique, indent=2) + "\n", encoding="utf-8")


def commit_allowlist(root: Path, rule_id: str) -> list[str]:
    ids = load_allowlist_ids(root)
    if rule_id not in ids:
        ids.append(rule_id)
    write_allowlist_ids(root, ids)
    return ids


def remove_allowlist_id(root: Path, rule_id: str) -> list[str]:
    ids = [item for item in load_allowlist_ids(root) if item != rule_id]
    write_allowlist_ids(root, ids)
    return ids


def needs_reconcile_path(root: Path) -> Path:
    return root / NEEDS_RECONCILE_REL


def write_needs_reconcile(root: Path, payload: dict[str, Any]) -> Path:
    path = needs_reconcile_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def clear_needs_reconcile(root: Path) -> None:
    path = needs_reconcile_path(root)
    if path.is_file():
        path.unlink()


def load_revoked_ids(root: Path) -> set[str]:
    path = root / REVOKED_REL
    if not path.is_file():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return set()
    return {str(item) for item in data}


def write_revoked_ids(root: Path, ids: set[str]) -> None:
    path = root / REVOKED_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(ids), indent=2) + "\n", encoding="utf-8")


def load_rules_cache(root: Path) -> dict[str, Any]:
    path = root / RULES_CACHE_REL
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def write_rules_cache(root: Path, cache: dict[str, Any]) -> None:
    path = root / RULES_CACHE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2) + "\n", encoding="utf-8")


def soft_delete_in_repo_rule(root: Path, rule_id: str) -> str | None:
    path = root / IN_REPO_RULES_REL / f"{rule_id}.md"
    if not path.is_file():
        return None
    dest = path.with_name(f"{rule_id}.md.deleted")
    path.replace(dest)
    return str(dest)


def revoke_rule(root: Path, rule_id: str) -> dict[str, Any]:
    remove_allowlist_id(root, rule_id)
    revoked = load_revoked_ids(root)
    revoked.add(rule_id)
    write_revoked_ids(root, revoked)
    deleted = soft_delete_in_repo_rule(root, rule_id)
    cache = load_rules_cache(root)
    cache.pop(rule_id, None)
    write_rules_cache(root, cache)
    return {
        "verdict": "ok",
        "action": "revoke",
        "ruleId": rule_id,
        "allowlist": load_allowlist_ids(root),
        "revoked": sorted(revoked),
        "softDeleted": deleted,
        "cache": cache,
    }


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
    try:
        result = adapter_writer(root, payload)
    except Exception as exc:
        write_needs_reconcile(
            root,
            {"ruleId": rule_id, "cause": "provider-write-failed", "error": str(exc)},
        )
        raise
    if not isinstance(result, dict) or result.get("verdict") != "ok":
        write_needs_reconcile(
            root,
            {
                "ruleId": rule_id,
                "cause": "provider-write-failed",
                "result": result if isinstance(result, dict) else {"verdict": "fail"},
            },
        )
        return {
            "verdict": "fail",
            "cause": "needs-reconcile",
            "needsReconcile": True,
            "provider": provider,
            "ruleId": rule_id,
        }
    allowlist = commit_allowlist(root, rule_id)
    clear_needs_reconcile(root)
    cache = load_rules_cache(root)
    cache[rule_id] = {"body": body, "contentHash": payload["contentHash"], "provider": provider}
    write_rules_cache(root, cache)
    result["provider"] = provider
    result["capabilities"] = PROVIDER_RULE_CAPABILITIES[provider]
    result["adapterDoc"] = result.get("adapterDoc") or adapter_path_for(provider)
    result["allowlist"] = allowlist
    result["needsReconcile"] = False
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
