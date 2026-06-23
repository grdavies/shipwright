#!/usr/bin/env python3
"""phase-flow stop hook — durable-memory distillation scheduler.

This is the plugin-native replacement for the inherited `continual-learning` stop hook.
Like that hook, it does *no* mining itself: it is a turn/time/transcript gate that, when
thresholds trip, returns a `followup_message` instructing the agent to run `/pf-memory-sync`
(which distills new transcript deltas into the configured memory provider).

Thresholds come from the consumer repo's `.cursor/workflow.config.json`
(`memory.autoSync`), with env overrides, and sensible defaults. Set
`memory.autoSync.enabled = false` (or env `PHASE_FLOW_MEMORY_SYNC_DISABLE=1`) to silence it.

Robust by design: any failure prints an empty `{}` and exits 0, so a broken hook can
never wedge a session or block a turn.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_STATE_RELPATH = Path(".cursor") / "hooks" / "state" / "phase-flow-memory-sync-scheduler.json"

_DEFAULT_MIN_TURNS = 10
_DEFAULT_MIN_MINUTES = 120

_FOLLOWUP = (
    "Run `/pf-memory-sync` now to distill new agent-transcript deltas into durable memories "
    "via the configured memory provider. Read the delta only; store high-signal substance "
    "(decisions, hard-won learnings, bug root-causes, design choices, notable review/CI "
    "patterns) with the right category, tags, and related files; search-before-store to "
    "avoid duplicates; never store raw transcripts or secrets. If nothing durable surfaced, "
    "respond exactly: No high-signal memory updates."
)


def _now_ms() -> int:
    import time

    return int(time.time() * 1000)


def _read_stdin_json() -> dict:
    try:
        text = sys.stdin.read()
        return json.loads(text) if text.strip() else {}
    except (OSError, ValueError):
        return {}


def _workspace_root(payload: dict) -> Path:
    """Resolve the repo root from the payload's workspace_roots, falling back to cwd.

    Cursor does not guarantee the hook's cwd is the workspace root, so prefer the explicit
    workspace_roots the stop payload provides. This keeps config + scheduler state anchored to
    the repo regardless of where Cursor launches the hook from.
    """
    roots = payload.get("workspace_roots")
    if isinstance(roots, list):
        for root in roots:
            if isinstance(root, str) and root.strip():
                candidate = Path(root)
                if candidate.is_dir():
                    return candidate
    return Path.cwd()


def _load_config(root: Path) -> dict:
    for path in (root / ".cursor" / "workflow.config.json", root / "workflow.config.json"):
        try:
            if path.is_file():
                return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return {}


def _auto_sync_settings(config: dict) -> tuple[bool, int, int]:
    memory = config.get("memory", {}) if isinstance(config, dict) else {}
    auto = memory.get("autoSync", {}) if isinstance(memory, dict) else {}

    enabled = bool(auto.get("enabled", True))
    if os.environ.get("PHASE_FLOW_MEMORY_SYNC_DISABLE", "").strip().lower() in {"1", "true", "yes", "on"}:
        enabled = False

    def _pos_int(value, fallback: int) -> int:
        try:
            parsed = int(value)
            return parsed if parsed > 0 else fallback
        except (TypeError, ValueError):
            return fallback

    min_turns = _pos_int(os.environ.get("PHASE_FLOW_MEMORY_SYNC_MIN_TURNS", auto.get("minTurns")), _DEFAULT_MIN_TURNS)
    min_minutes = _pos_int(
        os.environ.get("PHASE_FLOW_MEMORY_SYNC_MIN_MINUTES", auto.get("minMinutes")), _DEFAULT_MIN_MINUTES
    )
    return enabled, min_turns, min_minutes


def _load_state(state_path: Path) -> dict:
    fallback = {
        "version": 1,
        "lastRunAtMs": 0,
        "turnsSinceLastRun": 0,
        "lastTranscriptMtimeMs": None,
        "lastCompletedGenerationId": None,
    }
    try:
        if state_path.is_file():
            parsed = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict) and parsed.get("version") == 1:
                merged = {**fallback, **parsed}
                if merged.get("lastCompletedGenerationId") is None and merged.get("lastProcessedGenerationId"):
                    merged["lastCompletedGenerationId"] = merged.pop("lastProcessedGenerationId", None)
                return merged
    except (OSError, ValueError):
        pass
    return fallback


def _save_state(state_path: Path, state: dict) -> None:
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def _transcript_mtime_ms(transcript_path) -> int | None:
    if not transcript_path:
        return None
    try:
        return int(Path(transcript_path).stat().st_mtime_ns / 1_000_000)
    except OSError:
        return None


def main() -> None:
    payload = _read_stdin_json()
    root = _workspace_root(payload)
    config = _load_config(root)
    enabled, min_turns, min_minutes = _auto_sync_settings(config)
    if not enabled:
        print(json.dumps({}))
        return

    state_path = root / _STATE_RELPATH
    state = _load_state(state_path)

    generation_id = payload.get("generation_id")
    counted_turn = payload.get("status") == "completed" and payload.get("loop_count", 0) == 0

    # Dedup only after a completed stop was fully processed for this generation.
    if (
        counted_turn
        and generation_id
        and generation_id == state.get("lastCompletedGenerationId")
    ):
        print(json.dumps({}))
        return

    turns_since = state.get("turnsSinceLastRun", 0) + (1 if counted_turn else 0)
    now = _now_ms()

    last_run = state.get("lastRunAtMs", 0) or 0
    minutes_since = (now - last_run) / 60000 if last_run > 0 else float("inf")

    transcript_mtime = _transcript_mtime_ms(payload.get("transcript_path"))
    last_mtime = state.get("lastTranscriptMtimeMs")
    transcript_advanced = transcript_mtime is not None and (last_mtime is None or transcript_mtime > last_mtime)

    should_trigger = (
        counted_turn
        and turns_since >= min_turns
        and minutes_since >= min_minutes
        and transcript_advanced
    )

    if should_trigger:
        state["lastRunAtMs"] = now
        state["turnsSinceLastRun"] = 0
        state["lastTranscriptMtimeMs"] = transcript_mtime
        if counted_turn and generation_id:
            state["lastCompletedGenerationId"] = generation_id
        _save_state(state_path, state)
        print(json.dumps({"followup_message": _FOLLOWUP}, ensure_ascii=False))
        return

    state["turnsSinceLastRun"] = turns_since
    if counted_turn and generation_id:
        state["lastCompletedGenerationId"] = generation_id
    _save_state(state_path, state)
    print(json.dumps({}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 — hook must never crash the session
        # Emit a schema-valid empty stop result on stdout (the stop schema is only
        # `{ followup_message? }`); route the diagnostic to stderr so it never pollutes
        # the parsed hook output or surfaces as a malformed result.
        print(json.dumps({}))
        print(f"phase-flow memory-sync-stop hook degraded: {exc}", file=sys.stderr)
        sys.exit(0)
