import ast
import unittest

from analyzer import harness


def sample(expression="user_settings", prose="升级后保留 10 次初始化。"):
    return {
        "current": f"# 个人笔记\n\n{prose}\n\n```python\nfrom sklearn.cluster import KMeans\nmodel = KMeans(n_clusters=4, **{expression})\n```\n",
        "filename": "example.md", "revision": 2,
    }


def facts(mapping="user_settings", init="absent", n_init="absent"):
    return {"mapping": mapping, "init": init, "n_init": n_init}


class ExternalConfigTests(unittest.TestCase):
    def test_question_names_mapping_and_requires_config_facts(self):
        req = sample("config['model']")
        result = harness.run(req)
        self.assertEqual(result["status"], "question")
        self.assertEqual(result["questionType"], "external_config")
        self.assertEqual(result["mapping"], "config['model']")
        for text in ("config['model']", "init", "n_init"):
            self.assertIn(text, result["question"])
        unanswered = harness.run(dict(req, answer="old"))
        self.assertEqual(unanswered["status"], "question")
        self.assertIsNone(unanswered["proposed"])

    def test_guarded_patch_preserves_future_explicit_overrides(self):
        req = sample()
        result = harness.run(dict(req, configFacts=facts()))
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["proposed"])
        code = result["proposed"].split("```python\n")[1].split("```")[0]
        tree = ast.parse(code)
        tree.body = tree.body[1:]
        capture = lambda **kw: kw
        for mapping, expected in (({}, 10), ({"n_init": 4}, 4)):
            env = {"KMeans": capture, "user_settings": mapping}
            exec(compile(tree, "test", "exec"), env)
            self.assertEqual(env["model"]["n_init"], expected)
            self.assertNotIn("n_clusters", mapping)

    def test_explicit_unknown_conflicting_and_mismatched_facts(self):
        req = sample()
        result = harness.run(dict(req, configFacts=facts(n_init=7)))
        self.assertEqual(result["status"], "complete")
        self.assertIn("7", str(result["trace"]))
        self.assertIsNone(result["proposed"])
        self.assertEqual(harness.run(dict(req, configFacts=facts(init="random")))["status"], "complete")
        for new in (facts(init="unknown"), facts(n_init="unknown")):
            self.assertEqual(harness.run(dict(req, configFacts=new))["status"], "question")
        self.assertEqual(harness.run(dict(req, configFacts=facts("other")))["status"], "blocked")
        duplicate = dict(req, current=req["current"].replace("n_clusters=4", "init='random'"))
        self.assertEqual(harness.run(dict(duplicate, configFacts=facts(init="random")))["status"], "blocked")
        with self.assertRaises(ValueError):
            harness.run(dict(req, configFacts=facts(n_init=-1)))

    def test_user_attestation_participates_in_checkpoint_identity(self):
        req = dict(sample(), configFacts=facts())
        first = next(harness.events(req))
        changed = dict(req, configFacts=facts(n_init=5), checkpoint=first["checkpoint"])
        result = harness.run(changed)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["trace"], [])
        resumed = harness.run(dict(req, checkpoint=first["checkpoint"]))
        self.assertEqual(resumed["proposed"], harness.run(req)["proposed"])

    def test_partial_facts_only_request_fields_that_can_change_the_decision(self):
        req = sample()
        explicit = harness.run(dict(req, configFacts=facts(init="unknown", n_init=4)))
        self.assertEqual(explicit["status"], "complete")
        self.assertIsNone(explicit["proposed"])
        ambiguous = harness.run(dict(req, configFacts=facts(init="unknown", n_init="absent")))
        self.assertEqual(ambiguous["requiredFields"], ["init"])
        self.assertIn("init", ambiguous["question"])
        self.assertNotIn("n_init", ambiguous["question"])
        pending_count = harness.run(dict(req, configFacts=facts(init="k-means++", n_init="unknown")))
        self.assertEqual(pending_count["requiredFields"], ["n_init"])
        stable = harness.run(dict(req, configFacts=facts(init="random", n_init="unknown")))
        self.assertEqual(stable["status"], "complete")
        self.assertIsNone(stable["proposed"])
        duplicate = dict(req, current=req["current"].replace("n_clusters=4", "init='random'"))
        result = harness.run(dict(duplicate, configFacts=facts(init="unknown", n_init=4)))
        self.assertEqual(result["requiredFields"], ["init"])
        self.assertEqual(harness.run(dict(duplicate, configFacts=facts(init="random",n_init="unknown")))["status"], "blocked")
