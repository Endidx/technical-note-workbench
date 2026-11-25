import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_decisions import grounded_question


class QuestionAuditTests(unittest.TestCase):
    def test_only_locatable_questions_with_distinct_choices_count(self):
        note = "# 拟合\n留下旧报告，等确认本期用途。"
        good = {"status": "question", "proposed": None, "decisionGap": "migration_purpose",
                "question": "这次按哪个目标运行？", "questionChoices": {"old": "复现", "default": "采用新版"},
                "citations": [{"line": 2, "quote": "等确认本期用途。"}]}
        self.assertTrue(grounded_question(good, "migration_purpose", note))
        for change in ({"decisionGap":"requirement_owner"}, {"proposed":"新的内容"}, {"status":"blocked"},
                       {"questionChoices":{"old":"复现","default":"复现"}}, {"citations":[]},
                       {"citations":[{"line":1,"quote":"等确认本期用途。"}]}):
            self.assertFalse(grounded_question(dict(good, **change), "migration_purpose", note))
