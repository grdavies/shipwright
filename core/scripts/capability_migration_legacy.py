"""Legacy capability selection paths retained for migration parity (PRD 021 R13, TR9)."""

from __future__ import annotations

import fnmatch
import json
import os
import re
from pathlib import Path
from typing import Any

from capability_select import (
    POLYSEMOUS_TOKENS,
    normalize_signal_context,
    text_has_token,
    whole_token_pattern,
)

DOC_REVIEW_CORE = [
    "sw-coherence-reviewer",
    "sw-feasibility-reviewer",
    "sw-scope-guardian-reviewer",
    "sw-product-reviewer",
    "sw-adversarial-reviewer",
    "sw-docs-currency-reviewer",
]

DOC_REVIEW_ALL = DOC_REVIEW_CORE + ["sw-security-reviewer", "sw-design-reviewer"]

SECURITY_TOKENS = [
    "auth",
    "authn",
    "authz",
    "authentication",
    "authorization",
    "login",
    "session",
    "oauth",
    "jwt",
    "payment",
    "payments",
    "billing",
    "PII",
    "credentials",
    "token",
    "encryption",
    "public api",
    "public endpoint",
    "external api",
    "webhook",
]

DESIGN_UNAMBIGUOUS = [
    "UI",
    "UX",
    "wireframe",
    "modal",
    "button",
    "navigation",
    "responsive",
    "accessibility",
    "user flow",
]

DESIGN_HEADINGS = ["UI", "UX", "Screens", "Mockups"]

DESIGN_LINK_PATTERNS = ["figma.com", "figma.io"]

CODE_REVIEW_CORE = [
    "correctness",
    "maintainability",
    "scope-fidelity",
    "testing",
    "security",
]

ADVERSARIAL_THRESHOLD = 50

PROVIDER_FAMILIES = {
    "review.provider": "review",
    "review.local.provider": "review.local",
    "memory.provider": "memory",
    "verify.provider": "verify",
}

UNCONFIGURED_VALUES = frozenset({"", "none", "off", "unconfigured", "null"})


