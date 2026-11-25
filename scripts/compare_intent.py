#!/usr/bin/env python3
"""Audit the paired rule / contextual-intent run using raw predictions and exact note citations."""
import argparse
from collections import Counter
import json
from pathlib import Path

from compare_agent import target_count, verified_edit
from evaluate import evaluate_prediction, score


def evidence_check(case, step):
    lines = case["original"].splitlines()
    citations = step.get("citations", [])
    quotes = []
    for citation in citations:
        line = citation.get("line")
        quote = citation.get("quote")
        if (type(line) is not int or not 1 <= line <= len(lines) or
                not isinstance(quote, str) or not quote.strip() or quote not in lines[line - 1]):
            raise ValueError(f"{case['id']} 引文与原文行号不符")
        quotes.append(quote)
    if step.get("method") == "model":
        if not quotes:
            raise ValueError(f"{case['id']} 模型修改建议缺少可定位引文")
    elif not quotes and step.get("evidence"):
        quotes = [step["evidence"]]
    if not case.get("evidence"):
        return None
    # Gold is consulted solely by this offline verifier. Match each annotated
    # passage inside one actual cited passage, allowing a full sentence as a quote.
    hits = [any(text in q and q in case["original"] for q in quotes) for text in case["evidence"]]
    return all(hits) if case["evidenceMode"] == "all" else any(hits)


def compare(report):
    methods = ("agent", "agent-model")
    if report["status"] != "finished" or not set(methods).issubset(report["run"]["methods"]):
        raise ValueError("需要同一轮完整的两种意图模式记录")
    records = [r for r in report["records"] if r["method"] in methods]
    summary = score(report["gold"], records, methods)
    rows = {(r["caseId"], r["method"]): r for r in records}
    transitions = Counter()
    print("案例\t参考\t规则\t模型辅助\t修改依据覆盖\t补丁")
    for case in report["gold"]:
        a, b = (rows[case["id"], m] for m in methods)
        rule, model = (evaluate_prediction(r, case)[0] for r in (a, b))
        transitions[rule, model] += 1
        covered = patch = "—"
        for row in (a, b):
            raw = row["raw"] or {}
            if evaluate_prediction(row)[0] != "edit":
                continue
            if not verified_edit(case["original"], raw.get("proposed"), target_count(case)):
                raise ValueError(f"{case['id']} 候选补丁未通过独立 AST 校验")
            if row is b:
                step = next(s for s in raw["trace"] if s["tool"] == "read_intent")
                support = evidence_check(case, step)
                covered = {None:"无标注", True:"覆盖", False:"未覆盖"}[support]
                patch = "通过"
        print(case["id"], case["expected"], rule, model, covered, patch, sep="\t")
    for method in methods:
        s = summary[method]
        asks = sum(confusion["ask"] for confusion in s["confusion"].values())
        print(f"{method}: 正确 {s['correct']}/{s['cases']}，追问 {asks}，"
              f"多余追问 {asks - s['confusion']['ask']['ask']}，应追问命中 {s['confusion']['ask']['ask']}，误改 {s['misEdits']}/{s['misEditDenominator']}，"
              f"阻塞 {s['blocked']}，错误 {s['errors']}")
    print("规则追问转模型建议修改", transitions["ask", "edit"], "转保留", transitions["ask", "keep"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    compare(json.loads(args.report.read_text(encoding="utf-8")))
