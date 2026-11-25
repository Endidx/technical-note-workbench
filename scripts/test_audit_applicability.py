import unittest

from audit_applicability import audit


class ApplicabilityAuditTests(unittest.TestCase):
    def test_prepatch_allow_must_be_grounded_even_if_patch_is_valid(self):
        note = "本次要求十次初始化。\n```python\nfrom sklearn.cluster import KMeans\nm = KMeans()\n```\n"
        gate = dict(route="single_goal", outcome="allow", reason="当前任务的初始化要求",
                    modelCalled=False, citations=[dict(line=1, quote="本次要求十次初始化。")])
        raw = dict(status="complete", proposed=note.replace("KMeans()", "KMeans(n_init=10)"),
                   trace=[dict(tool="read_intent", applicability=gate)])
        report = dict(status="finished", gold=[dict(id="x", original=note)],
                      records=[dict(method="agent", caseId="x", raw=raw)])
        self.assertEqual(sum(audit(report).values()), 1)
        for key, value in (("outcome","pause"), ("citations",[]), ("route","user_answer"),
                           ("citations",[dict(line=2, quote="十次初始化")])):
            with self.subTest(key=key):
                raw["trace"][0]["applicability"] = dict(gate, **{key:value})
                with self.assertRaises(ValueError):
                    audit(report)

    def test_reference_target_and_candidate_are_both_checked_against_gold(self):
        note = "参照组设为六次。\n```python\nfrom sklearn.cluster import KMeans\nm=KMeans(n_init=1)\n```"
        gate = dict(route="reference", outcome="allow", reason="按参照组的次数对齐",
                    modelCalled=False, citations=[dict(line=1, quote="参照组设为六次。")])
        step = dict(tool="read_intent", method="reference", applicability=gate,
                    referenceEvidence=dict(targetCount=6))
        raw = dict(status="complete", proposed=note.replace("n_init=1", "n_init=6"), trace=[step])
        report = dict(status="finished", gold=[dict(id="x", original=note, targetNInit=6)],
                      records=[dict(method="agent", caseId="x", raw=raw)])
        self.assertEqual(sum(audit(report).values()), 1)
        step["referenceEvidence"]["targetCount"] = 10
        with self.assertRaises(ValueError):
            audit(report)
        raw["proposed"] = note.replace("n_init=1", "n_init=10")
        with self.assertRaises(ValueError):
            audit(report)
