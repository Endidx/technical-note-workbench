"""Verify the decision and evidence attached to each proposed initialization-count patch."""
import argparse
from collections import Counter
import json
from pathlib import Path

from compare_agent import target_count, verified_edit
from evaluate import evaluate_prediction


def audit(report):
    if report.get("status") != "finished":
        raise ValueError("需要完整评测记录")
    cases = {c["id"]: c for c in report["gold"]}
    counts = Counter()
    for record in report["records"]:
        decision, _ = evaluate_prediction(record)
        if decision != "edit":
            continue
        cid, method = record["caseId"], record["method"]
        raw = record["raw"]
        note = cases[cid]["original"]
        steps = [s for s in raw["trace"] if s["tool"] == "read_intent"]
        check = steps[0].get("applicability", {}) if len(steps) == 1 else {}
        if check.get("outcome") != "allow" or not check.get("reason"):
            raise ValueError(f"{cid}/{method} 补丁缺少放行理由")
        if type(check.get("modelCalled")) is not bool or not check.get("route"):
            raise ValueError(f"{cid}/{method} 缺少核实路径或调用标志")
        # This benchmark scores the first action on each unmodified note.
        # A recorded user override would be evidence of a contaminated run.
        if check["route"] == "user_answer":
            raise ValueError(f"{cid}/{method} 首次决策使用了用户回答")
        lines = note.splitlines()
        citations = check.get("citations") or []
        if not citations:
            raise ValueError(f"{cid}/{method} 自动放行缺少笔记引文")
        for cite in citations:
            line, quote = cite.get("line"), cite.get("quote")
            if type(line) is not int or not 1 <= line <= len(lines) or not isinstance(quote, str) or not quote.strip() or quote not in lines[line - 1]:
                raise ValueError(f"{cid}/{method} 引文行号或原文有误")
        target = target_count(cases[cid])
        step = steps[0]
        if step.get("method") == "reference" or "referenceEvidence" in step:
            observed = (step.get("referenceEvidence") or {}).get("targetCount")
            if type(observed) is not int or observed != target:
                raise ValueError(f"{cid}/{method} 参照证据中的目标次数与标注不符")
        if not verified_edit(note, raw.get("proposed"), target):
            raise ValueError(f"{cid}/{method} 补丁没有通过独立 AST 检查")
        counts[method, check["route"]] += 1
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    counts = audit(json.loads(args.report.read_text(encoding="utf-8")))
    print("通过放行依据和 AST 核验的首次补丁", sum(counts.values()))
    for (method, route), total in sorted(counts.items()):
        print(method, route, total, sep="\t")