def canonical_bytes(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def is_quick_tier(tier: str | None) -> bool:
    return str(tier or "").strip().lower() == "quick"


def doc_type_from_path(doc_path: str | None) -> str:
    if not doc_path:
        return "unknown"
    path = doc_path.replace("\\", "/")
    if "/docs/decisions/" in path and "/amendments/" in path:
        return "decision-amendment"
    if "/docs/decisions/" in path:
        return "decision-record"
    if "/docs/prds/" in path and "/amendments/" in path:
        return "prd-amendment"
    if "/docs/prds/" in path:
        return "prd-draft"
    return "unknown"


def security_signal_fires(body: str) -> str | None:
    for token in SECURITY_TOKENS:
        if text_has_token(body, token, match_mode="whole_token", case_insensitive=True, exclude_polysemous=False):
            return token
    return None


def design_signal_fires(body: str) -> str | None:
    for token in DESIGN_UNAMBIGUOUS:
        if text_has_token(
            body,
            token,
            match_mode="whole_token",
            case_insensitive=True,
            exclude_polysemous=True,
        ):
            return token
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        heading = re.sub(r"^#+\s*", "", stripped).strip()
        compare = heading.lower()
        for target in DESIGN_HEADINGS:
            if compare == target.lower() or target.lower() in compare:
                return f"heading:{target}"
    lowered = body.lower()
    for pattern in DESIGN_LINK_PATTERNS:
        if pattern in lowered:
            return f"link:{pattern}"
    return None


def legacy_doc_review_select(ctx: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_signal_context(ctx)
    tier = normalized.get("tier")
    doc_path = normalized.get("doc_path")
    body = str(normalized.get("body_snapshot") or "")
    overrides = normalized.get("overrides") or {}
    doc_type = doc_type_from_path(str(doc_path) if doc_path else None)

    if is_quick_tier(str(tier) if tier is not None else None):
        return {
            "family": "doc-review",
            "panel": [],
            "activation": {"core": [], "gated": [], "override": "none", "skipped": True, "reason": "quick-tier"},
        }

    if overrides.get("all"):
        panel = list(DOC_REVIEW_ALL)
        return {
            "family": "doc-review",
            "panel": panel,
            "activation": {
                "core": [p.replace("sw-", "").replace("-reviewer", "") for p in DOC_REVIEW_CORE],
                "gated": [],
                "override": "all",
            },
        }

    persona_override = overrides.get("personas")
    if isinstance(persona_override, list) and persona_override:
        panel = list(DOC_REVIEW_CORE)
        forced = []
        for name in persona_override:
            slug = str(name).strip().lower()
            if slug in {"security", "design"}:
                forced.append(f"sw-{slug}-reviewer")
            elif slug.startswith("sw-"):
                forced.append(slug if slug.endswith("-reviewer") else f"{slug}-reviewer")
            else:
                forced.append(f"sw-{slug}-reviewer")
        panel.extend(forced)
        panel = sorted(set(panel), key=lambda item: DOC_REVIEW_ALL.index(item) if item in DOC_REVIEW_ALL else 999)
        return {
            "family": "doc-review",
            "panel": panel,
            "activation": {
                "core": [p.replace("sw-", "").replace("-reviewer", "") for p in DOC_REVIEW_CORE],
                "gated": [],
                "override": f"personas {', '.join(str(p) for p in persona_override)}",
            },
        }

    if doc_type == "decision-record":
        return {
            "family": "doc-review",
            "panel": list(DOC_REVIEW_ALL),
            "activation": {
                "core": [p.replace("sw-", "").replace("-reviewer", "") for p in DOC_REVIEW_CORE],
                "gated": [],
                "override": "decision-record full panel",
            },
        }

    if doc_type == "prd-amendment":
        panel = ["sw-coherence-reviewer", "sw-scope-guardian-reviewer", "sw-docs-currency-reviewer"]
        return {
            "family": "doc-review",
            "panel": panel,
            "activation": {
                "core": ["coherence", "scope-guardian", "docs-currency"],
                "gated": [],
                "override": "prd-amendment floor",
            },
        }

    if doc_type == "decision-amendment":
        panel = ["sw-coherence-reviewer", "sw-scope-guardian-reviewer", "sw-adversarial-reviewer", "sw-feasibility-reviewer", "sw-docs-currency-reviewer"]
        return {
            "family": "doc-review",
            "panel": panel,
            "activation": {
                "core": ["coherence", "scope-guardian", "adversarial", "feasibility", "docs-currency"],
                "gated": [],
                "override": "decision-amendment floor",
            },
        }

    panel = list(DOC_REVIEW_CORE)
    gated: list[dict[str, str]] = []
    security = security_signal_fires(body)
    if security:
        panel.append("sw-security-reviewer")
        gated.append({"persona": "security", "matched": security})
    design = design_signal_fires(body)
    if design:
        panel.append("sw-design-reviewer")
        gated.append({"persona": "design", "matched": design})

    return {
        "family": "doc-review",
        "panel": panel,
        "activation": {
            "core": [p.replace("sw-", "").replace("-reviewer", "") for p in DOC_REVIEW_CORE],
            "gated": gated,
            "override": "none",
        },
    }


def _is_executable_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped in {"{", "}", "(", ")", "[", "]"}:
        return False
    if re.match(r"^[{}\[\]()]+$", stripped):
        return False
    if re.match(r"^(import\s|from\s+\S+\s+import|#include|using\s|require\(|use\s)", stripped):
        return False
    if re.match(r"^(//|#(?!!)|/\*|\*|--|<!--)", stripped):
        return False
    return True


def digest_rows(digest: dict[str, Any]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for entry in digest.get("files") or []:
        path = str(entry.get("path", ""))
        for line in entry.get("added_lines") or []:
            rows.append((path, str(line)))
    return rows


def legacy_code_review_select(change_digest: dict[str, Any]) -> dict[str, Any]:
    files = change_digest.get("files") or []
    rows = digest_rows(change_digest)
    added_all = rows

    def path_match(path: str, pattern: str) -> bool:
        p = path.replace("\\", "/").lower()
        pat = pattern.lower()
        return fnmatch.fnmatch(p, pat) or fnmatch.fnmatch(os.path.basename(p), pat)

    def any_path(patterns: list[str]) -> bool:
        return any(path_match(f.get("path", ""), p) for f in files for p in patterns)

    def any_added(regex: str, flags: int = re.I) -> bool:
        rx = re.compile(regex, flags)
        return any(rx.search(line) for _, line in added_all)

    def any_file(regex: str, flags: int = re.I) -> bool:
        rx = re.compile(regex, flags)
        return any(rx.search(f.get("path", "")) for f in files)

    signals: dict[str, list[str]] = {}
    specialists: list[str] = []

    perf_signals: list[str] = []
    if any_added(r"\b(loop|hot[- ]?path|query|index|perf)\b"):
        perf_signals.append("keyword:performance")
    if any_path(["**/*.sql"]):
        perf_signals.append("glob:**/*.sql")
    if perf_signals:
        specialists.append("performance")
        signals["performance"] = perf_signals

    api_signals: list[str] = []
    api_patterns = [
        r"openapi",
        r"swagger",
        r"\.proto$",
        r"graphql",
        r"/routes?/",
        r"handler",
        r"/api/",
        r"\.openapi\.",
    ]
    for pattern in api_patterns:
        if any_file(pattern) or any_added(pattern):
            api_signals.append(f"match:{pattern}")
    if api_signals:
        specialists.append("api-contract")
        signals["api-contract"] = api_signals

    dm_signals: list[str] = []
    dm_globs = ["**/migrations/**", "**/migrate/**", "**/schema.sql", "*backfill*"]
    for glob in dm_globs:
        if any_path([glob]):
            dm_signals.append(f"glob:{glob}")
    if dm_signals:
        specialists.append("data-migration")
        signals["data-migration"] = dm_signals

    rel_signals: list[str] = []
    if any_added(r"\b(retry|timeout|concurrency|error.handling|catch|rescue|panic)\b"):
        rel_signals.append("keyword:reliability")
    if any_added(r"\b(silent|swallow|ignored.rejection|empty.catch|log.and.continue)\b"):
        rel_signals.append("keyword:silent-failure")
    if rel_signals:
        specialists.append("reliability")
        signals["reliability"] = rel_signals

    adv_signals: list[str] = []
    exe = sum(1 for _, line in added_all if _is_executable_line(line))
    if exe >= ADVERSARIAL_THRESHOLD:
        adv_signals.append(f"executable_lines:{exe}>={ADVERSARIAL_THRESHOLD}")
    if any_added(r"\b(auth|payment|stripe|mutation|external.api|webhook)\b"):
        adv_signals.append("keyword:high-stakes")
    if adv_signals:
        specialists.append("adversarial")
        signals["adversarial"] = adv_signals

    ui_signals: list[str] = []
    ui_globs = [
        "*.tsx",
        "*.jsx",
        "*.vue",
        "*.svelte",
        "*.css",
        "*.scss",
        "*.less",
        "*.styles.ts",
        "*.css.ts",
        "*.swift",
        "*.kt",
        "*.dart",
        "*.storyboard",
        "*.xib",
        "**/components/**",
        "**/ui/**",
        "**/styles/**",
        "**/theme/**",
        "**/res/layout/*.xml",
    ]
    for glob in ui_globs:
        if any_path([glob]):
            ui_signals.append(f"glob:{glob}")
    if any_added(r"\b(styled|makeStyles|createGlobalStyle)\b") or any_added(r"css`"):
        ui_signals.append("marker:css-in-js")
    if ui_signals:
        specialists.append("ui-ux")
        signals["ui-ux"] = ui_signals

    td_signals: list[str] = []
    if any_path(["*.d.ts"]):
        td_signals.append("glob:*.d.ts")
    if any_added(r"\b(interface|type|class|struct|enum)\b"):
        td_signals.append("marker:type-decl")
    if td_signals:
        specialists.append("type-design")
        signals["type-design"] = td_signals

    ca_signals: list[str] = []
    if any_path(["*.md", "*.mdx"]):
        ca_signals.append("glob:docs")
    if any_added(r"^\s*(//|#|/\*|\*|\"\"\"|''')"):
        ca_signals.append("marker:comment-change")
    if ca_signals:
        specialists.append("comment-accuracy")
        signals["comment-accuracy"] = ca_signals

    ai_signals: list[str] = []
    ai_globs = [
        "commands/**",
        "core/commands/**",
        "skills/**",
        "core/skills/**",
        "rules/**",
        "providers/**",
    ]
    for glob in ai_globs:
        if any_path([glob]):
            ai_signals.append(f"glob:{glob}")
    if any_path(["*.md"]) and any_added(r"\b(prompt|agent|subagent|skill)\b"):
        ai_signals.append("glob:prompt-md")
    if any_added(r"\b(openai|anthropic|llm|chat\.completions|untrusted)\b"):
        ai_signals.append("marker:untrusted-llm")
    if ai_signals:
        specialists.append("ai-native")
        signals["ai-native"] = ai_signals

    return {
        "core": CODE_REVIEW_CORE,
        "specialists": specialists,
        "signals": signals,
        "executable_line_count": exe,
        "adversarial_threshold": ADVERSARIAL_THRESHOLD,
        "excluded": ["previous-comments"],
    }


def resolve_config_value(config: dict[str, Any], dotted_key: str) -> Any:
    current: Any = config
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def is_configured(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    return normalized not in UNCONFIGURED_VALUES


def legacy_providers_select(ctx: dict[str, Any], *, repo_root: Path | None = None) -> dict[str, Any]:
    normalized = normalize_signal_context(ctx)
    config = normalized.get("config") or {}
    families: dict[str, Any] = {}

    review = config.get("review") or {}
    local = review.get("local") or {}
    local_enabled = local.get("enabled", True)
    local_provider = str(local.get("provider", "native")).strip().lower()
    local_fire = bool(local_enabled) and local_provider != "none"
    families["review.local"] = {
        "key": "review.local.provider",
        "value": local_provider,
        "configured": local_fire,
        "fire": local_fire,
        "skip_reason": None if local_fire else (
            "review.local.enabled is false" if not local_enabled else 'review.local.provider is "none"'
        ),
    }

    review_provider = str(review.get("provider", "none")).strip().lower()
    review_set = "provider" in review
    families["review"] = {
        "key": "review.provider",
        "value": review_provider,
        "configured": is_configured(review_provider),
        "explicitlySet": review_set,
    }

    memory_provider = str((config.get("memory") or {}).get("provider", "none")).strip().lower()
    families["memory"] = {
        "key": "memory.provider",
        "value": memory_provider,
        "configured": is_configured(memory_provider),
    }

    verify_provider = str((config.get("verify") or {}).get("provider", "none")).strip().lower()
    families["verify"] = {
        "key": "verify.provider",
        "value": verify_provider,
        "configured": is_configured(verify_provider),
    }

    if repo_root is not None and review_provider == "coderabbit":
        config_candidates = [
            ".coderabbit.yaml",
            ".github/coderabbit.yaml",
            "coderabbit.yaml",
            ".coderabbit.yml",
        ]
        has_config = any((repo_root / name).is_file() for name in config_candidates)
        families["review"]["coderabbitConfigPresent"] = has_config
        families["review"]["preflightOk"] = has_config or review_provider in UNCONFIGURED_VALUES

    return {"family": "providers", "families": families}


def legacy_dispatch_select(ctx: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_signal_context(ctx)
    file_paths = list(normalized.get("file_paths") or [])
    file_count = len(file_paths)
    conductor_mode = normalized.get("conductor_mode")
    mode = str(conductor_mode).strip().lower() if conductor_mode else None

    if mode == "background_phase":
        return {
            "family": "dispatch",
            "posture": "inline",
            "intraphaseSubagentDispatch": "disabled",
            "fileCount": file_count,
            "conductorMode": mode,
            "reason": "background_phase disables intra-phase Task dispatch (R45)",
        }

    inline_execute = file_count <= 3
    return {
        "family": "dispatch",
        "posture": "delegate" if not inline_execute else "inline",
        "intraphaseSubagentDispatch": "enabled",
        "fileCount": file_count,
        "conductorMode": mode,
        "reason": (
            "delegate-by-default"
            if not inline_execute
            else "inline allowed for <=3 declared file paths during execute discipline"
        ),
    }
