import unittest

from scripts import evaluate


class ScoreTests(unittest.TestCase):
    def test_three_labels_and_error_denom(self):
        gold = [
            {"id": str(i), "expected": label} for i, label in enumerate(("edit", "keep", "ask", "edit"))
        ]
        rows = []
        for i, raw in enumerate(({"kind": "change"}, {"kind": "change"}, {"kind": "confirm"}, None)):
            rows.append({"caseId": str(i), "method": "fixed", "latencyMs": i + 1, "raw": raw})
        note = "```python\nfrom sklearn.cluster import KMeans\nm = KMeans()\n```"
        gold[0]["original"] = note
        rows[0]["raw"]["proposed"] = note.replace("KMeans()", "KMeans(n_init=10)")
        rows[-1]["error"] = "解析失败"
        report = evaluate.score(gold, rows, ["fixed"])["fixed"]
        self.assertEqual(report["correct"], 2)
        self.assertEqual(report["accuracy"], 0.5)
        self.assertEqual(report["editRecall"], 0.5)
        self.assertEqual(report["misEditRate"], 0.5)
        self.assertEqual(report["errors"], 1)

    def test_block_is_separate_from_ask_and_errors(self):
        rows = [
            {
                "caseId": "a",
                "method": "agent",
                "latencyMs": 1,
                "raw": {"status": "blocked", "reason": "unknown type", "trace": []},
            }
        ]
        result = evaluate.score([{"id": "a", "expected": "ask"}], rows, ["agent"])["agent"]
        self.assertEqual(result["blocked"], 1)
        self.assertEqual(result["correct"], 0)
        self.assertEqual(result["errors"], 0)

    def test_invalid_direct_json_is_not_a_correct_guess(self):
        raw = {"choices": [{"message": {"content": "Probably edit ..."}}]}
        out = evaluate.score(
            [{"id": "a", "expected": "edit"}],
            [{"caseId": "a", "method": "direct", "latencyMs": 0, "raw": raw}],
            ["direct"],
        )
        self.assertEqual(out["direct"]["errors"], 1)

    def test_duplicate_and_missing_cases_rejected(self):
        gold = [{"id": "a", "expected": "edit"}]
        row = {"caseId": "a", "method": "fixed", "latencyMs": 0, "raw": {"kind": "change"}}
        for bad in ([], [row, row]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                evaluate.score(gold, bad, ["fixed"])

    def test_prompt_has_no_gold_leak(self):
        import json

        case = {"expected": "do-not-leak-gold", "reason": "annotation secret", "original": "# actual note"}
        payload = evaluate.direct_payload(case, {"old": "official snapshot"}, "local")
        wire = json.dumps(payload)
        self.assertNotIn("do-not-leak-gold", wire)
        self.assertNotIn("annotation secret", wire)
        self.assertIn("# actual note", wire)
        self.assertIn("official snapshot", wire)

    def test_recompute_uses_raw_not_cached_predictions(self):
        row = {
            "caseId": "a",
            "method": "direct",
            "latencyMs": 5,
            "prediction": "ask",
            "modelCalls": [{}],
            "raw": {
                "choices": [{"message": {"content": '{"decision":"keep"}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 5},
            },
        }
        result = evaluate.score([{"id": "a", "expected": "keep"}], [row], ["direct"])["direct"]
        self.assertEqual(result["correct"], 1)
        self.assertEqual(result["observedPromptTokens"], 12)
        self.assertIsNone(result["editRecall"])
        self.assertEqual(result["modelCalls"], 1)

    def test_offline_rescore_produces_recalculated_rows(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as base:
            path = Path(base) / "run.json"
            output = Path(base) / "out.json"
            report = {
                "schema": evaluate.SCHEMA,
                "run": {"methods": ["fixed"]},
                "gold": [{"id": "i", "expected": "keep"}],
                "records": [
                    {
                        "caseId": "i",
                        "method": "fixed",
                        "raw": {"kind": "explicit"},
                        "latencyMs": 0.1,
                        "prediction": "edit",
                    }
                ],
            }
            path.write_text(json.dumps(report))
            with patch.object(evaluate, "request_json", side_effect=AssertionError("network prohibited")):
                evaluate.main(["--rescore", str(path), "--output", str(output)])
            recovered = json.loads(output.read_text())
            self.assertEqual(recovered["records"][0]["prediction"], "keep")
            self.assertEqual(recovered["summary"]["fixed"]["correct"], 1)

    def test_constrained_direct_schema(self):
        payload = evaluate.direct_payload({"original": "raw"}, {}, "q")
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        schema = payload["response_format"]["json_schema"]["schema"]
        self.assertEqual(schema["properties"]["decision"]["enum"], ["edit", "keep", "ask"])
        self.assertEqual(set(schema["required"]), {"decision", "reason", "evidence"})
        self.assertTrue(payload["messages"][-1]["content"].endswith(evaluate.DIRECT_SUFFIX))

    def test_correctness_and_evidence_are_independent(self):
        import json

        gold = [
            {"id": "a", "expected": "edit", "original": "代码在此。"},
            {"id": "b", "expected": "ask", "original": "保留原文。"},
        ]
        rows = []
        for cid, answer in [
            ("a", {"decision": "edit", "reason": " ", "evidence": "不存在的片段"}),
            ("b", {"decision": "edit", "reason": "该项需改", "evidence": "保留原文。"}),
        ]:
            rows.append(
                {
                    "caseId": cid,
                    "method": "direct",
                    "latencyMs": 1,
                    "raw": {"choices": [{"message": {"content": json.dumps(answer)}}]},
                }
            )
        metrics = evaluate.score(gold, rows, ["direct"])["direct"]
        self.assertEqual(metrics["correct"], 1)
        self.assertEqual(metrics["qualityEligible"], 2)
        self.assertEqual(metrics["literalNoteEvidenceCount"], 1)
        self.assertEqual(metrics["nonemptyReasonCount"], 1)

    def test_patch_value_is_scored_from_gold_independently(self):
        note = "# 记录\n```python\nfrom sklearn.cluster import KMeans\n模型 = KMeans(n_init = 1) # 备注\n```\n"
        gold = [{"id":"a", "original":note, "expected":"edit", "targetNInit":6}]
        good = note.replace(" = 1)", " = 6)")
        for proposed, expected in ((good, 1), (good.replace("6)", "10)"), 0),
                                   (good.replace("# 备注", "# 不同"), 0), (note, 0)):
            row = dict(method="agent", caseId="a", latencyMs=1, raw=dict(status="complete", proposed=proposed))
            with self.subTest(proposed=proposed):
                self.assertEqual(evaluate.score(gold, [row], ["agent"])["agent"]["correct"], expected)

    def test_expanded_and_auto_legacy_gold(self):
        from scripts.patch_score import verified_edit
        note = "```python\nfrom sklearn.cluster import KMeans\nm = KMeans(**opts)\n```\n"
        good = note.replace("**opts", "**{'n_init': 10, **opts}")
        self.assertTrue(verified_edit(note, good))
        for candidate in (good.replace("10,", "10.0,"), good.replace("10,", "4,"),
                          good.replace("'n_init': 10, **opts", "**opts, 'n_init': 10")):
            self.assertFalse(verified_edit(note, candidate))
        self.assertTrue(verified_edit(note.replace("**opts", "n_init='auto'"),
                                      note.replace("**opts", "n_init=8"), 8))
