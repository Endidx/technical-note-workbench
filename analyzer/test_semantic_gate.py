import unittest
from unittest.mock import patch
from . import semantic_gate as gate, harness
from .test_decision_gate import CODE


def reply(relation, ids, old="", new=""):
    return {"结论":relation,"判断理由":"比较当前拥有者、用途与裁决","依据句号":ids,"旧方或旧目标原词":old,"新方或新目标原词":new}


class SemanticGateTests(unittest.TestCase):
    def test_roles_and_citations_verified(self):
        note = "校准员想要十次初始化。带教员让同一次演示采用新版默认。"
        for result, accepted in [(reply(gate.SHARED,[1,2],"校准员","带教员"),True),
                                (reply(gate.SHARED,[1,2],"主管","带教员"),False),
                                (reply(gate.SHARED,[1,2],"校准员","校准员"),False),
                                (reply(gate.SHARED,[1,9],"校准员","带教员"),False)]:
            with self.subTest(result=result),patch.object(gate,"classify",return_value=result):
                finding=gate.inspect(note)
                self.assertEqual(bool(finding),accepted)
                if accepted:
                    self.assertEqual(finding["decisionGap"],"requirement_owner")

    def test_native_requires_committed_verifiable_default(self):
        for body,accepted in [
            ("旧脚本做过十次初始化。我们已升级到1.4。",False),
            ("旧项目用十次初始化。本次只演示新版原样的效果。",True),
            ("旧项目用十次初始化。可能采用新版默认。",False),
            ("实验笔记需要十次初始化。本次采用新版默认，还是保留十次初始化？",False),
        ]:
            with self.subTest(body=body),patch.object(gate,"classify",return_value=reply(gate.FINAL,[2])):
                self.assertEqual(bool(gate.inspect(body)),accepted)

    def test_purpose_requires_alternatives_and_active_uncertainty(self):
        with patch.object(gate,"classify",return_value=reply(gate.ALTERNATIVE,[1,2])):
            self.assertIsNone(gate.inspect("需要旧版十次初始化。最新版尚未安装。"))
            gap=gate.inspect("复现旧作业还是展示新版默认？我没收到用途说明。")
            self.assertEqual(gap["decisionGap"],"migration_purpose")

    def test_rule_answer_and_nonaffected_calls_skip_model(self):
        with patch.object(gate,"classify",side_effect=AssertionError):
            def run(code=CODE,**params):
                return harness.run(dict(filename="x.md",revision=1,current="本周例会。整理完笔记。"+code,**params))
            self.assertIsNotNone(run(intentMode="model",answer="old")["proposed"])
            self.assertIsNone(run(intentMode="model",answer="default")["proposed"])
            self.assertEqual(run(intentMode="rule")["status"],"question")
            self.assertEqual(run(CODE.replace("KMeans(4)","KMeans(4,n_init=1)"),intentMode="model")["status"],"complete")
            self.assertIsNone(gate.inspect("本周例会。整理完笔记。"))

    def test_malformed_output_falls_back_to_existing_rule(self):
        with patch.object(gate,"classify",return_value={"unexpected":1}):
            result=harness.run(dict(filename="x.md",revision=1,current="我是负责人。升级后保留 10 次初始化。"+CODE,intentMode="model"))
            self.assertIn("n_init=10",result["proposed"])

    def test_two_quoted_deliverables_cannot_authorize_default(self):
        body = "交付可能是旧结果复现，也可能是新版默认说明。现在不知要交哪一份。"
        with patch.object(gate,"classify",return_value=reply(gate.FINAL,[1,2],"旧结果复现","新版默认说明")):
            result=gate.inspect(body)
            self.assertEqual(result["decisionGap"],"migration_purpose")
            self.assertNotIn("resolved",result)
