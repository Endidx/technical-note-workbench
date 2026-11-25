"""Opt-in real-service smoke test, using public synthetic notes in a uniquely scoped generation."""

import os
import uuid
import unittest
from unittest.mock import patch

from analyzer import library
from analyzer.test_library import doc


@unittest.skipUnless(
    os.getenv("LIBRARY_TEST_QDRANT_URL"), "set LIBRARY_TEST_QDRANT_URL to run the Qdrant contract"
)
class QdrantContract(unittest.TestCase):
    def test_ready_gate_idempotency_isolation_and_vector_ranking(self):
        payload = {
            "workspaceId": str(uuid.uuid4()),
            "generation": "1",
            "documents": [doc("retry.md", "# 错误处理\n\n遇到错误会再次尝试。")],
            "before": {"content": "# Fetch\n\nRetries: 2"},
            "after": {"content": "# Fetch\n\nRetries: 3"},
        }
        with patch.dict(os.environ, {"LIBRARY_QDRANT_URL": ""}):
            local = library.search(payload)["hits"]
        with patch.dict(os.environ, {"LIBRARY_QDRANT_URL": os.environ["LIBRARY_TEST_QDRANT_URL"]}):
            with self.assertRaises(RuntimeError):
                library.search(payload)
            for _ in range(2):
                self.assertEqual(library.publish(payload)["backend"], "qdrant")
            live = library.search(payload)["hits"]
            self.assertEqual([r["filename"] for r in live], [r["filename"] for r in local])
            self.assertEqual(live[0]["channels"][0]["name"], "Vector")
            self.assertAlmostEqual(
                live[0]["channels"][0]["score"], local[0]["channels"][0]["score"], places=5
            )
            with self.assertRaises(RuntimeError):
                library.search(dict(payload, generation="2"))
