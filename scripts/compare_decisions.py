#!/usr/bin/env python3
"""Compare two generations of Harness on identical examples, with the model and tool planner fixed."""
import argparse
import json
from pathlib import Path

from evaluate import evaluate_prediction, score

METHODS = ("agent", "agent-model")


GAPS = {"purpose": "migration_purpose", "priority": "requirement_owner"}


def grounded_question(raw, expected_gap, original):
    if raw.get("status") != "question" or raw.get("decisionGap") != expected_gap:
        return False
    choices = raw.get("questionChoices") or {}
    if (raw.get("proposed") is not None or not raw.get("question")
            or not all(isinstance(choices.get(k), str) and choices[k].strip() for k in ("old", "default"))
            or choices["old"] == choices["default"]):
        return False
    cites = raw.get("citations") or []
    lines = original.splitlines()
    return bool(cites) and all(
        type(c.get("line")) is int and 1 <= c["line"] <= len(lines)
        and isinstance(c.get("quote"), str) and c["quote"].strip() and c["quote"] in lines[c["line"] - 1]
        for c in cites
    )


def measure(report):
    rows = [r for r in report["records"] if r["method"] in METHODS]
    scores = score(report["gold"], rows, METHODS)
    cases = {c["id"]: c for c in report["gold"]}
    predictions = {(r["caseId"], r["method"]): evaluate_prediction(r, cases[r["caseId"]])[0] for r in rows}
    indexed = {(r["caseId"], r["method"]): r["raw"] or {} for r in rows}
    specific = [c for c in report["gold"] if c.get("requiredDecision") in GAPS and c["expected"] == "ask"]
    for mode, s in scores.items():
        s["specificCases"] = len(specific)
        s["specificQuestions"] = sum(grounded_question(indexed[c["id"], mode],
            GAPS[c["requiredDecision"]], c["original"]) for c in specific)
        matrix = s["confusion"]
        s["unnecessaryQuestions"] = matrix["edit"]["ask"] + matrix["keep"]["ask"]
        s["necessaryQuestions"] = matrix["ask"]["ask"]
        s["questions"] = s["unnecessaryQuestions"] + s["necessaryQuestions"]
    return scores, predictions


def compare(previous, current):
    if any(r["status"] != "finished" for r in (previous, current)):
        raise ValueError("需要两份完整评测记录")
    if previous["gold"] != current["gold"] or any(
        previous["run"][k] != current["run"][k]
        for k in ("sourceSha256", "model", "agentPlanner", "baseUrl", "goldSha256")
    ):
        raise ValueError("输入、标签、依据或运行配置不同，无法逐案对照")
    old_scores, old = measure(previous)
    new_scores, new = measure(current)
    print("案例\t参考\t旧规则→新规则\t旧模型→新模型")
    for c in current["gold"]:
        key = c["id"]
        print(key, c["expected"], *(f"{old[key, m]}→{new[key, m]}" for m in METHODS), sep="\t")
    print("版本\t模式\t正确\t应改命中\t误改\t追问\t多余追问\t必要追问命中\t具体用途或优先级追问\t阻塞/错误")
    for version, metrics in (("之前", old_scores), ("之后", new_scores)):
        for mode, s in metrics.items():
            specific = f"{s['specificQuestions']}/{s['specificCases']}" if s["specificCases"] else "—"
            print(version, mode, f"{s['correct']}/{s['cases']}", s["confusion"]["edit"]["edit"],
                  f"{s['misEdits']}/{s['misEditDenominator']}", s["questions"],
                  s["unnecessaryQuestions"], s["necessaryQuestions"], specific, f"{s['blocked']}/{s['errors']}", sep="\t")
    return old_scores, new_scores


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    args = parser.parse_args()
    compare(*(json.loads(p.read_text(encoding="utf-8")) for p in (args.before, args.after)))
