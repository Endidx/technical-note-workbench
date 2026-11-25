import unittest
from unittest.mock import patch
from . import harness, semantic_gate
from .test_decision_gate import CODE


class BindingTests(unittest.TestCase):
    authors = "陈冬的批注是维持旧预算。\n郑竹的批注是采用新版默认。\n同一调用只需一位终审人。"
    documents = "本次交付考虑《北塔风积分图》或《南岸原生示意表》。\n后者应展示新版默认。\n前者需要十次初始化。"

    def check(self, prose, mode="rule", **kwargs):
        with patch.object(semantic_gate, "inspect", return_value=None):
            return harness.run(dict(current=prose+CODE,revision=0,filename="note.md",intentMode=mode,**kwargs))

    def test_missing_reviewer_then_answers(self):
        for mode in ("rule","model"):
            body=self.authors+"签发栏空白。"
            r=self.check(body,mode)
            self.assertEqual(r["decisionTarget"],"authority")
            for key,name in (("old","陈冬"),("default","郑竹")):
                self.assertIn(name,r["questionChoices"][key])
                cites=r["choiceCitations"][key]
                self.assertEqual(cites[0]["quote"],name)
                self.assertIn(cites[-1]["quote"],body.splitlines()[cites[-1]["line"]-1])
                decision=self.check(body,mode,answer=key)
                self.assertEqual(bool(decision["proposed"]),key=="old")

    def test_current_signed_selection_has_priority_and_can_precede_claims(self):
        for note,want_edit in [
            ("签发栏：陈冬。"+self.authors,True),
            (self.authors+"最终由前者终审，后改由后者终审。",False),
            (self.authors+"陈冬的上期授权已过期。签发栏：郑竹。",False),
            (self.documents+"会上决定只交《南岸原生示意表》。",False),
            (self.documents+"会上决定只交《北塔风积分图》。",True),
        ]:
            with self.subTest(note=note):
                r=self.check(note)
                self.assertEqual(r["status"],"complete")
                self.assertEqual(bool(r["proposed"]),want_edit)

    def test_unsigned_or_hypothetical_cannot_authorize(self):
        for claim in ("若签发栏：陈冬，需要额外复查。","签发栏未填。陈冬自称有终审权。","另一个任务最终由陈冬终审。"):
            with self.subTest(claim=claim):
                r=self.check(self.authors+claim)
                self.assertEqual(r.get("decisionTarget"),"authority")
                self.assertIsNone(r["proposed"])

    def test_two_unreconciled_signatures_and_unsigned_opinions_stay_open(self):
        for addition in ("签发栏：陈冬。签发栏：郑竹。","陈冬只签了自己的建议。","郑竹提议最终由郑竹终审。"):
            r=self.check(self.authors+addition)
            self.assertEqual(r["status"],"question")
            self.assertEqual(r["decisionTarget"],"authority")
            self.assertIsNone(r["proposed"])

    def test_title_and_requirement_citations_cross_lines_in_reverse_order(self):
        for body in [self.documents+"分发单未填勾选项。",
                     "勾选栏空白。\n## 《北塔风积分图》\n保留十次初始化。\n## 《南岸原生示意表》\n采用新版默认。"]:
            with self.subTest(body=body):
                r=self.check(body)
                self.assertEqual(r.get("decisionTarget"),"deliverable")
                for key,title in (("old","北塔风积分图"),("default","南岸原生示意表")):
                    refs=r["choiceCitations"][key]
                    self.assertEqual(refs[0]["quote"],title)
                    self.assertNotEqual(refs[0]["line"],refs[1]["line"])
                    for ref in refs:
                        self.assertIn(ref["quote"],body.splitlines()[ref["line"]-1])

    def test_unquoted_reports_with_aliases_and_pending_approval(self):
        for alias in ("（南岑周报）", "，简称南岑周报，", "（别称：南岑周报）"):
            body = ("南岑比对周报" + alias + "约定在新版仍试十组初始中心；"
                    "赤岭体验月报，简称赤岭月报，写的是采用发行版默认初始化。"
                    "批件尚未回来。")
            with self.subTest(alias=alias):
                r = self.check(body)
                self.assertEqual(r.get("decisionTarget"), "deliverable")
                for side, title, policy in (("old", "南岑比对周报", "仍试十组初始中心"),
                                            ("default", "赤岭体验月报", "采用发行版默认初始化")):
                    refs = r["choiceCitations"][side]
                    self.assertEqual(refs[0]["quote"], title)
                    self.assertIn(policy, refs[-1]["quote"])
                    for ref in refs:
                        self.assertIn(ref["quote"], body.splitlines()[ref["line"] - 1])

    def test_print_selection_uses_selected_alias_policy(self):
        body = ("云湖现场简报（云湖简报）采用新版默认初始化。"
                "石室复核快报，简称石室快报，要求每批固定十组初始化后择优。")
        for title, edit in (("云湖简报", False), ("石室快报", True)):
            r = self.check(body + "送印单上的题名已定为" + title + "。")
            self.assertEqual(r["status"], "complete")
            self.assertEqual(bool(r["proposed"]), edit)
