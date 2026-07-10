#!/usr/bin/env python3
"""Shared Task-dispatch prompt construction boundary (PRD 058 gap-083 R19, R24, R25)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from _sw.cli import build_parser, run_module_main
from check_gate_lib import load_workflow_config
from context_compress import compress, detect_content_type, estimate_tokens, retrieve
from dispatch_intensity_check import format_intensity_directive, validate_retrieve_key_guard

DEFAULT_THRESHOLD_TOKENS = 8000
DEFAULT_CONTEXT_COMPRESSION_ENABLED = False
CONTENT_STRATEGIES = ("json", "diff", "log", "prose")
DEFAULT_STRATEGIES = {name: "compress" for name in CONTENT_STRATEGIES}
SURFACE_SHIP_PHASE = "ship-phase"
INTENSITY_SOURCE_DELIVER_PHASE_SHIP = "deliver.phase-ship"
SURFACE_DOC_REVIEW = "doc-review"
TELEMETRY_SURFACES = frozenset({SURFACE_SHIP_PHASE, SURFACE_DOC_REVIEW})


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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

    enabled = block.get("enabled", DEFAULT_CONTEXT_COMPRESSION_ENABLED)
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

    if not config.get("enabled", DEFAULT_CONTEXT_COMPRESSION_ENABLED):
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


def build_deliver_phase_ship_prompt(
    *,
    intensity: str,
    body: str,
    intensity_source: str = INTENSITY_SOURCE_DELIVER_PHASE_SHIP,
    context_blocks: list[ContextBlock] | None = None,
    config_path: str | None = None,
    root: Path | None = None,
) -> DispatchPromptResult:
    """Assemble deliver phase-ship Task prompt with required intensity directive (gap-115, R3)."""
    return build_task_dispatch_prompt(
        intensity=intensity,
        intensity_source=intensity_source,
        body=body,
        context_blocks=context_blocks,
        config_path=config_path,
        root=root,
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




def build_dispatch_telemetry_entry(
    result: DispatchPromptResult,
    *,
    surface: str,
    dispatch_id: str | None = None,
    phase_slug: str | None = None,
    compression_enabled: bool | None = None,
) -> dict[str, Any]:
    """Build a token-estimate telemetry record (PRD 058 R28)."""
    if surface not in TELEMETRY_SURFACES:
        raise ValueError(f"unsupported telemetry surface: {surface!r}")
    entry: dict[str, Any] = {
        "event": "dispatch-token-estimate",
        "surface": surface,
        "tokensBefore": result.tokens_before,
        "tokensAfter": result.tokens_after,
        "compressionApplied": result.compression_applied,
    }
    if dispatch_id:
        entry["dispatchId"] = dispatch_id
    if phase_slug:
        entry["phaseSlug"] = phase_slug
    if compression_enabled is not None:
        entry["contextCompressionEnabled"] = compression_enabled
    return entry


def _append_jsonl_log(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({**entry, "at": utc_now()}, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
    os.chmod(path, 0o600)


def _patch_status_dispatch_telemetry(status_path: Path, entry: dict[str, Any]) -> None:
    if not status_path.is_file():
        return
    doc = json.loads(status_path.read_text(encoding="utf-8"))
    records = doc.get("dispatchTelemetry")
    if not isinstance(records, list):
        records = []
    records.append({**entry, "at": utc_now()})
    doc["dispatchTelemetry"] = records
    status_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    os.chmod(status_path, 0o600)


def record_dispatch_telemetry(
    result: DispatchPromptResult,
    *,
    root: Path,
    surface: str,
    dispatch_id: str | None = None,
    phase_slug: str | None = None,
    run_dir: Path | None = None,
    compression_enabled: bool | None = None,
) -> Path:
    """Record before/after token estimates per surface convention (R28)."""
    entry = build_dispatch_telemetry_entry(
        result,
        surface=surface,
        dispatch_id=dispatch_id,
        phase_slug=phase_slug,
        compression_enabled=compression_enabled,
    )
    repo = root.resolve()

    if surface == SURFACE_DOC_REVIEW:
        if not dispatch_id:
            raise ValueError("dispatch_id required for doc-review telemetry")
        sink = repo / ".cursor" / "doc-review-runs" / f"{dispatch_id}.json"
        sink.parent.mkdir(parents=True, exist_ok=True)
        sink.write_text(json.dumps({**entry, "at": utc_now()}, indent=2) + "\n", encoding="utf-8")
        os.chmod(sink, 0o600)
        return sink

    deliver_log = repo / ".cursor" / "sw-deliver-runs" / "run.log"
    _append_jsonl_log(deliver_log, entry)
    if run_dir is not None:
        _append_jsonl_log(run_dir / "run.log", entry)
    if phase_slug:
        phase_run = repo / ".cursor" / "sw-deliver-runs" / phase_slug
        _append_jsonl_log(phase_run / "run.log", entry)
        _patch_status_dispatch_telemetry(phase_run / "status.json", entry)
    return deliver_log


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
    build_p.add_argument(
        "--surface",
        choices=sorted(TELEMETRY_SURFACES),
        help="Telemetry sink: ship-phase (run.log/status.json) or doc-review",
    )
    build_p.add_argument("--dispatch-id", help="Dispatch id (required for doc-review surface)")
    build_p.add_argument("--phase-slug", help="Phase slug for ship-phase telemetry")
    build_p.add_argument("--run-dir", help="Optional per-phase run directory for run.log mirror")

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

    config = load_context_compression_config(root, args.config_path)
    result = build_task_dispatch_prompt(
        intensity=args.intensity,
        intensity_source=args.intensity_source,
        body=body,
        context_blocks=blocks,
        config_path=args.config_path,
        root=root,
    )
    write_dispatch_prompt(result, args.out)
    telemetry_sink: str | None = None
    if args.surface:
        run_dir = Path(args.run_dir).resolve() if args.run_dir else None
        sink = record_dispatch_telemetry(
            result,
            root=root,
            surface=args.surface,
            dispatch_id=args.dispatch_id,
            phase_slug=args.phase_slug,
            run_dir=run_dir,
            compression_enabled=config.get("enabled"),
        )
        telemetry_sink = str(sink)
    if args.json:
        payload: dict[str, Any] = {
            "out": str(args.out),
            "retrieveKeys": result.retrieve_keys,
            "tokensBefore": result.tokens_before,
            "tokensAfter": result.tokens_after,
            "compressionApplied": result.compression_applied,
            "contextCompressionEnabled": config.get("enabled"),
        }
        if telemetry_sink:
            payload["telemetrySink"] = telemetry_sink
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    run_module_main(main)
