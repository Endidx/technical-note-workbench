import unittest
from unittest.mock import patch

from . import bindings, binding_records as records, harness, model_intent
from .test_decision_gate import CODE


class BindingRecordTests(unittest.TestCase):
    note = "周蓝（核准岗）负责本次数值。这里按以往十次初始化重算。何南（演示岗）要求使用新版默认。目前终审签发栏还空着。"
    unsigned = {
        "类别": "最终审阅者",
        "旧对象": "周蓝",
        "旧要求编号": 2,
        "新对象": "何南",
        "新要求编号": 3,
        "决定": "未选定",
        "决定编号": 4,
    }

    def verified(self, note=None, **changes):
        rows = records.spans(bindings.note_items(note or self.note))
        return records.verify(rows, dict(self.unsigned, **changes))

    def test_grounded_records_include_actual_objects_and_policies(self):
        result = self.verified()
        self.assertEqual(result["decisionTarget"], "authority")
        for side, name in (("old", "周蓝"), ("default", "何南")):
            self.assertEqual(result["choiceCitations"][side][0]["quote"], name)
            self.assertIn(result["choiceEvidence"][side]["quote"], self.note)
        for bad in (
            {"旧对象": "赵"},
            {"旧对象": "何南", "新对象": "周蓝"},
            {"新要求编号": 2},
            {"旧要求编号": 0},
            {"决定编号": 3},
            {"决定": "已选定旧方案"},
        ):
            with self.subTest(bad=bad):
                self.assertIsNone(self.verified(**bad))

    def test_actual_assignment_is_required_and_unselected_result_is_vetoed(self):
        prose = self.note + "新签发栏：何南。"
        self.assertIsNone(self.verified(prose))
        result = self.verified(prose, 决定="已选定新方案", 决定编号=5)
        self.assertEqual(result["resolved"], "default")
        self.assertIsNone(
            self.verified(prose + "何南的授权已撤销。", 决定="已选定新方案", 决定编号=5)
        )

    def test_swapping_order_preserves_subject_behaviors_in_rule_mode(self):
        for swapped in (False, True):
            left = "《琴桥档案》，要求按旧预算十轮初始化。"
            right = "《镜港图讯》，要求直接采用升级后的默认效果。"
            text = (right + left if swapped else left + right) + "出版物栏空白。"
            result = harness.run(dict(filename="x.md", current=text + CODE, revision=0))
            self.assertIn("琴桥", result["questionChoices"]["old"])
            self.assertIn("镜港", result["questionChoices"]["default"])

    def test_absent_candidate_does_not_invoke_model(self):
        with patch.object(
            records, "extract", side_effect=AssertionError("unneeded model call")
        ):
            self.assertIsNone(
                records.inspect("我换了版本。旧代码有十轮初始化，目前采取新版默认。")
            )

    def test_preceding_assignment_is_not_overridden_by_a_later_proposal(self):
        prose = "正式指定何南终审。" + self.note.replace("目前终审签发栏还空着。", "")
        rows = records.spans(bindings.note_items(prose))
        extracted = dict(
            self.unsigned,
            **{"旧要求编号": 3, "新要求编号": 4, "决定": "已选定新方案", "决定编号": 1},
        )
        result = records.verify(rows, extracted)
        self.assertEqual(result["resolved"], "default")
        self.assertIsNone(records.verify(rows, dict(extracted, 决定="已选定旧方案")))

    def test_clause_numbers_are_distinct_on_the_same_physical_line(self):
        rows = records.spans(bindings.note_items(self.note))
        self.assertTrue(all(row.line == 1 for row in rows))
        result = records.verify(rows, self.unsigned)
        self.assertNotEqual(
            result["choiceEvidence"]["old"], result["choiceEvidence"]["default"]
        )
