import unittest
import json
from pathlib import Path

from analyzer.library import OPERATIONS


OLD = """# scikit-learn 1.1.3
## KMeans
n_init : int, default=10
## OneHotEncoder
OneHotEncoder(*, categories='auto', drop=None, sparse=True, dtype=float)
"""
NEW = """# scikit-learn 1.4.2
## KMeans
n_init : 'auto' or int, default='auto'
When n_init='auto', the number of runs is 10 for random and 1 for k-means++.
## OneHotEncoder
OneHotEncoder(*, categories='auto', drop=None, sparse_output=True, dtype=float)
"""


def source(version, content):
    return dict(name="scikit-learn", filename=f"sklearn-{version}.md", version=version, content=content)


def run(code, prose="", old=OLD, new=NEW):
    note = f"# 笔记\n\n{prose}\n\n```python\n{code}\n```\n"
    operation = OPERATIONS.get("investigate_batch_note")
    assert operation is not None, "batch operation missing"
    return operation(dict(filename="recipe.md", content=note, before=source("1.1.3", old),
                          after=source("1.4.2", new))), note


class BatchNoteTests(unittest.TestCase):
    def test_prelabelled_mapping_cases_and_second_pass(self):
        cases = Path(__file__).resolve().parents[1] / "examples/batch-decisions/cases.json"
        for case in json.loads(cases.read_text(encoding="utf-8")):
            with self.subTest(case=case["id"]):
                data = dict(filename="field-notes.md", content=case["note"],
                            before=source("1.1.3", OLD), after=source("1.4.2", NEW))
                investigate = OPERATIONS["investigate_batch_note"]
                result = investigate(data)
                self.assertEqual(result["status"], case["expected"])
                if case["expected"] == "edit":
                    changed = case["note"].replace(case["old"], case["replacement"])
                    self.assertEqual(result["proposed"], changed)
                    self.assertEqual(investigate(dict(data, content=changed))["status"], "keep")
                else:
                    self.assertIsNone(result["proposed"])
                for term in case.get("questionIncludes", []):
                    self.assertIn(term, result["question"])

    def test_local_mapping_cites_definition_and_exact_key_location(self):
        result, note = run("from sklearn.preprocessing import OneHotEncoder as Enc\n"
                           "设置 = {\n    'sparse': policy(X),\n}\nencoder = Enc(**设置)")
        self.assertEqual(result["status"], "edit")
        for snippet in ("设置 = {", "'sparse': policy(X)", "Enc(**设置)"):
            line = next(i for i, text in enumerate(note.splitlines(), 1) if snippet in text)
            self.assertTrue(any(f"recipe.md · L{line} · " in s and snippet in s
                                for s in result["evidence"]), result["evidence"])

    def test_unverified_ownership_or_collisions_ask(self):
        for code in (
            "cfg = fallback = {'sparse': True}\ne = E(**cfg)",
            "cfg = {'sparse': True}\ne = E(**cfg, **other)",
            "cfg = {'sparse': True}\ne = E(sparse_output=False, **cfg)",
            "cfg = {'sparse': True, 'sparse': False}\ne = E(**cfg)",
            "cfg = {'sparse': True}\nalias = cfg\ne = E(**cfg)",
            "cfg = {'sparse': True}\ne = E(**cfg)\n```\n\n```python\nlog(cfg)",
            "cfg = {'sparse': True}\ninspect(globals())\ne = E(**cfg)",
            "cfg = {'sparse': True}\nfrom elsewhere import cfg\ne = E(**cfg)",
        ):
            with self.subTest(code=code):
                result, _ = run("from sklearn.preprocessing import OneHotEncoder as E\n" + code)
                self.assertEqual(result["status"], "ask")
                self.assertIsNone(result["proposed"])

    def test_followup_draft_resolves_original_demo_without_changing_its_expression(self):
        examples = Path(__file__).resolve().parents[1] / "examples/batch-upgrade/notes"
        original = (examples / "01-config.md").read_text(encoding="utf-8")
        data = dict(filename="01-config.md", content=original,
                    before=source("1.1.3", OLD), after=source("1.4.2", NEW))
        investigate = OPERATIONS["investigate_batch_note"]
        request = investigate(data)
        self.assertEqual(request["status"], "ask")
        self.assertIn("同一", request["question"])
        draft = original.replace("encoder = ", 'encoder_options = {"sparse": profile.width > 100}\nencoder = ')
        result = investigate(dict(data, content=draft))
        self.assertEqual(result["status"], "edit")
        self.assertEqual(result["proposed"], draft.replace('"sparse"', '"sparse_output"'))

    def test_annotated_private_config_used_in_pipeline(self):
        code = ("from sklearn.preprocessing import OneHotEncoder\n"
                "def make_transform(names):\n"
                "    settings: dict = {'sparse': len(names) > 5}\n"
                "    return make_pipeline(OneHotEncoder(**settings), model)")
        result, note = run(code)
        self.assertEqual(result["status"], "edit")
        self.assertEqual(result["proposed"], note.replace("'sparse'", "'sparse_output'"))

    def test_aliases_two_changes_one_source_preserving_edit(self):
        code = ("from sklearn.cluster import KMeans as KM\n"
                "import sklearn.preprocessing as prep\n"
                "labels = KM(3).fit_predict(X)\n"
                "编码 = prep.OneHotEncoder( sparse = False, handle_unknown='ignore')  # sparse stays")
        r, note = run(code, "升级后仍需保留 10 次初始化。")
        self.assertEqual(r["status"], "edit")
        self.assertEqual(r["proposed"], note.replace("KM(3)", "KM(3, n_init=10)")
                         .replace(" sparse = False", " sparse_output = False"))
        for file in ["recipe.md", "sklearn-1.1.3.md", "sklearn-1.4.2.md"]:
            self.assertTrue(any(file in line for line in r["evidence"]))
        self.assertTrue(r["trace"])

    def test_config_and_missing_wrapper_questions_are_specific(self):
        for code, prose, expected in [
            ("from sklearn.cluster import KMeans\nm = KMeans(**model_params)", "", ["model_params", "n_init"]),
            ("from sklearn.preprocessing import OneHotEncoder as Enc\ne = Enc(**cfg)", "", ["cfg", "sparse"]),
            ("from project import build_encoder\ne = build_encoder(sparse=False)",
             "项目封装的 OneHotEncoder 由 build_encoder 创建。", ["build_encoder", "sparse"]),
        ]:
            with self.subTest(code=code):
                r, _ = run(code, prose)
                self.assertEqual(r["status"], "ask")
                self.assertIsNone(r["proposed"])
                for text in expected:
                    self.assertIn(text, r["question"])

    def test_unrelated_and_already_compatible(self):
        for code, expected in [
            ("from another import OneHotEncoder\nx = OneHotEncoder(sparse=False)", "irrelevant"),
            ("print('other')", "irrelevant"),
            ("from sklearn.preprocessing import OneHotEncoder\nx = OneHotEncoder(sparse_output=False)", "keep"),
            ("from sklearn.cluster import KMeans\nx = KMeans(n_init=7)", "keep"),
            ("from sklearn.cluster import KMeans\nx = KMeans(init='random')", "keep"),
            ("from sklearn.cluster import KMeans\nx = KMeans()", "ask"),
        ]:
            with self.subTest(code=code):
                r, _ = run(code)
                self.assertEqual(r["status"], expected)
                self.assertIsNone(r["proposed"])

    def test_incomplete_and_unrelated_evidence_never_authorizes_an_edit(self):
        for old, new in [
            ("", NEW), (OLD, "# KMeans\nn_init=10"),
            ("# KMeans\nNo parameters here.\n## OtherModel\nn_init : int, default=10", NEW),
            (OLD, "# RandomEstimator\nn_init : int, default='auto'"),
        ]:
            with self.subTest(old=old, new=new):
                r, _ = run("from sklearn.cluster import KMeans\nm = KMeans()", "仍需保留 10 次初始化。", old, new)
                self.assertEqual(r["status"], "ask")
                self.assertIsNone(r["proposed"])

    def test_atomic_question_and_shadowed_bindings(self):
        for code in [
            "from sklearn.preprocessing import OneHotEncoder as E\na=E(sparse=False)\nb=E(**cfg)",
            "from sklearn.preprocessing import OneHotEncoder as E\nE = factory\na=E(sparse=False)",
        ]:
            r, note = run(code)
            self.assertEqual(r["status"], "ask")
            self.assertIsNone(r["proposed"])

    def test_version_peer_and_unverified_reference(self):
        for args, prose, status, detail in [
            ("", "维护者要求当前调用与 scikit-learn 1.0.2 保持相同的初始化行为。", "edit", "1.0.2"),
            ("n_init=1", "cuML 一侧以十次初始化拟合。维护者要求 scikit-learn 参照实现与 cuML 使用相同的初始化次数。", "edit", "cuML"),
            ("n_init=3", "维护者要求 scikit-learn 参照实现与 cuML 使用相同的初始化次数。", "ask", "cuML"),
            ("n_init=4", "维护者要求当前调用与 scikit-learn 1.1.3 默认的初始化次数保持一致。", "edit", "1.1.3"),
            ("n_init=settings", "升级后仍需保留 10 次初始化。", "ask", "n_init"),
        ]:
            with self.subTest(prose=prose):
                r, _ = run("from sklearn.cluster import KMeans\nmodel=KMeans(" + args + ")", prose)
                self.assertEqual(r["status"], status)
                if status == "edit":
                    self.assertIn("n_init=10", r["proposed"])
                    self.assertIn(detail, str(r["evidence"]))
                else:
                    self.assertIn(detail, r["question"])

    def test_unbound_constructor_and_unmentioned_wrapper_name(self):
        for code, prose, target in [
            ("x = KMeans()", "", "KMeans"),
            ("from project import prepare\ne = prepare(**external)", "项目包装 OneHotEncoder。", "prepare"),
            ("from sklearn.cluster import KMeans as KM\nctor=KM\nx=ctor(4)", "", "ctor"),
        ]:
            with self.subTest(code=code):
                r, _ = run(code, prose)
                self.assertEqual(r["status"], "ask")
                self.assertIn(target, r["question"])

    def test_grounding_is_estimator_specific_and_does_not_assume_removal(self):
        for old, new, code in [
            (OLD.replace("KMeans", "MiniBatchKMeans"), NEW,
             "from sklearn.cluster import KMeans\nm=KMeans()"),
            (OLD, NEW.replace("sparse_output=True", "sparse=True, sparse_output=True"),
             "from sklearn.preprocessing import OneHotEncoder\ne=OneHotEncoder(sparse=False)"),
            (OLD, NEW.replace("sparse_output=True", "sparse=True, new_output=True"),
             "from sklearn.preprocessing import OneHotEncoder\ne=OneHotEncoder(sparse=False)"),
        ]:
            r, _ = run(code, "升级后仍需保留 10 次初始化。", old, new)
            self.assertEqual(r["status"], "ask")
            self.assertIsNone(r["proposed"])

    def test_non_python_fence_does_not_supply_executable_calls(self):
        content = "# 文档\n\n````markdown\n```python\nfrom sklearn.preprocessing import OneHotEncoder\ne=OneHotEncoder(sparse=False)\n```\n````\n"
        r = OPERATIONS['investigate_batch_note'](dict(filename="x.md", content=content,
                                         before=source("1.1.3", OLD), after=source("1.4.2", NEW)))
        self.assertEqual(r["status"], "irrelevant")
