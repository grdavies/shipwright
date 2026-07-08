"""Unit tests for dispatch_prompt.py (PRD 058 phase 9 R19, R24, R25)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dispatch_intensity_check import parse_anchored_directive, validate_retrieve_key_guard
from dispatch_prompt import (
    ContextBlock,
    SURFACE_DOC_REVIEW,
    SURFACE_SHIP_PHASE,
    build_task_dispatch_prompt,
    load_context_compression_config,
    process_context_block,
    record_dispatch_telemetry,
    recover_compressed_context,
)


class DispatchPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.config_path = self.root / "workflow.config.json"
        self.config_path.write_text(
            json.dumps(
                {
                    "contextCompression": {
                        "enabled": False,
                        "thresholdTokens": 50,
                        "strategies": {
                            "json": "compress",
                            "diff": "path-reference",
                            "log": "compress",
                            "prose": "compress",
                        },
                    }
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_build_includes_anchored_directive(self) -> None:
        result = build_task_dispatch_prompt(
            intensity="full",
            intensity_source="routing.commands",
            body="Do the work.",
            config_path=str(self.config_path),
            root=self.root,
        )
        parsed = parse_anchored_directive(result.prompt)
        self.assertEqual(parsed, ("full", "routing.commands"))
        self.assertIn("Do the work.", result.prompt)
        guard = validate_retrieve_key_guard(result.prompt)
        self.assertEqual(guard.verdict, "pass")

    def test_path_reference_for_file_backed_block(self) -> None:
        doc = self.root / "fixture.md"
        doc.write_text("Short file-backed context.", encoding="utf-8")
        cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        cfg["contextCompression"]["enabled"] = True
        self.config_path.write_text(json.dumps(cfg), encoding="utf-8")

        processed = process_context_block(
            ContextBlock(path="fixture.md", label="fixture"),
            config=load_context_compression_config(self.root, str(self.config_path)),
            root=self.root,
        )
        self.assertTrue(processed.used_path_reference)
        self.assertIn("fixture.md", processed.text)
        self.assertNotIn("Short file-backed", processed.text)

    def test_ephemeral_block_compresses_when_enabled(self) -> None:
        cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        cfg["contextCompression"]["enabled"] = True
        cfg["contextCompression"]["thresholdTokens"] = 10
        self.config_path.write_text(json.dumps(cfg), encoding="utf-8")

        large = "word " * 500
        result = build_task_dispatch_prompt(
            intensity="lite",
            intensity_source="defaultIntensity",
            body="task",
            context_blocks=[ContextBlock(text=large, label="payload")],
            config_path=str(self.config_path),
            root=self.root,
        )
        self.assertTrue(result.compression_applied)
        self.assertTrue(result.retrieve_keys)
        guard = validate_retrieve_key_guard(result.prompt)
        self.assertEqual(guard.verdict, "pass")

    def test_recover_round_trip(self) -> None:
        cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        cfg["contextCompression"]["enabled"] = True
        cfg["contextCompression"]["thresholdTokens"] = 10
        self.config_path.write_text(json.dumps(cfg), encoding="utf-8")

        large = "payload " * 400
        result = build_task_dispatch_prompt(
            intensity="normal",
            intensity_source="routing.skills",
            body="task",
            context_blocks=[ContextBlock(text=large)],
            config_path=str(self.config_path),
            root=self.root,
        )
        self.assertTrue(result.retrieve_keys)
        restored = recover_compressed_context(result.retrieve_keys[0], root=self.root)
        self.assertIn("payload", restored)


    def test_context_compression_default_off_without_block(self) -> None:
        empty_cfg = self.root / "empty.config.json"
        empty_cfg.write_text("{}", encoding="utf-8")
        config = load_context_compression_config(self.root, str(empty_cfg))
        self.assertFalse(config["enabled"])

    def test_telemetry_ship_phase_run_log(self) -> None:
        result = build_task_dispatch_prompt(
            intensity="lite",
            intensity_source="defaultIntensity",
            body="task body",
            config_path=str(self.config_path),
            root=self.root,
        )
        slug = "telemetry-fixture-phase"
        phase_run = self.root / ".cursor" / "sw-deliver-runs" / slug
        phase_run.mkdir(parents=True, exist_ok=True)
        (phase_run / "status.json").write_text('{"verdict":"in-flight","phase":"' + slug + '"}', encoding="utf-8")
        record_dispatch_telemetry(
            result,
            root=self.root,
            surface=SURFACE_SHIP_PHASE,
            phase_slug=slug,
            compression_enabled=False,
        )
        log = (self.root / ".cursor" / "sw-deliver-runs" / "run.log").read_text(encoding="utf-8")
        self.assertIn("dispatch-token-estimate", log)
        status = json.loads((phase_run / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(len(status["dispatchTelemetry"]), 1)

    def test_telemetry_doc_review_sink(self) -> None:
        result = build_task_dispatch_prompt(
            intensity="normal",
            intensity_source="routing.commands",
            body="review task",
            config_path=str(self.config_path),
            root=self.root,
        )
        dispatch_id = "panel-abc123"
        sink = record_dispatch_telemetry(
            result,
            root=self.root,
            surface=SURFACE_DOC_REVIEW,
            dispatch_id=dispatch_id,
            compression_enabled=False,
        )
        self.assertTrue(sink.is_file())
        payload = json.loads(sink.read_text(encoding="utf-8"))
        self.assertEqual(payload["dispatchId"], dispatch_id)
        self.assertEqual(payload["surface"], SURFACE_DOC_REVIEW)

if __name__ == "__main__":
    unittest.main()
