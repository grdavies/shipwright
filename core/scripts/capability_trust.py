"""Trust boundary + execution chokepoint for capability selection (PRD 021 TR5, R27)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

# Kernel/safety hooks — excluded from manifest selection and reordering (TR5).
KERNEL_HOOK_SLOTS = frozenset({"beforeSubmitPrompt", "stop"})

KERNEL_HOOK_SOURCE_MARKERS = (
    "before-submit-guardrails",
    "before_submit_guardrails",
    "memory-sync-stop",
    "memory_sync_stop",
    "memory_prework_gate",
    "guardrail_core",
    "memory-redact",
)

# Manifest hooks may only augment non-safety emitter slots.
MANIFEST_HOOK_SLOTS = frozenset({"sessionStart", "preToolUse"})

PROVIDER_GATES = frozenset({"check-gate.sh", "review-local-resolve.sh"})
MEMORY_GATES = frozenset({"check-gate.sh", "memory-preflight"})
HOOK_GATE_PREFIX = "hooks.json:"

PROVIDER_FAMILY_KEYS: dict[str, str] = {
    "review": "review.provider",
    "review.local": "review.local.provider",
    "memory": "memory.provider",
    "verify": "verify.provider",
    "code-review": "code-review.provider",
}


def is_kernel_hook_source(source_path: str) -> bool:
    normalized = source_path.replace("\\", "/").lower()
    return any(marker in normalized for marker in KERNEL_HOOK_SOURCE_MARKERS)


def parse_hook_slot(gate_ref: str | None) -> str | None:
    if not gate_ref or not str(gate_ref).startswith(HOOK_GATE_PREFIX):
        return None
    return str(gate_ref)[len(HOOK_GATE_PREFIX) :]


def entry_source_exists(repo_root: Path, entry: dict[str, Any]) -> bool:
    source_path = entry.get("sourcePath")
    if not isinstance(source_path, str):
        return False
    return (repo_root / source_path).is_file()


def provider_configured(
    provider_family: str | None,
    ctx: dict[str, Any],
    *,
    resolve_config_value: Callable[[dict[str, Any], str], Any],
    is_configured: Callable[[Any], bool],
) -> tuple[bool, str | None]:
    if not provider_family:
        return False, None
    key = PROVIDER_FAMILY_KEYS.get(str(provider_family))
    if not key:
        return False, None
    value = resolve_config_value(ctx.get("config") or {}, key)
    return is_configured(value), key


def adapter_matches(provider_family: str | None, adapter_id: str | None, config_value: Any) -> bool:
    if adapter_id is None or config_value is None:
        return False
    if str(provider_family) == "code-review":
        return str(config_value).strip().lower() in {
            str(adapter_id).strip().lower(),
            "native",
            "ce-code-review",
        }
    return str(config_value).strip().lower() == str(adapter_id).strip().lower()


def authorize_executable(
    entry: dict[str, Any],
    ctx: dict[str, Any],
    *,
    eligible: bool,
    repo_root: Path | None,
    resolve_config_value: Callable[[dict[str, Any], str], Any],
    is_configured: Callable[[Any], bool],
) -> dict[str, Any]:
    executable = bool(entry.get("executable"))
    metadata = (entry.get("capability") or {}).get("metadata") or {}
    gate_ref = metadata.get("gateRef")
    kind = entry.get("kind")

    if not eligible:
        return {
            "eligible": False,
            "executable": executable,
            "authorized": False,
            "gateRef": gate_ref,
            "refusalReason": "not_eligible",
        }
    if not executable:
        return {
            "eligible": True,
            "executable": False,
            "authorized": True,
            "gateRef": None,
            "refusalReason": None,
        }

    if repo_root is not None and not entry_source_exists(repo_root, entry):
        return {
            "eligible": True,
            "executable": True,
            "authorized": False,
            "gateRef": gate_ref,
            "refusalReason": "index_tamper",
        }

    if kind == "hook":
        slot = parse_hook_slot(gate_ref)
        if not slot or slot in KERNEL_HOOK_SLOTS or slot not in MANIFEST_HOOK_SLOTS:
            return {
                "eligible": True,
                "executable": True,
                "authorized": False,
                "gateRef": gate_ref,
                "refusalReason": "unknown_hook",
            }
        return {
            "eligible": True,
            "executable": True,
            "authorized": True,
            "gateRef": gate_ref,
            "refusalReason": None,
        }

    provider_family = metadata.get("providerFamily")
    configured, config_key = provider_configured(
        provider_family,
        ctx,
        resolve_config_value=resolve_config_value,
        is_configured=is_configured,
    )
    if not configured:
        return {
            "eligible": True,
            "executable": True,
            "authorized": False,
            "gateRef": gate_ref,
            "refusalReason": "unconfigured_provider",
        }

    config_value = resolve_config_value(ctx.get("config") or {}, config_key or "")
    adapter_id = metadata.get("adapterId")
    if provider_family and adapter_id and not adapter_matches(provider_family, adapter_id, config_value):
        return {
            "eligible": True,
            "executable": True,
            "authorized": False,
            "gateRef": gate_ref,
            "refusalReason": "config_override_untrusted",
        }

    if str(provider_family) == "memory":
        if gate_ref not in MEMORY_GATES:
            return {
                "eligible": True,
                "executable": True,
                "authorized": False,
                "gateRef": gate_ref,
                "refusalReason": "unknown_gate",
            }
    elif gate_ref not in PROVIDER_GATES:
        return {
            "eligible": True,
            "executable": True,
            "authorized": False,
            "gateRef": gate_ref,
            "refusalReason": "unknown_gate",
        }

    if not gate_ref:
        return {
            "eligible": True,
            "executable": True,
            "authorized": False,
            "gateRef": gate_ref,
            "refusalReason": "unknown_gate",
        }

    return {
        "eligible": True,
        "executable": True,
        "authorized": True,
        "gateRef": gate_ref,
        "refusalReason": None,
    }
