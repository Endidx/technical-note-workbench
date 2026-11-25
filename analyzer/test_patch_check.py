import unittest
from analyzer.patch_check import verify


class PatchTests(unittest.TestCase):
    original = "# 图表\n\n```python\nfrom sklearn.cluster import KMeans\nm = KMeans(5)\n```\n"

    def test_reject_other_changes_even_when_ten_is_present(self):
        good = self.original.replace("5)", "5, n_init=10)")
        verify(self.original, good, expanded=False)
        for wrong in (good.replace("# 图表", "# 其他"), good.replace("5,", "8,"),
                      good.replace("m =", "u ="), good.replace("10)", "10.0)")):
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                verify(self.original, wrong, expanded=False)

    def test_expanded_mapping_and_precedence(self):
        before = self.original.replace("5)", "5, **opts)")
        good = before.replace("**opts)", "**{'n_init': 10, **opts})")
        verify(before, good, expanded=True)
        for wrong in (good.replace("**opts}", "**other}"), good.replace("m =", "u ="),
                      good.replace("'n_init': 10, **opts", "**opts, 'n_init': 10")):
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                verify(before, wrong, expanded=True)

    def test_propose_count_formats(self):
        from analyzer.patch_check import propose_count
        for args, expected in (("n_init='auto'", "n_init=7"),
                               ("n_init = (0x1), random_state=9", "n_init = (7), random_state=9"),
                               ("", "n_init=7"), ("\n    4, # 聚类数\n", "\n    4, n_init=7, # 聚类数\n"),
                               ("\n    random_state=2,\n", "\n    n_init=7,\n    random_state=2,\n")):
            note = self.original.replace("m = KMeans(5)", "模型 = KMeans(" + args + ")")
            for eol in ("\n", "\r\n"):
                source = note.replace("\n", eol)
                wanted = note.replace("KMeans(" + args + ")", "KMeans(" + expected + ")").replace("\n", eol)
                with self.subTest(args=args, eol=eol):
                    self.assertEqual(propose_count(source, 7), wanted)

    def test_arbitrary_count_dependencies_are_closed(self):
        from analyzer.patch_check import propose_count
        for args in ("n_init=calc()", "n_init=True", "n_init='other'", "n_init=7", "**opts"):
            with self.subTest(args=args), self.assertRaises(ValueError):
                propose_count(self.original.replace("5)", args + ")"), 7)
        for count in (0, -1, True, 10.0, "4"):
            with self.subTest(count=count), self.assertRaises(ValueError):
                propose_count(self.original, count)
