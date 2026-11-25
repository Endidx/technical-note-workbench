import unittest
from unittest.mock import patch

from analyzer import library
from analyzer.test_library import doc


class ChannelAblation(unittest.TestCase):
    def test_channels_keep_their_production_scores_and_default_fusion(self):
        documents = [
            doc("cluster.md", "# 实验\n\n```python\nfrom sklearn.cluster import KMeans as KM\nKM(3)\n```"),
            doc("plain.md", "# 模型\n\nKMeans 权重聚类"),
        ]
        rows, scope = library.rows_and_scope({"documents": documents})
        change = {"heading": "KMeans", "before": "n_init=10", "after": "n_init=auto"}
        full = library.rank(change, rows, scope)
        self.assertEqual(full, library.rank(change, rows, scope, channels={"BM25", "Vector", "AST"}))
        for channel in ("BM25", "Vector", "AST"):
            expected = {hit["filename"]: info for hit in full for info in hit["channels"] if info["name"] == channel}
            self.assertTrue(expected)
            if channel == "Vector":
                actual = library.rank(change, rows, scope, channels={channel})
            else:
                with patch.object(library.vectors, "encode", side_effect=AssertionError("unused encoder")):
                    actual = library.rank(change, rows, scope, channels={channel})
            self.assertEqual({hit["filename"]: hit["channels"] for hit in actual},
                             {name: [info] for name, info in expected.items()})
