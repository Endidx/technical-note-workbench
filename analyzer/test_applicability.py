import unittest
from unittest.mock import patch
from . import applicability, harness, model_intent
from .test_decision_gate import CODE


class ApplicabilityTests(unittest.TestCase):
    def investigate(self, text, **args):
        return harness.run(
            dict(current=text + CODE, filename="x.md", revision=5, **args)
        )

    def test_counterfactual_owners_swapped_and_selected(self):
        for old, new in [("林真", "吴南"), ("吴南", "林真")]:
            text = f"{new}是试用验收人，要求采用新版默认。{old}是质检验收人，要求每次保留十组初始中心。盖章栏空白。"
            for mode in ("rule", "model"):
                with patch(
                    "analyzer.model_intent.structured_call",
                    side_effect=model_intent.ModelUnavailable("offline"),
                ):
                    r = self.investigate(text, intentMode=mode)
                self.assertEqual(r["status"], "question")
                self.assertIn(old, r["questionChoices"]["old"])
                self.assertIn(new, r["questionChoices"]["default"])
                for key in ("old", "default"):
                    cites = r["choiceCitations"][key]
                    self.assertTrue(all(c["quote"] in text for c in cites))
                for who, changed in [(old, True), (new, False)]:
                    elected = self.investigate(text + f"正式指定{who}终审。")
                    self.assertEqual(elected["status"], "complete")
                    self.assertEqual(bool(elected["proposed"]), changed)

    def test_model_objection_runs_binding_extraction_with_no_keyword_precondition(self):
        text = "我需要维持旧预算。另有意见要先核实。"
        origin = {"method": "model", "evidence": "我需要维持旧预算。"}
        opposite = {
            "question": "听谁的？",
            "citations": [{"quote": "另有意见要先核实。", "line": 1, "sentence": 2}],
        }

        def extraction(prose, force=False, on_call=None):
            self.assertTrue(force)
            if on_call:
                on_call()
            return opposite

        with (
            patch.object(
                applicability,
                "model_review",
                return_value=("两项要求仍待选择", opposite["citations"]),
            ),
            patch("analyzer.binding_records.inspect", side_effect=extraction) as tool,
        ):
            gate, trace = applicability.evaluate(
                text, "old", None, "model", None, origin
            )
            self.assertEqual(tool.call_count, 1)
            self.assertEqual(trace["outcome"], "ask")
            self.assertTrue(trace["modelCalled"])
            self.assertEqual(gate["question"], opposite["question"])

    def test_separate_calls_are_not_authorization(self):
        note = "不同调用分别用于两门课程。外部教程要求旧版十次初始化。"
        data = {"evidence": "外部教程要求旧版十次初始化。"}
        gate, trace = applicability.evaluate(note, "old", None, "rule", None, data)
        self.assertEqual(trace["outcome"], "ask")
        self.assertTrue(gate["clarify"])
        scoped = note + "但本段要求十次初始化。"
        _, trace = applicability.evaluate(scoped, "old", None, "rule", None, data)
        self.assertEqual(trace["outcome"], "allow")
        self.assertIn("本段", trace["citations"][0]["quote"])

    def test_different_authorisation_positions_and_no_bypass(self):
        requirements = "《银桥图》的要求是十次初始化。《泉城表》的要求是采用新版默认。"
        assignment = "交付单已选定《银桥图》。"
        for text in [requirements + assignment, assignment + requirements]:
            r = self.investigate(text)
            self.assertTrue(r["proposed"])
            audit = next(
                s["applicability"] for s in r["trace"] if s["tool"] == "read_intent"
            )
            self.assertEqual(audit["outcome"], "allow")
            self.assertTrue(any("银桥图" in c["quote"] for c in audit["citations"]))
        with self.assertRaisesRegex(ValueError, "缺少当前修订"):
            harness.conclusion(
                {"mode": "k-means++", "intent": "old", "input": {"current": CODE}}
            )

    def test_signed_ordinals_survive_a_previous_pending_status(self):
        note = "两位负责人陈老师和李老师参与同一次审阅。前者要求保留十次初始化。后者要求采用新版默认。终审人尚未指定。最终由陈老师终审。"
        result = self.investigate(note)
        self.assertIsNotNone(result["proposed"])
        audit = next(
            s["applicability"] for s in result["trace"] if s["tool"] == "read_intent"
        )
        self.assertTrue(any("最终" in c["quote"] for c in audit["citations"]))

    def test_no_positive_evidence_never_allows_patch(self):
        _, review = applicability.evaluate(
            "普通会议记录。", "old", None, "rule", None, {}
        )
        self.assertEqual(review["outcome"], "ask")
        result = self.investigate("这页留待决定。", answer="old")
        audit = next(
            s["applicability"] for s in result["trace"] if s["tool"] == "read_intent"
        )
        self.assertEqual(audit["route"], "user_answer")
        self.assertTrue(result["proposed"])

    def test_current_assignment_precedes_an_individual_proposal(self):
        body = "我要求为这页固定十次初始化。甲班只是拟了这个预算，乙班希望库自行决定，正式交给哪班还没定。"
        for mode in ("rule", "model"):
            with (
                self.subTest(mode=mode),
                patch("analyzer.semantic_gate.inspect", return_value=None),
                patch.object(
                    applicability,
                    "model_review",
                    return_value=("只存在一项当前要求", []),
                ),
            ):
                ask = self.investigate(body, intentMode=mode)
                self.assertEqual(ask["status"], "question")
                self.assertIn("甲班", ask["questionChoices"]["old"])
                self.assertIn("乙班", ask["questionChoices"]["default"])
                for owner, want_edit in (("甲班", True), ("乙班", False)):
                    result = self.investigate(
                        body + f"现已确定交给{owner}执行。", intentMode=mode
                    )
                    self.assertEqual(result["status"], "complete")
                    self.assertEqual(bool(result["proposed"]), want_edit)

    def test_effective_order_outweighs_retired_default_assumption(self):
        record = "执行单正式签发，当前工序按十次初始化复算后才交付。"
        history = "起先我以为要演示新版默认。"
        retirement = "演示用的图册已转交实训组。"
        for parts in ((history, record, retirement), (retirement, record, history)):
            text = "\n".join(parts)
            items, _, _ = applicability.inspect_context(text)
            commitment = next(s for s in items if s.quote == record)
            origin = {
                "method": "model",
                "evidenceRoles": {
                    "practice": commitment.sentence,
                    "commitment": commitment.sentence,
                },
                "citations": [vars(commitment)],
            }
            with patch.object(
                applicability,
                "model_review",
                side_effect=AssertionError("effective order already checked"),
            ):
                _, review = applicability.evaluate(
                    text, "old", None, "model", None, origin
                )
                self.assertEqual(review["outcome"], "allow")
                self.assertEqual(review["route"], "candidate_claims")
        for changed in (
            record.replace("正式签发", "尚待签发"),
            record + "不过执行单还未签字。",
            record + "两个方案现在都有效。",
        ):
            text = history + changed + retirement
            items, _, _ = applicability.inspect_context(text)
            commit = next(s for s in items if "执行单" in s.quote)
            origin = {
                "method": "model",
                "evidenceRoles": {
                    "practice": commit.sentence,
                    "commitment": commit.sentence,
                },
                "citations": [vars(commit)],
            }
            self.assertIsNone(applicability.effective_work_order(items, origin))
