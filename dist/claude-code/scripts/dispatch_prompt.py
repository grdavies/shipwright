#!/usr/bin/env python3
"""Shared Task-dispatch prompt construction boundary (PRD 058 gap-083 R19, R24, R25)."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from _sw.cli import build_parser, run_module_main
from check_gate_lib import load_workflow_config
from context_compress import compress, detect_content_type, estimate_tokens, retrieve
from dispatch_intensity_check import format_intensity_directive, validate_retrieve_key_guard

DEFAULT_THRESHOLD_TOKENS = 8000
CONTENT_STRATEGIES = ("json", "diff", "log", "prose")
DEFAULT_STRATEGIES = {name: "compress" for name in CONTENT_STRATEGIES}


@dataclass(frozen=True)
class ContextBlock:
    """Inbound context block for dispatch prompt assembly."""

    text: str | None = None
    path: str | None = None
    content_type: str | None = None
    label: str | None = None
    allow_path_reference: bool = True


@dataclass
class ProcessedBlock:
    text: str
    compressed: bool = False
    retrieve_keys: list[str] = field(default_factory=list)
    used_path_reference: bool = False


@dataclass
class DispatchPromptResult:
    prompt: str
    retrieve_keys: list[str] = field(default_factory=list)
    tokens_before: int = 0
    tokens_after: int = 0
    compression_applied: bool = False


def load_context_compression_config(
    root: Path | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Read contextCompression settings from workflow.config.json."""
    if config_path:
        cfg_file = Path(config_path)
        cfg = json.loads(cfg_file.read_text(encoding="utf-8")) if cfg_file.is_file() else {}
    else:
        repo = (root or Path.cwd()).resolve()
        cfg = load_workflow_config(repo)

    block = cfg.get("contextCompression", {})
    if not isinstance(block, dict):
        block = {}

    enabled = block.get("enabled", False)
    if isinstance(enabled, str):
        enabled = enabled.lower() in ("true", "1", "yes")

    threshold = block.get("thresholdTokens", DEFAULT_THRESHOLD_TOKENS)
    strategies = block.get("strategies", {})
    if not isinstance(strategies, dict):
        strategies = {}

    merged_strategies = {**DEFAULT_STRATEGIES, **strategies}

    return {
        "enabled": bool(enabled),
        "thresholdTokens": int(threshold) if threshold is not None else DEFAULT_THRESHOLD_TOKENS,
        "strategies": merged_strategies,
    }


def _resolve_block_text(block: ContextBlock, root: Path) -> tuple[str, bool, str | None]:
    """Return (text, is_file_backed, display_path)."""
    if block.path:
        path = Path(block.path)
        display_path = block.path
        if not path.is_absolute():
            path = root / path
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace"), True, display_path
        return f"[missing file: {block.path}]", False, display_path
    return block.text or "", False, None


def _strategy_for_content_type(strategies: dict[str, str], content_type: str) -> str:
    strategy = strategies.get(content_type, strategies.get("prose", "compress"))
    return str(strategy)


def _format_path_reference(label: str | None, path: str) -> str:
    header = f"## Context: {label}\n" if label else ""
    return f"{header}Read the full content at: `{path}`\n"


def _format_block_header(label: str | None, *, summarized: bool = False) -> str:
    if not label:
        return ""
    suffix = " (summarized)" if summarized else ""
    return f"## Context: {label}{suffix}\n"


def process_context_block(
    block: ContextBlock,
    *,
    config: dict[str, Any],
    root: Path,
) -> ProcessedBlock:
    """Process a single context block per compression/path-ref policy."""
    text, file_backed, display_path = _resolve_block_text(block, root)
    content_type = block.content_type or detect_content_type(text)
    label = block.label or content_type
    threshold = config.get("thresholdTokens", DEFAULT_THRESHOLD_TOKENS)
    token_count = estimate_tokens(text)

    if not config.get("enabled", False):
        return ProcessedBlock(text=f"{_format_block_header(label)}{text}")

    strategies = config.get("strategies", DEFAULT_STRATEGIES)
    strategy = _strategy_for_content_type(strategies, content_type)

    if strategy == "passthrough":
        return ProcessedBlock(text=f"{_format_block_header(label)}{text}")

    needs_summarization = token_count > threshold

    if file_backed and block.allow_path_reference and display_path and not needs_summarization:
        return ProcessedBlock(
            text=_format_path_reference(label, display_path),
            used_path_reference=True,
        )

    if file_backed and block.allow_path_reference and display_path and needs_summarization:
        return ProcessedBlock(
            text=_format_path_reference(label, display_path),
            used_path_reference=True,
        )

    if not needs_summarization:
        return ProcessedBlock(text=f"{_format_block_header(label)}{text}")

    result = compress(
        text,
        content_type=content_type,
        budget_tokens=threshold,
        root=root,
    )
    retrieve_keys: list[str] = []
    body = result.text
    if result.compressed and result.retrieveKey:
        retrieve_keys.append(result.retrieveKey)
        body += (
            "\n\n*(Content summarized — orchestrator may re-dispatch with fuller context "
            "via recoverable retrieve.)*"
        )

    return ProcessedBlock(
        text=f"{_format_block_header(label, summarized=result.compressed)}{body}",
        compressed=result.compressed,
        retrieve_keys=retrieve_keys,
    )


