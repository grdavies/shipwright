"""PRD 071 R1/R12 — catalog-driven consumer conformance (SoT + prework reachability)."""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import memory_sot as ms
import wave_memory_prework as prework
from memory_provider_catalog import load_catalog

THIRD_PROVIDER_ID = "fixture-third"
CAPABILITY_FLAGS = {
    "typedMemories": True,
    "filePathSearch": True,
    "categoryFilter": True,
    "recencyControl": True,
    "rulesAtStartup": True,
    "tasks": False,
    "export": False,
    "import": False,
    "softDelete": True,
    "semanticSearch": False,
}


def _adapter_doc(provider_id: str) -> str:
    return f"""---
metadata:
  shipwright-capability:
    version: 1
    triggers:
      -
        type: config_flag
        selectionFamily: providers
        key: memory.provider
        equals: {provider_id}
    metadata:
      providerFamily: memory
      adapterId: {provider_id}
      selectionFamily: providers
      gateRef: check-gate.py
---

# Provider adapter: {provider_id}

Test fixture third provider for consumer conformance (PRD 071 phase 6).
"""


def _rules_script() -> str:
    return "import json\nprint(json.dumps({'ok': True, 'rules': []}))\n"


def _install_third_provider(
    workspace: Path,
    repo_root: Path,
    *,
    source_class: str,
    agent_session: str,
) -> None:
    catalog = json.loads(json.dumps(load_catalog(repo_root)))
    catalog["providers"][THIRD_PROVIDER_ID] = {
        "adapterDoc": f"core/providers/{THIRD_PROVIDER_ID}.md",
        "rulesScript": f"providers/{THIRD_PROVIDER_ID}-rules.py",
        "capabilities": dict(CAPABILITY_FLAGS),
        "hookTransport": {
            "agentSession": agent_session,
            "ruleFetch": "out-of-band-script",
            "notes": "Hermetic third-provider fixture for consumer conformance tests.",
        },
        "interchange": {"jsonl": "unsupported", "okf": "unsupported"},
        "sourceOfTruthClass": source_class,
    }

    catalog_path = workspace / ".sw" / "memory-provider-catalog.json"
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    for rel in (
        "scripts/memory_provider_catalog.py",
        "scripts/memory_provider_register.py",
        "scripts/capability_index.py",
        "scripts/sw_resolve_plugin_root.py",
    ):
        src = repo_root / rel
        dest = workspace / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    adapter = workspace / "core" / "providers" / f"{THIRD_PROVIDER_ID}.md"
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(_adapter_doc(THIRD_PROVIDER_ID), encoding="utf-8")

    rules = workspace / "providers" / f"{THIRD_PROVIDER_ID}-rules.py"
    rules.parent.mkdir(parents=True, exist_ok=True)
    rules.write_text(_rules_script(), encoding="utf-8")

    cursor = workspace / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    (cursor / "workflow.config.json").write_text(
        json.dumps(
            {
                "memory": {
                    "provider": THIRD_PROVIDER_ID,
                    "project": "consumer-test",
                    "sourceOfTruth": "auto",
                }
            }
        ),
        encoding="utf-8",
    )


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_args: object) -> None:
        return


@pytest.fixture
def rest_probe_server() -> str:
    server = HTTPServer(("127.0.0.1", 0), _HealthHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_third_provider_auto_sot_reads_catalog_memory_authoritative(
    repo_root: Path, tmp_path: Path
) -> None:
    """O — auto SoT follows catalog sourceOfTruthClass for a registered third provider."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _install_third_provider(
        workspace,
        repo_root,
        source_class="memory-authoritative",
        agent_session="mcp",
    )

    provider = ms.resolve_memory_provider(workspace)
    assert provider == THIRD_PROVIDER_ID
    assert (
        ms.resolve_effective_sot("auto", provider, "decision", root=workspace) == "memory"
    )


def test_third_provider_rest_reachability_uses_transport_metadata(
    repo_root: Path, tmp_path: Path, rest_probe_server: str
) -> None:
    """O — REST transport probes connection metadata instead of recallium-only assumptions."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _install_third_provider(
        workspace,
        repo_root,
        source_class="memory-authoritative",
        agent_session="rest",
    )

    config = json.loads((workspace / ".cursor/workflow.config.json").read_text(encoding="utf-8"))
    config["memory"]["connection"] = {"restBaseUrl": rest_probe_server}
    (workspace / ".cursor/workflow.config.json").write_text(json.dumps(config), encoding="utf-8")

    assert prework.probe_provider_reachable(workspace, THIRD_PROVIDER_ID, config) is True


def test_third_provider_rest_missing_base_url_is_unreachable(
    repo_root: Path, tmp_path: Path
) -> None:
    """M — REST transport without restBaseUrl degrades to unreachable."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _install_third_provider(
        workspace,
        repo_root,
        source_class="repo-authoritative",
        agent_session="rest",
    )
    config = json.loads((workspace / ".cursor/workflow.config.json").read_text(encoding="utf-8"))

    assert prework.probe_provider_reachable(workspace, THIRD_PROVIDER_ID, config) is False
    assert ms.resolve_effective_sot("auto", THIRD_PROVIDER_ID, "decision", root=workspace) == "repo"


def test_unknown_provider_fails_consumer_resolution(repo_root: Path, tmp_path: Path) -> None:
    """I — unknown provider ids are rejected by catalog-backed consumers."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    catalog_path = workspace / ".sw" / "memory-provider-catalog.json"
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(
        json.dumps(load_catalog(repo_root)),
        encoding="utf-8",
    )
    cursor = workspace / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    (cursor / "workflow.config.json").write_text(
        json.dumps({"memory": {"provider": "not-registered"}}),
        encoding="utf-8",
    )

    assert ms.resolve_memory_provider(workspace) is None
    assert prework.probe_provider_reachable(workspace, "not-registered", {}) is False
