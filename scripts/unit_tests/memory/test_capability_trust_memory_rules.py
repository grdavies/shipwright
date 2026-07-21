"""PRD 074 R4 — capability trust gate for memory rules scripts."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from capability_trust import (  # noqa: E402
    MEMORY_RULES_SCRIPT_GATES,
    authorize_memory_rules_script,
)


def _resolve_config_value(config: dict, key: str):
    current = config
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _is_configured(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in {"", "none", "off", "unconfigured", "null"}
    return True


def test_mempalace_rules_script_gate_registered() -> None:
    assert "mempalace" in MEMORY_RULES_SCRIPT_GATES
    assert "mempalace-rules.py" in MEMORY_RULES_SCRIPT_GATES["mempalace"]


def test_basic_memory_rules_script_gate_registered() -> None:
    assert "basic-memory" in MEMORY_RULES_SCRIPT_GATES
    assert "basic-memory-rules.py" in MEMORY_RULES_SCRIPT_GATES["basic-memory"]


def test_authorize_mempalace_rules_script_when_configured() -> None:
    auth = authorize_memory_rules_script(
        "mempalace",
        "providers/mempalace-rules.py",
        {"config": {"memory": {"provider": "mempalace"}}},
        resolve_config_value=_resolve_config_value,
        is_configured=_is_configured,
    )
    assert auth["authorized"] is True
    assert auth["script"] == "mempalace-rules.py"


def test_authorize_basic_memory_rules_script_when_configured() -> None:
    auth = authorize_memory_rules_script(
        "basic-memory",
        "providers/basic-memory-rules.py",
        {"config": {"memory": {"provider": "basic-memory"}}},
        resolve_config_value=_resolve_config_value,
        is_configured=_is_configured,
    )
    assert auth["authorized"] is True
    assert auth["script"] == "basic-memory-rules.py"


def test_catalog_membership_alone_does_not_authorize_wrong_script() -> None:
    auth = authorize_memory_rules_script(
        "mempalace",
        "providers/recallium-rules.py",
        {"config": {"memory": {"provider": "mempalace"}}},
        resolve_config_value=_resolve_config_value,
        is_configured=_is_configured,
    )
    assert auth["authorized"] is False
    assert auth["refusalReason"] == "unknown_rules_script"


def test_basic_memory_catalog_alone_does_not_authorize_wrong_script() -> None:
    auth = authorize_memory_rules_script(
        "basic-memory",
        "providers/mempalace-rules.py",
        {"config": {"memory": {"provider": "basic-memory"}}},
        resolve_config_value=_resolve_config_value,
        is_configured=_is_configured,
    )
    assert auth["authorized"] is False
    assert auth["refusalReason"] == "unknown_rules_script"


def test_config_override_untrusted_blocks_rules_script() -> None:
    auth = authorize_memory_rules_script(
        "mempalace",
        "providers/mempalace-rules.py",
        {"config": {"memory": {"provider": "recallium"}}},
        resolve_config_value=_resolve_config_value,
        is_configured=_is_configured,
    )
    assert auth["authorized"] is False
    assert auth["refusalReason"] == "config_override_untrusted"


def test_basic_memory_config_override_untrusted_blocks_rules_script() -> None:
    auth = authorize_memory_rules_script(
        "basic-memory",
        "providers/basic-memory-rules.py",
        {"config": {"memory": {"provider": "recallium"}}},
        resolve_config_value=_resolve_config_value,
        is_configured=_is_configured,
    )
    assert auth["authorized"] is False
    assert auth["refusalReason"] == "config_override_untrusted"


@pytest.mark.parametrize("provider_id", ["recallium", "in-repo", "mempalace", "basic-memory"])
def test_known_providers_have_named_script_gates(provider_id: str) -> None:
    gates = MEMORY_RULES_SCRIPT_GATES[provider_id]
    assert f"{provider_id}-rules.py" in gates