def build_task_dispatch_prompt(
    *,
    intensity: str,
    intensity_source: str,
    body: str,
    context_blocks: list[ContextBlock] | None = None,
    config_path: str | None = None,
    root: Path | None = None,
) -> DispatchPromptResult:
    """Assemble a Task-dispatch prompt with directive, optional compression, and body."""
    repo = (root or Path.cwd()).resolve()
    config = load_context_compression_config(repo, config_path)

    directive = format_intensity_directive(intensity, intensity_source)
    parts = [directive]
    retrieve_keys: list[str] = []
    tokens_before = estimate_tokens(directive) + estimate_tokens(body)
    compression_applied = False

    for block in context_blocks or []:
        processed = process_context_block(block, config=config, root=repo)
        if processed.text:
            parts.append(processed.text)
            tokens_before += estimate_tokens(processed.text)
        retrieve_keys.extend(processed.retrieve_keys)
        if processed.compressed:
            compression_applied = True

    parts.append(body)
    prompt = "\n".join(part for part in parts if part)

    guard = validate_retrieve_key_guard(prompt)
    if guard.verdict == "fail":
        raise ValueError(guard.remediation or guard.cause or "retrieve key leaked into prompt")

    return DispatchPromptResult(
        prompt=prompt,
        retrieve_keys=retrieve_keys,
        tokens_before=tokens_before,
        tokens_after=estimate_tokens(prompt),
        compression_applied=compression_applied,
    )


def recover_compressed_context(retrieve_key: str, *, root: Path | None = None) -> str:
    """Orchestrator-side retrieve for re-dispatch (R24)."""
    return retrieve(retrieve_key, root=root)


def write_dispatch_prompt(result: DispatchPromptResult, output_path: str | Path) -> Path:
    """Write assembled prompt to disk for dispatch-check --prompt validation."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.prompt, encoding="utf-8")
    return path


def _context_block_from_json(data: dict[str, Any]) -> ContextBlock:
    return ContextBlock(
        text=data.get("text"),
        path=data.get("path"),
        content_type=data.get("contentType") or data.get("content_type"),
        label=data.get("label"),
        allow_path_reference=bool(data.get("allowPathReference", data.get("allow_path_reference", True))),
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(prog="dispatch-prompt", description="Build Task-dispatch prompts (PRD 058 R25).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    build_p = sub.add_parser("build", help="Assemble a dispatch prompt file")
    build_p.add_argument("--intensity", required=True)
    build_p.add_argument("--intensity-source", required=True)
    build_p.add_argument("--body-file", help="Path to redacted task body text")
    build_p.add_argument("--body", help="Inline task body text")
    build_p.add_argument("--context-json", help="JSON array of context blocks")
    build_p.add_argument("--config", dest="config_path", help="workflow.config.json override")
    build_p.add_argument("--root", help="Repository root")
    build_p.add_argument("--out", required=True, help="Output prompt path")
    build_p.add_argument("--json", action="store_true", help="Emit build metadata JSON to stdout")

    recover_p = sub.add_parser("recover", help="Orchestrator-side CCR retrieve (R24)")
    recover_p.add_argument("--key", required=True)
    recover_p.add_argument("--root", help="Repository root")

    args = parser.parse_args(argv)
    root = Path(args.root).resolve() if getattr(args, "root", None) else Path.cwd().resolve()

    if args.cmd == "recover":
        print(recover_compressed_context(args.key, root=root))
        return 0

    if args.body_file:
        body = Path(args.body_file).read_text(encoding="utf-8")
    elif args.body is not None:
        body = args.body
    else:
        body = sys.stdin.read()

    blocks: list[ContextBlock] = []
    if args.context_json:
        payload = json.loads(args.context_json)
        if isinstance(payload, list):
            blocks = [_context_block_from_json(item) for item in payload if isinstance(item, dict)]

    result = build_task_dispatch_prompt(
        intensity=args.intensity,
        intensity_source=args.intensity_source,
        body=body,
        context_blocks=blocks,
        config_path=args.config_path,
        root=root,
    )
    write_dispatch_prompt(result, args.out)
    if args.json:
        print(
            json.dumps(
                {
                    "out": str(args.out),
                    "retrieveKeys": result.retrieve_keys,
                    "tokensBefore": result.tokens_before,
                    "tokensAfter": result.tokens_after,
                    "compressionApplied": result.compression_applied,
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    run_module_main(main)
