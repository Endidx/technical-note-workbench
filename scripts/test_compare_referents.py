import unittest
from compare_referents import concrete


class QuestionTest(unittest.TestCase):
    def test_only_grounded_correctly_routed_object_choices_count(self):
        note = "青版压缩包和黄版压缩包"
        case = dict(id="sample", original=note, requiredDecision="artifact", targets=[
            dict(answer="old", aliases=["青版"]), dict(answer="default", aliases=["黄版"])])
        raw = dict(status="question", question="要提交哪个包？",
                   questionChoices=dict(old="青版", default="黄版"), citations=[dict(line=1, quote=note)])
        self.assertTrue(concrete(case, raw))
        for replacements in (
                dict(question="要保留十次吗？"), dict(questionChoices=dict(old="黄版", default="青版")),
                dict(questionChoices=dict(old=note, default=note)), dict(citations=[]),
                dict(citations=[dict(line=2, quote=note)]), dict(proposed="candidate")):
            self.assertFalse(concrete(case, dict(raw, **replacements)))

    def test_physical_assignment_requires_an_object_question(self):
        note = "白鹭箱旧预算，灰雁柜用默认。"
        case = dict(id="sample", original=note, requiredDecision="artifact",
                    targetType="physical", targets=[
                        dict(answer="old", aliases=["白鹭箱"]),
                        dict(answer="default", aliases=["灰雁柜"])])
        raw = dict(status="question", question="这份笔记用于哪台设备？",
                   questionChoices=dict(old="白鹭箱", default="灰雁柜"),
                   citations=[dict(line=1, quote=note)])
        self.assertTrue(concrete(case, raw))
        for question in ("白鹭箱和灰雁柜要保留十次吗？", "需要提交哪个文件或包？"):
            self.assertFalse(concrete(case, dict(raw, question=question)))

    def test_policy_evidence_must_belong_to_named_choice(self):
        from compare_referents import supported_choices
        lines = ["松涛纪要", "旧预算十套", "海湾草案", "新版原生"]
        case = dict(id="sample", original="\n".join(lines), requiredDecision="deliverable",
                    targets=[dict(answer=k, aliases=[lines[i]], policyAliases=[lines[i+1]])
                             for i, k in ((0, "old"), (2, "default"))])
        cites = [dict(line=i, quote=q) for i, q in enumerate(lines, 1)]
        raw = dict(status="question", question="本次准备哪份报告？", citations=cites,
                   questionChoices=dict(old=lines[0], default=lines[2]),
                   choiceCitations=dict(old=cites[:2], default=cites[2:]))
        self.assertTrue(supported_choices(case, raw))
        raw["choiceCitations"]["old"] = [cites[0], cites[3]]
        self.assertFalse(supported_choices(case, raw))
