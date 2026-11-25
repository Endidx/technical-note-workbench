import unittest
from analyzer import library


def doc(name, text):
    return {"filename": name, "index": library.index({"filename": name, "content": text})}


def search(old, new, docs):
    return library.search({"before": {"content": old}, "after": {"content": new}, "documents": docs})


class LibraryTests(unittest.TestCase):
    def test_omitted_parameter_and_physical_line_numbers(self):
        notes = [
            doc(
                "cluster.md", "# 实验\n\n```python\nfrom sklearn.cluster import KMeans as KM\nm = KM(3)\n```"
            ),
            doc("unrelated.md", "# 周报\n\n把茶叶装入玻璃瓶。"),
        ]
        result = search(
            "# KMeans\n\n`n_init` defaults to 10.", "# KMeans\n\n`n_init` defaults to auto.", notes
        )
        self.assertEqual([h["filename"] for h in result["hits"]], ["cluster.md"])
        hit = result["hits"][0]
        self.assertEqual(hit["startLine"], 3)
        self.assertIn("KM(3)", hit["text"])
        self.assertIn("AST", [ch["name"] for ch in hit["channels"]])

    def test_other_api_sections_and_no_change(self):
        old = "# Pandas 1.2\n\n## join\n\nJoin has a timeout.\n\n## read_csv\n\n`read_csv` uses header row."
        new = old.replace("1.2", "1.3").replace("header row", "header inference")
        chunks = [
            doc(
                "notes.md",
                "# Notes\n\n## morning\n\nUse read_csv for a batch.\n\n## evening\n\nOur read_csv example.",
            )
        ]
        result = search(old, new, chunks)
        self.assertEqual(len(result["changes"]), 1)
        self.assertNotIn("timeout", result["changes"][0]["before"])
        self.assertEqual({r["startLine"] for r in result["hits"]}, {5, 9})
        self.assertEqual(search(old, old, chunks)["hits"], [])

    def test_cross_language_concept_without_shared_tokens(self):
        notes = [
            doc("policy.md", "# 请求策略\n\n遇到瞬时错误会再次尝试，连续两次仍失败时结束。"),
            doc("other.md", "# 采购\n\n采购了一台显示器。"),
        ]
        result = search("# Transport\n\nRetries: 3", "# Transport\n\nRetries: 4", notes)
        self.assertEqual([h["filename"] for h in result["hits"]], ["policy.md"])
        self.assertIn("Vector", [c["name"] for c in result["hits"][0]["channels"]])

    def test_long_fence_retains_call_on_later_physical_lines(self):
        content = (
            "# 训练\n\n```python\nfrom sklearn.cluster import KMeans as KM\n"
            + "# wait\n" * 40
            + "m = KM(3)\n```"
        )
        hit = search("# KMeans\n\nn_init 10", "# KMeans\n\nn_init auto", [doc("long.md", content)])["hits"]
        self.assertTrue(
            any(
                h["startLine"] <= 45 <= h["endLine"] and any(c["name"] == "AST" for c in h["channels"])
                for h in hit
            )
        )

    def test_single_long_line_bounded(self):
        notes = doc("long.md", "# Long\n\n" + "one two " * 2000)
        chunks = notes["index"]["chunks"]
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(x["text"]) <= 2500 for x in chunks))
        self.assertTrue(all(x["startLine"] == x["endLine"] == 3 for x in chunks))

    def test_link_only_edits_and_sibling_reorder(self):
        old = "# Tasks\n\n[发布](https://example.org/v1)\n\n# Setup\n\n安装指南"
        moved = "# Setup\n\n安装指南\n\n# Tasks\n\n[发布](https://example.org/v1)"
        self.assertEqual(search(old, moved, [])["changes"], [])
        update = search(old, moved.replace("/v1)", "/v2)"), [])["changes"]
        self.assertEqual(len(update), 1)
        self.assertIn("/v1", update[0]["before"])
        self.assertIn("/v2", update[0]["after"])

    def test_leaf_headings_only(self):
        only = doc("outline.md", "# Package v1\n\n## Deprecated API")["index"]["chunks"]
        self.assertEqual([(v["text"], v["startLine"]) for v in only], [("## Deprecated API", 3)])
        changes = search("# Package v1\n\n## Deprecated API", "# Package v2\n\n## New API", [])["changes"]
        self.assertTrue(any("Deprecated API" in row["before"] for row in changes))
        self.assertTrue(any("New API" in row["after"] for row in changes))

    def test_selected_clause_and_tie_ranking(self):
        old = "# Config v1\n\n## retry\n\nRetries 3.\n\n## timeout\n\nTimeout is 10 seconds."
        new = old.replace("v1", "v2").replace("3.", "5.").replace("10 seconds", "20 seconds")
        records = [doc(x, "# Policy\n\nTimeout for client sockets.") for x in ("b.md", "a.md")]
        args = {"before": {"content": old}, "after": {"content": new}, "documents": records}
        compared = library.search(args)
        self.assertEqual(len(compared["changes"]), 2)
        target = next(c for c in compared["changes"] if c["heading"].endswith("timeout"))
        out = library.search(dict(args, changeId=target["id"]))
        self.assertEqual(out["selectedChangeId"], target["id"])
        self.assertEqual([r["filename"] for r in out["hits"]], ["a.md", "b.md"])
        self.assertEqual(out["hits"][0]["channels"], out["hits"][1]["channels"])
        with self.assertRaises(ValueError):
            library.search(dict(args, changeId="invalid"))
