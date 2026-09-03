"""Hermetic benchmark harness for memory-eval (PRD 082 R33)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPTS = SCRIPT_DIR.parents[1]
IN_REPO_SEARCH = SCRIPTS / "in-repo-memory-search.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from fixtures import RESERVED_PREFIX, all_corpora, exclude_reserved_ids, is_reserved_id
from metrics import SCENARIOS, build_fixture_index, emit_all_scenarios, emit_scenario_metrics, metrics_json

# Local/null adapters permitted in hermetic runs.
ALLOWED_HERMETIC_PROVIDERS = frozenset({"in-repo", "null", "memory-stub"})

# Known provider credential env vars — any non-empty value aborts hermetic startup.
PROVIDER_TOKEN_ENV_KEYS = frozenset(
    {
        "RECALLIUM_API_KEY",
        "BASIC_MEMORY_API_KEY",
        "OBSIDIAN_API_KEY",
        "MEMPALACE_API_KEY",
    }
)

NETWORK_BACKED_AGENT_SESSIONS = frozenset({"mcp", "rest"})


class HermeticAbort(RuntimeError):
    """Raised when hermetic startup checks fail."""


@dataclass
class HermeticHarness:
    project_root: Path
    provider: str = "in-repo"
    project_id: str = "eval-project"

    def __post_init__(self) -> None:
        self.project_root = self.project_root.resolve()

    def memory_store_path(self) -> Path:
        return self.project_root / ".cursor" / "sw-memory"

    def seed_reserved_corpora(self) -> None:
        """Seed RESERVED_PREFIX fixture corpora into the hermetic in-repo store (R1)."""
        store = self.memory_store_path()
        (store / "memories").mkdir(parents=True, exist_ok=True)
        (store / "rules").mkdir(parents=True, exist_ok=True)
        for fixtures in all_corpora(project_id=self.project_id).values():
            for item in fixtures:
                tags = [
                    f"eval-corpus:{item.corpus}",
                    f"eval-decision-hint:{item.decision_hint}",
                    f"eval-project:{item.project_id}",
                ]
                if item.stale:
                    tags.append("eval-stale:true")
                if item.contradictory:
                    tags.append("eval-contradictory:true")
                subprocess.run(
                    [
                        sys.executable,
                        str(IN_REPO_SEARCH),
                        "store",
                        "--store",
                        str(store),
                        "--id",
                        item.memory_id,
                        "--category",
                        "learning",
                        "--content",
                        item.content,
                        "--tags",
                        ",".join(tags),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )

    def pin_provider(self) -> None:
        cursor = self.project_root / ".cursor"
        cursor.mkdir(parents=True, exist_ok=True)
        config = {
            "memory": {
                "provider": self.provider,
                "project": self.project_id,
                "sourceOfTruth": "auto",
            }
        }
        (cursor / "workflow.config.json").write_text(
            json.dumps(config, indent=2),
            encoding="utf-8",
        )
        (cursor / "sw-memory.provider").write_text(f"{self.provider}\n", encoding="utf-8")
        memory_dir = cursor / "sw-memory" / "memories"
        memory_dir.mkdir(parents=True, exist_ok=True)
        self.seed_reserved_corpora()

    def cleanup(self) -> None:
        if self.project_root.is_dir():
            shutil.rmtree(self.project_root, ignore_errors=True)


def _configured_token_env_keys(root: Path) -> set[str]:
    keys = set(PROVIDER_TOKEN_ENV_KEYS)
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):  # shipwright-paths-exclusion: memory-eval harness seeds legacy config fixture tree
        path = root / rel
        if not path.is_file():
            continue
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        memory = cfg.get("memory")
        if isinstance(memory, dict):
            token_env = memory.get("tokenEnv")
            if isinstance(token_env, str) and token_env.strip():
                keys.add(token_env.strip())
    return keys


def find_provider_tokens_in_env(
    env: dict[str, str] | None = None,
    *,
    root: Path | None = None,
) -> list[str]:
    """Return env var names that carry a non-empty provider token."""
    source = env if env is not None else os.environ
    keys = set(PROVIDER_TOKEN_ENV_KEYS)
    if root is not None:
        keys.update(_configured_token_env_keys(root))
    present = []
    for key in sorted(keys):
        if source.get(key, "").strip():
            present.append(key)
    return present


def find_reachable_network_providers(root: Path, config: dict[str, Any] | None = None) -> list[str]:
    """Return configured network-backed providers that probe reachable."""
    from memory_provider_catalog import CatalogError, get_provider, load_catalog
    from wave_memory_prework import load_workflow_config, probe_provider_reachable

    if config is None:
        config = load_workflow_config(root)
    memory = config.get("memory") if isinstance(config, dict) else {}
    configured = ""
    if isinstance(memory, dict):
        configured = str(memory.get("provider") or "").strip()
    try:
        catalog = load_catalog(root)
    except CatalogError:
        return []

    reachable: list[str] = []
    provider_ids = [configured] if configured else list(catalog.get("providers", {}).keys())
    for provider_id in provider_ids:
        if not provider_id:
            continue
        try:
            entry = get_provider(catalog, provider_id)
        except CatalogError:
            continue
        transport = entry.get("hookTransport")
        if not isinstance(transport, dict):
            continue
        agent_session = str(transport.get("agentSession") or "").strip().lower()
        if agent_session not in NETWORK_BACKED_AGENT_SESSIONS:
            continue
        if probe_provider_reachable(root, provider_id, config):
            reachable.append(provider_id)
    return reachable


def assert_hermetic_startup(
    root: Path,
    *,
    env: dict[str, str] | None = None,
    provider: str = "in-repo",
) -> None:
    """Abort when ambient tokens or reachable network providers are present."""
    if provider not in ALLOWED_HERMETIC_PROVIDERS:
        raise HermeticAbort(
            f"provider {provider!r} is not a local/null adapter; "
            f"allowed: {sorted(ALLOWED_HERMETIC_PROVIDERS)}"
        )

    tokens = find_provider_tokens_in_env(env, root=root)
    if tokens:
        raise HermeticAbort(
            "provider token present in environment: " + ", ".join(tokens)
        )

    reachable = find_reachable_network_providers(root)
    blocked = [pid for pid in reachable if pid not in ALLOWED_HERMETIC_PROVIDERS]
    if blocked:
        raise HermeticAbort(
            "network-backed provider reachable: " + ", ".join(sorted(blocked))
        )


@contextmanager
def temporary_project(
    tmp_root: Path,
    *,
    provider: str = "in-repo",
    project_id: str = "eval-project",
    env: dict[str, str] | None = None,
) -> Iterator[HermeticHarness]:
    project_root = tmp_root / "memory-eval-project"
    harness = HermeticHarness(project_root, provider=provider, project_id=project_id)
    try:
        project_root.mkdir(parents=True, exist_ok=True)
        assert_hermetic_startup(project_root, env=env, provider=provider)
        harness.pin_provider()
        yield harness
    finally:
        harness.cleanup()


def filter_real_read_results(memory_ids: list[str]) -> list[str]:
    """Exclude reserved-prefix fixture ids from real memory reads."""
    return exclude_reserved_ids(memory_ids)


def run_smoke_benchmark(
    harness: HermeticHarness,
    *,
    scenario: str = "memory_enabled",
) -> dict[str, Any]:
    corpora = all_corpora(project_id=harness.project_id)
    scenario_fixtures: dict[str, list[MemoryFixture]] = {
        "memory_enabled": corpora.get("relevant", []),
        "memory_disabled": [],
        "stale": corpora.get("stale", []) + corpora.get("relevant", [])[:1],
        "contradictory": corpora.get("contradictory", []),
        "cross_project": corpora.get("foreign_project", []),
    }
    fixtures = scenario_fixtures.get(scenario, corpora.get("relevant", []))
    return emit_scenario_metrics(
        scenario,
        fixtures,
        memory_enabled=scenario != "memory_disabled",
        project_id=harness.project_id,
        store_path=harness.memory_store_path(),
        fixture_index=build_fixture_index(corpora),
    )


def run_full_benchmark(harness: HermeticHarness) -> dict[str, Any]:
    corpora = all_corpora(project_id=harness.project_id)
    return emit_all_scenarios(
        corpora,
        project_id=harness.project_id,
        store_path=harness.memory_store_path(),
    )


def main(argv: list[str] | None = None) -> int:
    import argparse
    import tempfile

    parser = argparse.ArgumentParser(description="Hermetic memory-eval harness (PRD 082 R33)")
    parser.add_argument("--scenario", default="all", choices=["all", *SCENARIOS])
    parser.add_argument("--project-id", default="eval-project")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="sw-memory-eval-") as tmp:
        tmp_path = Path(tmp)
        with temporary_project(tmp_path, project_id=args.project_id) as harness:
            if args.scenario == "all":
                payload = run_full_benchmark(harness)
            else:
                payload = run_smoke_benchmark(harness, scenario=args.scenario)
            print(metrics_json(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
