"""Optional real multilingual model acceptance case; uses no external requests."""

import os
import unittest

from analyzer.test_library import doc, search


@unittest.skipUnless(
    os.getenv("LIBRARY_ENCODER") == "onnx", "set LIBRARY_ENCODER=onnx for pretrained acceptance"
)
class MultilingualRetrieval(unittest.TestCase):
    def test_english_change_finds_chinese_runbook(self):
        old = "# Upload guide\n\n## send_file\n\nRetry a failed upload immediately."
        new = old.replace("immediately.", "after a delay.")
        corpus = [
            doc("值班.md", "# 值班手册\n\n文件传输失败时等待一段时间再重新发送。"),
            doc("购物.md", "# 购物\n\n午饭吃了牛肉面，顺便买了个杯子。"),
        ]
        hits = search(old, new, corpus)["hits"]
        self.assertEqual([h["filename"] for h in hits], ["值班.md"])
        self.assertEqual(hits[0]["channels"][0]["name"], "Vector")
        self.assertEqual(hits[0]["channels"][0]["querySide"], "新版条款")

    @unittest.skipUnless(
        os.getenv("LIBRARY_TEST_QDRANT_URL"), "set LIBRARY_TEST_QDRANT_URL to compare with live Qdrant"
    )
    def test_same_real_model_ranking_after_qdrant_publish(self):
        import uuid
        from unittest.mock import patch
        from analyzer import library

        old = "# Upload guide\n\n## send_file\n\nRetry a failed upload immediately."
        payload = {
            "before": {"content": old},
            "after": {"content": old.replace("immediately.", "after a delay.")},
            "workspaceId": str(uuid.uuid4()),
            "generation": "1",
            "documents": [
                doc("值班.md", "# 值班手册\n\n文件传输失败时等待一段时间再重新发送。"),
                doc("购物.md", "# 购物\n\n午饭吃了牛肉面。"),
            ],
        }
        with patch.dict(os.environ, {"LIBRARY_QDRANT_URL": ""}):
            expected = library.search(payload)["hits"]
        with patch.dict(os.environ, {"LIBRARY_QDRANT_URL": os.environ["LIBRARY_TEST_QDRANT_URL"]}):
            library.publish(payload)
            actual = library.search(payload)["hits"]
        self.assertEqual([r["filename"] for r in actual], [r["filename"] for r in expected])
        self.assertEqual(actual[0]["channels"][0]["querySide"], "新版条款")
        self.assertAlmostEqual(
            actual[0]["channels"][0]["score"], expected[0]["channels"][0]["score"], places=5
        )
