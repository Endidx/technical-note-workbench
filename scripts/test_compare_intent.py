import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_intent import evidence_check


class EvidenceAlignmentTests(unittest.TestCase):
    def test_joint_support_must_include_both_quotes(self):
        case = {"id": "t", "original": "# 台账\n以前试十套。\n现在次数要照旧。",
                "evidenceMode": "all", "evidence": ["以前试十套。", "现在次数要照旧。"]}
        step = {"method":"model", "citations":[{"line": 2, "quote": "以前试十套。"}]}
        self.assertFalse(evidence_check(case, step))
        self.assertTrue(evidence_check(dict(case, evidenceMode="any"), step))
        step["citations"].append({"line": 3, "quote": "现在次数要照旧。"})
        self.assertTrue(evidence_check(case, step))

    def test_unlocatable_quote_fails_even_without_gold(self):
        case = {"id": "t", "original": "这幅图用旧预算。"}
        for cites in ([], [{"line": 2, "quote": "旧预算"}], [{"line": 1, "quote": "新预算"}]):
            with self.subTest(cites=cites), self.assertRaises(ValueError):
                evidence_check(case, {"method":"model", "citations":cites})
