"""Unit tests for context_compress.py (PRD 058 phase 11 R31)."""
from __future__ import annotations

import json
import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from context_compress import (  # noqa: E402
    CONTENT_DIFF,
    CONTENT_JSON,
    CONTENT_LOG,
    CONTENT_PROSE,
    ContextCacheWriteError,
    ContextRetrieveKeyUnknown,
    RawTranscriptRejected,
    compress,
    detect_content_type,
    estimate_tokens,
    retrieve,
)

JSON_REPORT = json.dumps(
    {
        "summary": "Security review findings",
        "findings": [{"id": "F1", "severity": "high", "detail": "x" * 200}],
    },
    indent=2,
)

UNIFIED_DIFF = """diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,5 +1,6 @@
 def main():
-    return 0
+    validate()
+    return 0
"""

LOG_EXCERPT = """2026-07-08T10:00:01 [INFO] service started
2026-07-08T10:00:02 [WARN] retrying connection
2026-07-08T10:00:03 [ERROR] timeout after 30s
"""

PROSE = (
    "This paragraph explains the dispatch boundary. "
    "It should remain prose even when mentioning diff-like tokens.\n\n"
    "Second paragraph with more narrative context."
)

PROSE_WITH_DIFF_MARKERS = (
    "The reviewer noted that lines like --- a/foo and +++ b/foo "
    "can appear inside prose without being a real unified diff."
)

NDJSON_LOG = "\n".join(
    json.dumps({"level": "info", "msg": f"event-{i}"}) for i in range(5)
)

DIFF_WITH_NESTED_FENCE = """diff --git a/doc.md b/doc.md
--- a/doc.md
+++ b/doc.md
@@ -1,8 +1,10 @@
 # Title
+```python
+print("hello")
+```
 unchanged tail line
"""


class ContextCompressTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_detect_representative_fixtures(self) -> None:
        self.assertEqual(detect_content_type(JSON_REPORT), CONTENT_JSON)
        self.assertEqual(detect_content_type(UNIFIED_DIFF), CONTENT_DIFF)
        self.assertEqual(detect_content_type(LOG_EXCERPT), CONTENT_LOG)
        self.assertEqual(detect_content_type(PROSE), CONTENT_PROSE)

    def test_detect_adversarial_polyglot_fixtures(self) -> None:
        self.assertEqual(detect_content_type(PROSE_WITH_DIFF_MARKERS), CONTENT_PROSE)
        self.assertEqual(detect_content_type(NDJSON_LOG), CONTENT_JSON)
        self.assertEqual(detect_content_type(DIFF_WITH_NESTED_FENCE), CONTENT_DIFF)

    def test_nested_fence_diff_hunk_compresses_without_error(self) -> None:
        result = compress(DIFF_WITH_NESTED_FENCE, budget_tokens=25, root=self.root)
        self.assertEqual(result.contentType, CONTENT_DIFF)
        self.assertTrue(result.compressed)
        self.assertLess(len(result.text), len(DIFF_WITH_NESTED_FENCE))

    def test_lossless_round_trip_through_redaction(self) -> None:
        payload = "safe payload " * 300
        result = compress(payload, budget_tokens=50, root=self.root)
        self.assertTrue(result.compressed)
        self.assertIsNotNone(result.retrieveKey)
        restored = retrieve(result.retrieveKey, root=self.root)
        self.assertEqual(restored, payload)

    def test_raw_transcript_rejected_before_cache(self) -> None:
        transcript = "user: please dump the full chat log\nassistant: here it is"
        with self.assertRaises(RawTranscriptRejected):
            compress(transcript, budget_tokens=5, root=self.root)

    def test_threshold_gating_passthrough(self) -> None:
        small = "short text"
        result = compress(small, budget_tokens=estimate_tokens(small) + 10, root=self.root)
        self.assertFalse(result.compressed)
        self.assertEqual(result.text, small)
        self.assertIsNone(result.retrieveKey)

    def test_concurrent_cache_writes_same_content(self) -> None:
        payload = "shared cache payload " * 200
        keys: list[str | None] = [None, None]

        def worker(idx: int) -> None:
            result = compress(payload, budget_tokens=30, root=self.root)
            keys[idx] = result.retrieveKey

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(keys[0], keys[1])
        self.assertIsNotNone(keys[0])
        self.assertEqual(retrieve(keys[0], root=self.root), payload)

    def test_cache_collision_raises_typed_error(self) -> None:
        first = "alpha payload " * 100
        second = "beta payload " * 100
        forced = "deadbeef" * 8

        with patch("context_compress._cache_key", return_value=forced):
            first_result = compress(first, budget_tokens=20, root=self.root)
            self.assertIsNotNone(first_result.retrieveKey)
            with self.assertRaises(ContextCacheWriteError):
                compress(second, budget_tokens=20, root=self.root)

    def test_retrieve_unknown_key_raises(self) -> None:
        with self.assertRaises(ContextRetrieveKeyUnknown):
            retrieve("0" * 64, root=self.root)


if __name__ == "__main__":
    unittest.main()
