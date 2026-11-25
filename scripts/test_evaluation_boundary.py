"""Isolate benchmark annotations from first-turn review and semantic requests."""
from argparse import Namespace
import io
import json
import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from analyzer import model_intent
from scripts import evaluate


NOTE = """# 单页练习
样本卡片记为 N7041。

```python
from sklearn.cluster import KMeans
estimator = KMeans(n_clusters=3)
```
"""
ARGS = Namespace(agent_planner="offline", base_url="http://127.0.0.1:18086/v1", model="mock")
CASES = [
    (dict(id="id-alpha", original=NOTE, expected="edit", reason="reason-alpha",
          evidence=["样本卡片记为 N7041。"], evidenceMode="all"), Path("first-marker.md")),
    (dict(id="id-beta", original=NOTE, expected="keep", reason="reason-beta",
          evidence=["单页练习"], evidenceMode="any"), Path("second-marker.md")),
]


class EvaluationBoundaryTests(TestCase):
    def test_agent_first_turn_and_semantic_wire(self):
        reply = dict(decision="需要补充条件", evidence_ids=[1], reason="没有说明次数")
        envelope = {"choices": [{"message": {"content": json.dumps(reply)}}]}
        response = json.dumps(envelope).encode()
        payloads, actions = [], []
        for case, path in CASES:
            with patch.dict(os.environ, HARNESS_CHECKPOINT_KEY="t" * 32), \
                    patch.object(model_intent, "build_opener") as opener, \
                    patch.object(evaluate.harness, "run", wraps=evaluate.harness.run) as harness:
                transport = opener.return_value.open
                transport.side_effect = lambda *args, **kwargs: io.BytesIO(response)
                row = evaluate.evaluate_case(case, path, "agent-model", ARGS, {})
            harness.assert_called_once_with(dict(current=NOTE, filename=path.name,
                                                 revision=0, intentMode="model"))
            self.assertNotIn("error", row)
            self.assertEqual([call["stage"] for call in row["modelCalls"]], ["initial"])
            transport.assert_called_once()
            payload = json.loads(transport.call_args.args[0].data)
            self.assertIn("N7041", payload["messages"][-1]["content"])
            self.assertNotIn(path.name, str(payload))
            self.assertNotIn(case["id"], str(payload))
            self.assertNotIn(case["reason"], str(payload))
            payloads.append(payload)
            actions.append(evaluate.prediction("agent-model", row["raw"]))
        self.assertEqual(payloads[0], payloads[1])
        self.assertEqual(actions, ["ask", "ask"])

    def test_direct_wire_uses_only_note_and_sources(self):
        sources = {"source": "snapshot marker"}
        requests = []
        for case, path in CASES:
            with patch.object(evaluate, "request_json") as post:
                evaluate.evaluate_case(case, path, "direct", ARGS, sources)
            post.assert_called_once()
            payload = post.call_args.args[2]
            contents = payload["messages"][-1]["content"]
            material = contents.removeprefix("输入材料如下\n").removesuffix("\n" + evaluate.DIRECT_SUFFIX)
            self.assertEqual(json.loads(material), {"sources": sources, "note": NOTE})
            requests.append(payload)
        self.assertEqual(requests[0], requests[1])
