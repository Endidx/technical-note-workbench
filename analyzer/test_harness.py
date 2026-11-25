import unittest
from unittest.mock import patch

from analyzer.engine import NOTES
from analyzer.harness import run


def request(name, answer=None):
    path = next(NOTES.glob(name + "*.md"))
    return dict(current=path.read_text(), filename=path.name, revision=3, answer=answer)


class HarnessTests(unittest.TestCase):
    def test_bundled_outcomes_and_trace(self):
        for prefix, status, changed in (("01", "complete", True), ("02", "complete", False),
                                        ("03", "complete", False), ("04", "question", False)):
            with self.subTest(prefix=prefix):
                result = run(request(prefix))
                self.assertEqual(result["status"], status)
                self.assertEqual(result["proposed"] is not None, changed)
                self.assertEqual(result["revision"], 3)
                self.assertTrue(all(set(t) == ({"tool", "summary", "evidence", "applicability"} if t["tool"]=="read_intent" else {"tool", "summary", "evidence"}) for t in result["trace"]))
                self.assertIn("inspect_code", [t["tool"] for t in result["trace"]])

    def test_answer_changes_only_requested_choice(self):
        data = request("04", "old")
        self.assertEqual(run(data)["proposed"], data["current"].replace("state=9)", "state=9, n_init=10)"))
        self.assertIsNone(run(dict(data, answer="default"))["proposed"])

    def test_changed_input_and_unsupported_init(self):
        for extra, status in ((", init='random'", "complete"), (", init='k-means++'", "question"),
                              (", init=some_func", "blocked"), (", **settings", "question")):
            data = request("04")
            data["current"] = data["current"].replace("state=9)", f"state=9{extra})")
            self.assertEqual(run(data)["status"], status)

    def test_reject_invalid_answers_and_paths_are_never_read(self):
        with self.assertRaises(ValueError):
            run(dict(request("04"), answer="other"))
        with self.assertRaises(ValueError):
            run(dict(request("04"), filename="../secret"))

    @patch("analyzer.harness.remote_choice", return_value="read_disk")
    def test_remote_invalid_tool_fails_closed(self, _):
        with patch.dict("os.environ", {"HARNESS_PLANNER": "remote"}):
            result = run(request("01"))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["trace"], [])
        self.assertIsNone(result["proposed"])

    def test_current_pin_and_upgrade_with_same_code(self):
        data = request("04")
        data["current"] = data["current"].replace("初步尝试把文本分为六组，后续再比较聚类结果。",
            "本项目锁定 scikit-learn==1.1.3")
        pinned = run(data)
        self.assertEqual(pinned["status"], "complete")
        self.assertIsNone(pinned["proposed"])
        self.assertIn("本项目锁定 scikit-learn==1.1.3", [s["evidence"] for s in pinned["trace"]])
        upgraded = run(dict(data, current=data["current"].replace("1.1.3", "1.4.2")))
        self.assertEqual(upgraded["status"], "question")

    def test_bad_dynamic_call_never_returns_patch(self):
        data = request("01")
        data["current"] = data["current"].replace("model = ", "KMeans = other\nmodel = ")
        self.assertEqual(run(data)["status"], "blocked")

    def test_actual_remote_tool_request_schema(self):
        import json
        import io
        from analyzer.harness import remote_choice
        choices = {"choices": [{"message": {"tool_calls": [{
            "type": "function", "function": {"name": "inspect_code", "arguments": "{}"}}]}}]}
        with patch.dict("os.environ", {"HARNESS_BASE_URL": "https://example.org/v1", "HARNESS_MODEL": "model"}):
            with patch("analyzer.harness.build_opener") as opener:
                opener.return_value.open.return_value = io.BytesIO(json.dumps(choices).encode())
                self.assertEqual(remote_choice(["inspect_code"], []), "inspect_code")
                request_obj = opener.return_value.open.call_args[0][0]
                wire = json.loads(request_obj.data)
                self.assertEqual(wire["tools"][0]["function"]["name"], "inspect_code")
                self.assertEqual(wire["tool_choice"], "required")

    def test_explicit_or_conflicting_intents(self):
        data = request("04")
        examples = [
            ("升级后采用新版默认。", "complete", False),
            ("升级后保留 10 次初始化。", "complete", True),
            ("升级后不要保留 10 次初始化。", "question", False),
            ("升级后保留 10 次初始化。\n升级后采用新版默认。", "question", False),
        ]
        for text, expected, patch in examples:
            with self.subTest(text=text):
                result = run(dict(data, current=data["current"] + text))
                self.assertEqual(result["status"], expected)
                self.assertEqual(result["proposed"] is not None, patch)

    def test_remote_planner_may_change_order_but_cannot_skip_evidence(self):
        from analyzer.harness import MAX_STEPS
        with patch.dict("os.environ", {"HARNESS_PLANNER": "remote"}):
            with patch("analyzer.harness.remote_choice", side_effect=lambda allowed, _: allowed[-1]):
                result = run(request("04"))
            self.assertEqual(result["status"], "question")
            self.assertEqual(result["trace"][0]["tool"], "read_sources")
            self.assertLessEqual(len(result["trace"]), MAX_STEPS)
            with patch("analyzer.harness.remote_choice", return_value="submit_result"):
                self.assertEqual(run(request("01"))["status"], "blocked")

    @patch("analyzer.harness.MAX_STEPS", 2)
    def test_truncated_budget_blocks_patch(self):
        result = run(request("01"))
        self.assertEqual(result["status"], "blocked")
        self.assertIsNone(result["proposed"])
        self.assertEqual(len(result["trace"]), 2)
