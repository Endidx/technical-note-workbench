import unittest
from unittest.mock import patch
from . import harness, model_intent

CODE = "\n\n```python\nfrom sklearn.cluster import KMeans\nx = KMeans(4)\n```\n"
PURPOSE = "过去的测试做了十次初始化。\n这回还没有确定任务是复现旧结果，还是记录新版默认行为。"
OWNERS = ("分析员要求固定十次初始化。\n写入门教程的人要求使用库默认次数。\n"
          "这两方使用同一段代码。\n尚未选定以哪方为准。")


class DecisionGateTests(unittest.TestCase):
    def run_note(self, body, **params):
        return harness.run(dict(filename="user.md", revision=2, current=body+CODE, **params))

    def test_two_gaps_have_specific_questions_and_quotes_in_both_modes(self):
        for mode in ("rule","model"):
            for body, gap in [(PURPOSE,"migration_purpose"),(OWNERS,"requirement_owner")]:
                with self.subTest(mode=mode,gap=gap), patch.object(model_intent,"complete",side_effect=AssertionError):
                    r = self.run_note(body,intentMode=mode)
                    self.assertEqual((r["status"],r["decisionGap"]),("question",gap))
                    self.assertIsNone(r["proposed"])
                    self.assertEqual(r["decisionPolicy"],"context-decisions-v14")
                    self.assertEqual(set(r["questionChoices"]),{"old","default"})
                    for c in r["citations"]:
                        self.assertIn(c["quote"],body.splitlines()[c["line"]-1])
                    for tool in ("read_intent","ask_user"):
                        step = next(t for t in r["trace"] if t["tool"] == tool)
                        self.assertEqual(step["citations"],r["citations"])

    def test_explicit_selection_unlocks_review(self):
        for body in (PURPOSE, OWNERS):
            self.assertIn("n_init=10",self.run_note(body,answer="old")["proposed"])
            self.assertEqual(self.run_note(body,answer="default")["status"],"complete")
            self.assertIsNone(self.run_note(body,answer="default")["proposed"])
            for target,patch_expected in (("采用新版默认",False),("保留十次初始化",True)):
                result = self.run_note(body+"\n最终决定"+target+"。")
                self.assertEqual(result["status"],"complete")
                self.assertEqual(bool(result["proposed"]),patch_expected)

    def test_separate_scope_reference_and_irrelevant_call(self):
        notes = [
            "# 摘录\n" + "> " + PURPOSE.replace("\n","\n> ") + "\n# 当前调用\n升级后采用新版默认。",
            "# 旧项目摘录\n" + PURPOSE + "\n# 当前入口\n升级后采用新版默认。",
        ]
        for note in notes:
            result = self.run_note(note)
            self.assertEqual(result["status"], "complete")
            self.assertIsNone(result["proposed"])
        body = OWNERS.replace("同一段代码","各自的脚本")
        self.assertNotIn("decisionGap",self.run_note(body))
        for expr in ("KMeans(4,n_init=3)","KMeans(4,init='random')","KMeans(4,**opts)"):
            r = harness.run(dict(filename="x.md",revision=1,current=OWNERS+CODE.replace("KMeans(4)",expr)))
            self.assertNotIn("decisionGap",r)

    def test_implicit_conflict_and_history_without_named_new_option(self):
        implied = OWNERS.split("尚未")[0]
        result = self.run_note(implied)
        self.assertEqual(result["decisionGap"], "requirement_owner")
        self.assertIn("分析员",result["questionChoices"]["old"])
        self.assertIn("教程",result["questionChoices"]["default"])
        self.assertIn("n_init=10",self.run_note(implied+"最终以分析员为准。")["proposed"])
        statement = "上次使用十次初始化。下回的任务目标还没决定。"
        self.assertEqual(self.run_note(statement)["decisionGap"], "migration_purpose")
        unrelated = "上次使用十次初始化。当前决定采用新版默认。任务的图表标题还没决定。"
        self.assertEqual(self.run_note(unrelated)["status"],"complete")

    def test_questions_survive_signed_resume(self):
        req=dict(filename="x.md",revision=0,current=OWNERS+CODE)
        events=list(harness.events(req))
        restored=harness.run(dict(req,checkpoint=events[-2]["checkpoint"]))
        self.assertEqual(restored,events[-1]["result"])

    def test_rephrased_coordinated_claims_and_current_scope(self):
        from .decision_gate import examine
        scenarios = (
            ("平台组让我固定十次初始化，教研组却要同一份程序测试新版默认。", "requirement_owner"),
            ("上个月保存了十次初始化的结果。我还没被告知这回交付要还原旧结果，还是体验新版默认。", "migration_purpose"),
            ("既可能拿来复刻旧图，也可能用来测新版开箱。组长没告诉我它的用途。", "migration_purpose"),
            ("训练组要求十次初始化。说明组建议同一个发布包采用新版默认。", "requirement_owner"),
            ("训练组要求十次初始化。说明组建议另一份脚本采用新版默认。", None),
            ("训练组要求固定十次初始化。讲师不想让同一个发布包采用新版默认。", None),
            ("以前的项目做了十次初始化。假如新版怎么选我就怎么跑，会怎样？", None),
            ("制图员要求十次初始化。导览组要求同一份程序固定十次初始化。", None),
        )
        for note,expected in scenarios:
            with self.subTest(note=note):
                finding = examine(note)
                self.assertEqual((finding or {}).get("decisionGap"),expected)
                if expected is None:
                    self.assertFalse((finding or {}).get("resolved"))

    def test_new_authorial_decision_supersedes_historical_budget(self):
        for past in ("去年档案保留了十次初始化的输出。","当年报告用了十次初始化。"):
            result = self.run_note(past+"新库怎么选次数，我就怎么跑。")
            self.assertEqual(result["status"], "complete")
            self.assertIsNone(result["proposed"])
        decided = OWNERS+"\n原来的复现方案已被否决，最终以写入门教程的人为准。"
        self.assertEqual(self.run_note(decided)["status"],"complete")
        self.assertIsNone(self.run_note(decided)["proposed"])
        revised = OWNERS+"\n最终采用新版默认。随后已经决定保留十次初始化。"
        self.assertIn("n_init=10",self.run_note(revised)["proposed"])
