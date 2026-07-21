"""Trust boundary + execution chokepoint for capability selection (PRD 021 TR5, R27)."""

from __future__ import annotations

import re
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

PROVIDER_GATES = frozenset({"check-gate.py", "review-local-resolve.py"})
MEMORY_GATES = frozenset({"check-gate.py", "memory-preflight"})
HOOK_GATE_PREFIX = "hooks.json:"

# Named gates for out-of-band memory rules scripts (PRD 071 R4, PRD 074 R4, PRD 075 R4).
# Catalog membership alone does not authorize hook injection.
MEMORY_RULES_SCRIPT_GATES: dict[str, frozenset[str]] = {
    "recallium": frozenset({"recallium-rules.py"}),
    "in-repo": frozenset({"in-repo-rules.py"}),
    "mempalace": frozenset({"mempalace-rules.py"}),
    "basic-memory": frozenset({"basic-memory-rules.py"}),
}

PROVIDER_FAMILY_KEYS: dict[str, str] = {
    "review": "review.provider",
    "review.local": "review.local.provider",
    "memory": "memory.provider",
    "verify": "verify.provider",
    "quality": "quality.provider",
    "code-review": "code-review.provider",
}

GAT_REF_FIXTURE_DIRS = (
    "scripts/test/fixtures/capability-select",
    "scripts/test/fixtures/capability-lint",
)

_GAT_REF_PATTERN = re.compile(r"gateRef\s*:\s*([^\s\"']+\.sh)\b")
_GAT_REF_JSON_PATTERN = re.compile(r'"gateRef"\s*:\s*"([^"]+\.sh)"')


def _py_canonical_exists(repo_root: Path, gate_ref: str) -> bool:
    name = Path(gate_ref).name
    if not name.endswith(".sh"):
        return False
    py_name = name[:-3] + ".py"
    for scripts_dir in (repo_root / "scripts", repo_root / "core" / "scripts"):
        if (scripts_dir / py_name).is_file():
            return True
    return False


def scan_gateref_no_shell(repo_root: Path) -> list[dict[str, str]]:
    """Fail-closed scan for .sh gateRef where canonical .py exists (PRD 050 R17)."""
    violations: list[dict[str, str]] = []
    for rel_dir in GAT_REF_FIXTURE_DIRS:
        base = repo_root / rel_dir
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in {".md", ".json", ".yaml", ".yml"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for pattern in (_GAT_REF_PATTERN, _GAT_REF_JSON_PATTERN):
                for match in pattern.finditer(text):
                    gate_ref = match.group(1)
                    if _py_canonical_exists(repo_root, gate_ref):
                        violations.append(
                            {
                                "path": str(path.relative_to(repo_root)),
                                "gateRef": gate_ref,
                                "canonical": gate_ref.replace(".sh", ".py"),
                            }
                        )
    return violations


def check_gateref_no_shell(repo_root: Path) -> dict[str, Any]:
    violations = scan_gateref_no_shell(repo_root)
    if violations:
        return {
            "verdict": "fail",
            "halt": "gateref-no-shell",
            "violations": violations,
            "remediation": "restore gateRef to canonical .py script names",
        }
    return {"verdict": "pass", "scanned": list(GAT_REF_FIXTURE_DIRS)}


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


def authorize_memory_rules_script(
    provider_id: str,
    script_path: Path | str,
    ctx: dict[str, Any],
    *,
    resolve_config_value: Callable[[dict[str, Any], str], Any],
    is_configured: Callable[[Any], bool],
) -> dict[str, Any]:
    """Authorize a catalog rules script for hook injection (PRD 074 R4)."""
    normalized = str(provider_id or "").strip()
    allowed = MEMORY_RULES_SCRIPT_GATES.get(normalized)
    if not allowed:
        return {
            "authorized": False,
            "refusalReason": "unknown_provider",
            "providerId": normalized,
            "script": Path(str(script_path)).name,
        }

    configured, config_key = provider_configured(
        "memory",
        ctx,
        resolve_config_value=resolve_config_value,
        is_configured=is_configured,
    )
    if not configured:
        return {
            "authorized": False,
            "refusalReason": "unconfigured_provider",
            "providerId": normalized,
            "script": Path(str(script_path)).name,
        }

    config_value = resolve_config_value(ctx.get("config") or {}, config_key or "")
    if not adapter_matches("memory", normalized, config_value):
        return {
            "authorized": False,
            "refusalReason": "config_override_untrusted",
            "providerId": normalized,
            "script": Path(str(script_path)).name,
        }

    basename = Path(str(script_path)).name
    if basename not in allowed:
        return {
            "authorized": False,
            "refusalReason": "unknown_rules_script",
            "providerId": normalized,
            "script": basename,
        }

    return {
        "authorized": True,
        "refusalReason": None,
        "providerId": normalized,
        "script": basename,
    }


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
