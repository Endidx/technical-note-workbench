import unittest
from unittest.mock import patch

from . import applicability, fit_budget, harness
from .test_decision_gate import CODE


class FitBudgetTests(unittest.TestCase):
    def run_note(self, text, mode="rule"):
        return harness.run(
            dict(filename="case.md", current=text + CODE, revision=2, intentMode=mode)
        )

    def test_unknown_job_titles_and_swapped_owners(self):
        for old, new in [("任瑾", "童林"), ("童林", "任瑾")]:
            for reverse in (False, True):
                claims = [
                    f"{old}是磁场领航，要求每次保留十组初始中心；",
                    f"{new}是灯塔司仪，要求按新版默认执行。",
                ]
                text = (
                    "同一发布只能运行一次。"
                    + "".join(reversed(claims) if reverse else claims)
                    + "签发栏没填。"
                )
                for mode in ("rule", "model"):
                    with (
                        self.subTest(old=old, reverse=reverse, mode=mode),
                        patch(
                            "analyzer.model_intent.structured_call",
                            side_effect=AssertionError("unexpected model"),
                        ),
                    ):
                        result = self.run_note(text, mode)
                        self.assertEqual(result["status"], "question")
                        self.assertIn(old, result["questionChoices"]["old"])
                        self.assertIn(new, result["questionChoices"]["default"])
                        for who, edits in [(old, True), (new, False)]:
                            issued = self.run_note(text + f"正式指定{who}终审。", mode)
                            self.assertEqual(issued["status"], "complete")
                            self.assertEqual(bool(issued["proposed"]), edits)

    def test_parallel_names_and_roleless_objection(self):
        for body in [
            "任瑾和童林两人分别要求十次初始化、采用新版默认。",
            "任瑾坚持十次初始化，童林却主张按新版默认。",
        ]:
            text = "同一调用只发布一次。" + body + "尚待签字。"
            result = self.run_note(text)
            self.assertIn("任瑾", result["questionChoices"]["old"])
            self.assertIn("童林", result["questionChoices"]["default"])

    def test_positive_budget_precedes_optional_model(self):
        signed = "迁移审批单已核准本次沿用旧配置的预算。"
        prior = "旧规范规定每次拟合的候选中心配置为十套，拟合后保留误差最小的一套。"
        direct = "当前拟合规则是每批样本取十组起始中心，最后选误差最低的一组。"
        for note in (signed + prior, prior + signed, direct + "簇数随批次变化。"):
            for mode in ("rule", "model"):
                with (
                    self.subTest(note=note, mode=mode),
                    patch(
                        "analyzer.model_intent.structured_call",
                        side_effect=AssertionError("no redundant review"),
                    ),
                ):
                    result = self.run_note(note, mode)
                    self.assertIsNotNone(result["proposed"])
                    step = next(
                        t for t in result["trace"] if t["tool"] == "read_intent"
                    )
                    self.assertEqual(step["applicability"]["outcome"], "allow")

    def test_budget_units_scope_and_hypotheses(self):
        for body in (
            "每次拟合取十个中心组成一套，最后择优。",
            "拟合规定迭代十轮，每轮准备若干个中心择优。",
            "每次拟合从随机种子10出发，用几个中心择优。",
            "旧规范每次拟合取十组初始中心择优。",
            "假设每次拟合取十组初始中心择优。",
            "每次拟合取十组初始中心择优的要求已取消。",
            "每次拟合最多取十组初始中心择优。",
            "每次拟合取二十组初始中心择优。",
            "每次拟合取十组初始中心择优。今天只想测新版默认效果。",
        ):
            with self.subTest(body=body):
                items, _, _ = applicability.inspect_context(body)
                self.assertIsNone(fit_budget.inspect(items))

    def test_other_parameter_objection_may_not_cancel_verified_current_budget(self):
        text = "拟合规约要求每次运行十次初始化。最后迭代几轮并未决定。"
        items, _, _ = applicability.inspect_context(text)
        origin = {
            "citations": [vars(items[0])],
            "evidenceRoles": {"practice": 1, "commitment": 1},
        }
        self.assertTrue(
            fit_budget.irrelevant_objection(items, origin, [vars(items[1])])
        )
        self.assertIsNone(
            fit_budget.irrelevant_objection(items, origin, [vars(items[0])])
        )
        self.assertIsNone(
            fit_budget.irrelevant_objection(
                items,
                {"citations": [], "evidenceRoles": origin["evidenceRoles"]},
                [vars(items[1])],
            )
        )

    def test_unapproved_policy_does_not_accidentally_become_a_patch(self):
        for text in [
            "若迁移按十组初始中心择优，则要重新拟合。",
            "旧规范每次拟合取十组初始中心择优。",
            "每次拟合取十组初始中心择优的要求已取消。",
            "每次拟合取十个中心组成一套，最后择优。",
        ]:
            self.assertIsNone(self.run_note(text)["proposed"])
