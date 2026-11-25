import unittest
from unittest.mock import patch

from . import harness, semantic_gate
from .test_decision_gate import CODE


class ReferentTests(unittest.TestCase):
    def investigate(self,prose,mode="rule",**args):
        return harness.run(dict(current=prose+CODE,revision=3,filename="note.md",intentMode=mode,**args))

    def test_distinct_entities_and_responses(self):
        cases=[
            ("下载目录里有两个实验包，发来的文件名缺少后缀。\n「长桥」是旧版复现包；「飞舟」是新版默认演示包。\n没有说明今天要交哪一个。","artifact","长桥","飞舟"),
            ("单据只留下编号，没说要哪项成果。这个编号既用于补录旧预算的基线图，也用于展示出厂配置的实操课。","deliverable","基线图","实操课"),
            ("现场组坚持在同一运行保留旧预算；培训组坚持这一运行展示出厂设置。两边都没同意撤回。","authority","现场组","培训组"),
            ("两组审核同一次运行。\n质检部：\n应当复现旧版的结果。\n教学部：\n使用新版默认效果。","authority","质检部","教学部"),
        ]
        cases.extend([
            ("这段代码由两个工作组共用。测量组要求保留十次初始化。课程组要求采用新版默认。这段调用到底以谁为准，尚未决定。","authority","测量组","课程组"),
            ("目录里有两个脚本，路径被截掉，没说要哪一个。一个名为 `cliff_a.py`，用于复现旧版验收图。另一份是 `cove_b.py`，用于展示新版默认行为。","artifact","cliff_a.py","cove_b.py"),
        ])
        for body,target,old,new in cases:
            for mode in ("rule","model"):
                with self.subTest(target=target,mode=mode),patch.object(semantic_gate,"classify",side_effect=AssertionError("both grounded choices are sufficient")):
                    q=self.investigate(body,mode)
                    self.assertEqual(q.get("decisionTarget"),target)
                    self.assertIsNone(q["proposed"])
                    for key,name in [("old",old),("default",new)]:
                        self.assertIn(name,q["questionChoices"][key])
                        self.assertIn(name,q["question"])
                        e=q["choiceEvidence"][key]
                        self.assertIn(e["quote"],body.splitlines()[e["line"]-1])
                        r=self.investigate(body,mode,answer=key)
                        self.assertEqual(r["status"],"complete")
                        self.assertEqual(bool(r["proposed"]),key=="old")

    def test_no_guess_from_truncated_reference_or_withdrawn_requirement(self):
        body="有两个同名文件，路径只留下前缀。一个复现旧版十次初始化，另一个用途尚缺。未说明要交哪一个。"
        r=self.investigate(body)
        self.assertEqual(r["status"],"blocked")
        self.assertNotIn("questionChoices",r)
        self.assertIsNone(r["proposed"])

    def test_withdrawn_candidate_cannot_be_selected_as_current(self):
        body="检修组要求同一次运行保留旧版预算。教研组要求同一运行展示出厂模式。检修组已撤回自己的主张。"
        result=self.investigate(body)
        self.assertEqual(result["status"],"blocked")
        self.assertIsNone(result["proposed"])
        self.assertNotIn("questionChoices",result)

    def test_named_resolution_needs_no_second_confirmation(self):
        pre="包名未说明。两个候选如下。\n「云雀」是旧版复现包；「青鸟」用于展示新版默认。"
        for label,expected in [("云雀",True),("青鸟",False)]:
            with self.subTest(label=label):
                r=self.investigate(pre+"最终已选择"+label+"。")
                self.assertEqual(r["status"],"complete")
                self.assertEqual(bool(r["proposed"]),expected)
