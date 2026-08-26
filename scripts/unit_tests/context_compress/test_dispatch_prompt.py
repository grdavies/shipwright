"""Unit tests for dispatch_prompt.py (PRD 058 + PRD 332 compression rollout)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from capability_promotion import (
    STATE_ACTIVE,
    STATE_SHADOW,
    build_capability_record,
    build_registry,
    build_revision_record,
    get_capability,
    read_registry,
    write_registry,
    FamilyThresholds,
)
from dispatch_intensity_check import parse_anchored_directive, validate_retrieve_key_guard
from dispatch_prompt import (
    COMPRESSION_CAPABILITY_ID,
    ContextBlock,
    MODE_ACTIVE_LOSSY,
    MODE_LOSSLESS,
    MODE_SHADOW_LOSSY,
    SURFACE_DOC_REVIEW,
    SURFACE_SHIP_PHASE,
    build_task_dispatch_prompt,
    compute_compression_metrics,
    load_context_compression_config,
    process_context_block,
    record_compression_dispatch_evidence,
    record_dispatch_telemetry,
    recover_compressed_context,
    registry_path,
    resolve_compression_mode,
)
from context_compress import compress_with_mode


def _thresholds() -> FamilyThresholds:
    return FamilyThresholds.from_mapping(
        {
            "minQualifyingRuns": 3,
            "maxFalsePositiveRate": 0.05,
            "maxVetoConflictRate": 0.02,
            "minShadowAgreement": 0.85,
        }
    )


def _seed_compression_registry(
    root: Path,
    *,
    state: str,
    revision: int = 1,
    prior_active: dict | None = None,
) -> None:
    revision_record = build_revision_record(
        revision=revision,
        state=state,
        capability_family="context-compression",
        evidence_class="CompressionEvidence@v1",
        evidence_ref="sha256:" + ("a" * 64),
        thresholds=_thresholds(),
        prior_active=prior_active,
    )
    capability = build_capability_record(
        COMPRESSION_CAPABILITY_ID,
        capability_family="context-compression",
        revisions={revision: revision_record},
        active_revision=revision,
    )
    registry = build_registry({COMPRESSION_CAPABILITY_ID: capability})
    write_registry(registry_path(root), registry)


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

    def test_ephemeral_block_compresses_when_active_mode(self) -> None:
        cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        cfg["contextCompression"]["enabled"] = True
        cfg["contextCompression"]["thresholdTokens"] = 10
        cfg["contextCompression"]["phase"] = MODE_ACTIVE_LOSSY
        self.config_path.write_text(json.dumps(cfg), encoding="utf-8")
        _seed_compression_registry(self.root, state=STATE_ACTIVE)

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
        cfg["contextCompression"]["phase"] = MODE_ACTIVE_LOSSY
        self.config_path.write_text(json.dumps(cfg), encoding="utf-8")
        _seed_compression_registry(self.root, state=STATE_ACTIVE)

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
        (phase_run / "status.json").write_text(
            '{"verdict":"in-flight","phase":"' + slug + '"}',
            encoding="utf-8",
        )
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

    def test_end_to_end_compression_enabled_with_retrieve_round_trip(self) -> None:
        cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        cfg["contextCompression"]["enabled"] = True
        cfg["contextCompression"]["thresholdTokens"] = 15
        cfg["contextCompression"]["phase"] = MODE_ACTIVE_LOSSY
        self.config_path.write_text(json.dumps(cfg), encoding="utf-8")
        _seed_compression_registry(self.root, state=STATE_ACTIVE)

        large_diff = (
            "diff --git a/report.json b/report.json\n"
            "--- a/report.json\n+++ b/report.json\n"
            "@@ -1,3 +1,4 @@\n"
            + "\n".join(f"+line {i} added context" for i in range(200))
        )
        result = build_task_dispatch_prompt(
            intensity="full",
            intensity_source="routing.commands",
            body="Analyze the diff.",
            context_blocks=[ContextBlock(text=large_diff, label="report-diff")],
            config_path=str(self.config_path),
            root=self.root,
        )
        self.assertTrue(result.compression_applied)
        self.assertTrue(result.retrieve_keys)
        guard = validate_retrieve_key_guard(result.prompt)
        self.assertEqual(guard.verdict, "pass")
        restored = recover_compressed_context(result.retrieve_keys[0], root=self.root)
        self.assertIn("line 0 added context", restored)


class CompressionMeasuredPromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.config_path = self.root / "workflow.config.json"
        self.base_config = {
            "contextCompression": {
                "enabled": True,
                "thresholdTokens": 10,
                "strategies": {
                    "json": "compress",
                    "diff": "compress",
                    "log": "compress",
                    "prose": "compress",
                },
            }
        }

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_config(self, **overrides: object) -> dict:
        cfg = json.loads(json.dumps(self.base_config))
        cfg["contextCompression"].update(overrides)
        self.config_path.write_text(json.dumps(cfg), encoding="utf-8")
        return cfg["contextCompression"]

    def test_lossless_baseline_without_registry(self) -> None:
        mode, revision, _ = resolve_compression_mode(self.root)
        self.assertEqual(mode, MODE_LOSSLESS)
        self.assertIsNone(revision)

        large = "baseline " * 200
        mode_result = compress_with_mode(large, mode=MODE_LOSSLESS, budget_tokens=10, root=self.root)
        self.assertEqual(mode_result.authoritative.text, large)
        self.assertFalse(mode_result.authoritative.compressed)

    def test_shadow_mode_keeps_authoritative_lossless(self) -> None:
        _seed_compression_registry(self.root, state=STATE_SHADOW)
        mode, _, _ = resolve_compression_mode(self.root)
        self.assertEqual(mode, MODE_SHADOW_LOSSY)

        self._write_config()
        large = "shadow " * 300
        processed = process_context_block(
            ContextBlock(text=large, label="payload"),
            config=load_context_compression_config(self.root, str(self.config_path)),
            root=self.root,
            compression_mode=mode,
            capability_revision=1,
        )
        self.assertFalse(processed.compressed)
        self.assertIn("shadow", processed.text)
        self.assertIsNotNone(processed.compression_evidence)
        self.assertTrue(processed.compression_evidence["shadowNonAuthoritative"])

    def test_active_mode_requires_registry_promotion(self) -> None:
        _seed_compression_registry(self.root, state=STATE_ACTIVE)
        mode, revision, _ = resolve_compression_mode(self.root)
        self.assertEqual(mode, MODE_ACTIVE_LOSSY)
        self.assertEqual(revision, 1)

        self._write_config(phase=MODE_ACTIVE_LOSSY)
        large = "active " * 300
        result = build_task_dispatch_prompt(
            intensity="lite",
            intensity_source="routing.commands",
            body="task",
            context_blocks=[ContextBlock(text=large)],
            config_path=str(self.config_path),
            root=self.root,
        )
        self.assertTrue(result.compression_applied)
        self.assertEqual(result.compression_mode, MODE_ACTIVE_LOSSY)

    def test_stale_evidence_fallback_to_lossless(self) -> None:
        self._write_config(phase=MODE_ACTIVE_LOSSY)
        large = "fallback " * 300
        processed = process_context_block(
            ContextBlock(text=large),
            config=load_context_compression_config(self.root, str(self.config_path)),
            root=self.root,
            compression_mode=MODE_LOSSLESS,
            capability_revision=None,
        )
        self.assertFalse(processed.compressed)

    def test_safety_veto_blocks_active_lossy(self) -> None:
        _seed_compression_registry(self.root, state=STATE_ACTIVE)
        self._write_config(phase=MODE_ACTIVE_LOSSY)
        transcript = "BEGIN TRANSCRIPT\noperator spoke about deploy\nEND TRANSCRIPT\n" + ("x " * 200)
        mode_result = compress_with_mode(
            transcript,
            mode=MODE_ACTIVE_LOSSY,
            budget_tokens=10,
            root=self.root,
            safety_veto=True,
        )
        self.assertNotEqual(mode_result.mode, MODE_ACTIVE_LOSSY)
        self.assertEqual(mode_result.authoritative.text, transcript)

    def test_registry_rollback_on_regression(self) -> None:
        prior_ref = "sha256:" + ("9" * 64)
        rev1 = build_revision_record(
            revision=1,
            state=STATE_SHADOW,
            capability_family="context-compression",
            evidence_class="CompressionEvidence@v1",
            evidence_ref=prior_ref,
            thresholds=_thresholds(),
        )
        rev2 = build_revision_record(
            revision=2,
            state=STATE_ACTIVE,
            capability_family="context-compression",
            evidence_class="CompressionEvidence@v1",
            evidence_ref="sha256:" + ("b" * 64),
            thresholds=_thresholds(),
            prior_active={"revision": 1, "evidenceRef": prior_ref, "state": STATE_ACTIVE},
        )
        capability = build_capability_record(
            COMPRESSION_CAPABILITY_ID,
            capability_family="context-compression",
            revisions={1: rev1, 2: rev2},
            active_revision=2,
        )
        write_registry(registry_path(self.root), build_registry({COMPRESSION_CAPABILITY_ID: capability}))

        large = "rollback " * 300
        mode_result = compress_with_mode(
            large,
            mode=MODE_ACTIVE_LOSSY,
            budget_tokens=10,
            root=self.root,
        )
        metrics = compute_compression_metrics(
            large,
            mode_result,
            root=self.root,
            capability_revision=2,
            safety_veto=False,
            configured_mode=MODE_ACTIVE_LOSSY,
        )
        metrics["falsePositiveRate"] = 1.0
        metrics["falsePositive"] = True
        record_compression_dispatch_evidence(
            metrics,
            root=self.root,
            dispatch_id="regression-dispatch",
        )
        registry = read_registry(registry_path(self.root))
        capability = get_capability(registry, COMPRESSION_CAPABILITY_ID)
        rolled = capability["revisions"]["2"]
        self.assertEqual(rolled["state"], "rolled_back")
        self.assertEqual(capability["activeRevision"], 1)
        self.assertEqual(capability["revisions"]["1"]["state"], STATE_ACTIVE)

    def test_retrieve_key_recovery_metrics(self) -> None:
        large = "recoverable " * 300
        mode_result = compress_with_mode(
            large,
            mode=MODE_SHADOW_LOSSY,
            budget_tokens=10,
            root=self.root,
        )
        metrics = compute_compression_metrics(
            large,
            mode_result,
            root=self.root,
            capability_revision=1,
            safety_veto=False,
            configured_mode=MODE_SHADOW_LOSSY,
        )
        self.assertTrue(metrics["retrieveKeyValid"])
        self.assertGreater(metrics["tokenDelta"], 0)
        self.assertIn("evidenceRef", metrics)


if __name__ == "__main__":
    unittest.main()
