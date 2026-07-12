"""Advisory token-budget field and partial-result handoff (PRD 064 R12 / D2)."""
from __future__ import annotations

import json
from typing import Any

DEFAULT_ADVISORY_TOKEN_BUDGET = 32000


def load_token_budget_config(config: dict[str, Any]) -> dict[str, Any]:
    dispatch = config.get("dispatch")
    if not isinstance(dispatch, dict):
        return {}
    budget = dispatch.get("tokenBudget")
    return budget if isinstance(budget, dict) else {}


def resolve_token_budget(config: dict[str, Any]) -> dict[str, Any]:
    """Always-present advisory token budget — never an enforced stop (D2)."""
    budget_cfg = load_token_budget_config(config)
    advisory = budget_cfg.get("advisory", DEFAULT_ADVISORY_TOKEN_BUDGET)
    try:
        advisory_value = int(advisory)
    except (TypeError, ValueError):
        advisory_value = DEFAULT_ADVISORY_TOKEN_BUDGET
    if advisory_value < 1:
        advisory_value = DEFAULT_ADVISORY_TOKEN_BUDGET
    return {
        "advisory": advisory_value,
        "enforced": False,
        "used": None,
    }


def format_partial_result_handoff(token_budget: dict[str, Any]) -> str:
    """Structured partial-result handoff contract for sub-agent prompts."""
    advisory = token_budget.get("advisory", DEFAULT_ADVISORY_TOKEN_BUDGET)
    contract = {
        "tokenBudgetAdvisory": advisory,
        "enforced": False,
        "onPartialResult": {
            "action": "handoff",
            "requiredFields": [
                "partialResult",
                "completedSteps",
                "remainingSteps",
                "resumeHint",
            ],
            "envelope": "untrusted_payload",
        },
    }
    return (
        "## Partial-result handoff (advisory token budget)\n"
        "```json\n"
        f"{json.dumps(contract, indent=2)}\n"
        "```\n"
        "If you approach the advisory token budget, stop cleanly and return a "
        "structured partial-result object — never truncate mid-thought without handoff."
    )
