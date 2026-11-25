import json
import unittest
from unittest.mock import patch

from analyzer.harness import events, run
from analyzer.test_harness import request


def durable(step):
    # Match the JSON boundary between Python and the persistence owner.
    return json.loads(json.dumps(step["checkpoint"], ensure_ascii=False))


class CheckpointTests(unittest.TestCase):
    def test_resume_reader_round_keeps_prior_trace_without_reexecution(self):
        payload = request("01")
        expected = run(payload)
        stream = events(payload)
        checkpoint = durable(next(stream))
        stream.close()
        with patch("analyzer.harness.inspect_code", side_effect=AssertionError("duplicate inspection")):
            resumed = list(events(dict(payload, checkpoint=checkpoint)))
        self.assertEqual([e["step"] for e in resumed[:-1]], expected["trace"][1:])
        self.assertEqual(resumed[-1]["result"], expected)

    def test_crash_after_final_step_restores_complete_question_and_blocked(self):
        for payload in (request("01"), request("04"), dict(request("01"), current="unsupported")):
            original = list(events(payload))
            saved = durable(original[-2])
            with patch("analyzer.harness.next_tools", side_effect=AssertionError("duplicate decision")):
                self.assertEqual(list(events(dict(payload, checkpoint=saved))), [original[-1]])

    def test_changed_inputs_and_tamper_rejected_before_tools(self):
        payload = request("04")
        saved = durable(next(events(payload)))
        for changed in (dict(revision=4), dict(answer="old"), dict(current=payload["current"] + " "),
                        dict(filename="changed.md")):
            result = run(dict(payload, checkpoint=saved, **changed))
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["trace"], [])
        saved["trace"][0]["evidence"] = "changed"
        self.assertEqual(run(dict(payload, checkpoint=saved))["status"], "blocked")

    def test_changed_source_version_schema_or_planner_cannot_resume(self):
        from analyzer import checkpoint
        payload = request("01")
        saved = durable(next(events(payload)))
        new_sources = checkpoint.load_sources()
        new_sources["sklearn-1.4.md"] += b"\n"
        changes = [
            patch("analyzer.checkpoint.load_sources", return_value=new_sources),
            patch("analyzer.checkpoint.SCHEMA", "updated-tool-contract"),
            patch.dict("os.environ", {"HARNESS_PLANNER": "remote"}),
        ]
        for change in changes:
            with change:
                result = run(dict(payload, checkpoint=saved))
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["trace"], [])

    @patch("analyzer.harness.MAX_STEPS", 2)
    def test_reader_checkpoint_retains_consumed_budget(self):
        payload = request("01")
        saved = durable(next(events(payload)))
        resumed = list(events(dict(payload, checkpoint=saved)))
        self.assertEqual(len(resumed), 2)
        final = resumed[-1]["result"]
        self.assertEqual(final["status"], "blocked")
        self.assertEqual(len(final["trace"]), 2)
        self.assertEqual(list(events(dict(payload, checkpoint=durable(resumed[0])))), [resumed[-1]])

    def test_cli_resume_in_another_process(self):
        import subprocess
        import sys
        cmd = [sys.executable, "-m", "analyzer.harness", "--stream"]
        payload = request("01")
        with subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as worker:
            worker.stdin.write(json.dumps(payload))
            worker.stdin.close()
            first = json.loads(worker.stdout.readline())
            worker.kill()
        resumed_run = subprocess.run(cmd, input=json.dumps(dict(payload, checkpoint=durable(first))),
                                     text=True, capture_output=True, check=True)
        resumed = [json.loads(line) for line in resumed_run.stdout.splitlines()]
        result = resumed[-1]["result"]
        self.assertEqual(result, run(payload))
        self.assertEqual([e["step"] for e in resumed[:-1]], result["trace"][1:])
