"""Paired evaluation of the actual question and the choices a reviewer can submit."""
import argparse
import json
from pathlib import Path
import re

from compare_decisions import METHODS, measure
from compare_agent import target_count, verified_edit

# Check the question visible to the user. Both generations use the same rubric.
FOCUS = {
    "artifact": r"包|交付物|归档|产物|文件|构建|制品|附件|交哪|提交哪",
    "deliverable": r"报告|文稿|图表|材料|资料|交付|文档|交哪|准备哪|做哪|输出|稿|简报|周报",
    "authority": r"谁|哪方|哪一方|哪边|哪[个位家组]|优先|为准|采纳|依据.*要求|听从",
}


def concrete(case, raw):
    if not raw or raw.get("status") != "question" or raw.get("proposed") is not None:
        return False
    # Candidate nouns quoted inside the choices cannot establish what the
    # question asks the reviewer to decide.
    question = raw.get("question") or ""
    focus = re.sub(r"「[^」]*」|《[^》]*》|“[^”]*”|`[^`]*`", "", question)
    pattern = FOCUS[case["requiredDecision"]]
    if case.get("targetType") == "physical":
        for target in case["targets"]:
            for alias in target["aliases"]:
                focus = focus.replace(alias, "")
        pattern = (r"哪(?:一)?[只台套件座辆]|哪(?:一)?个(?:实物|设备|对象|工位|箱|柜|终端)"
                   r"|(?:笔记|说明|使用卡|实物|设备|机台|套件|工位).{0,12}(?:给谁|归谁|属于谁|对应谁)"
                   r"|(?:属于|适用|随附|随哪|对应|配给|发给|用于|绑定|归属).{0,10}(?:哪个|哪种|哪款)")
    if not re.search(pattern, focus):
        return False
    choices = raw.get("questionChoices") or {}
    lines = case["original"].splitlines()
    quotes = []
    for cite in raw.get("citations") or []:
        line, quote = cite.get("line"), cite.get("quote")
        if type(line) is not int or not 1 <= line <= len(lines) or not quote or quote not in lines[line - 1]:
            return False
        quotes.append(quote)
    targets = {t["answer"]: t["aliases"] for t in case["targets"]}
    if set(targets) != {"old", "default"}:
        raise ValueError("每个目标问题需要标注两个互异选项")
    for key, aliases in targets.items():
        if not aliases or any(not alias or alias not in case["original"] for alias in aliases):
            raise ValueError(f"{case['id']} 候选对象标注缺少原文依据")
        label = choices.get(key) or ""
        other = choices.get("default" if key == "old" else "old") or ""
        if not any(a in label and a not in other and any(a in q for q in quotes) for a in aliases):
            return False
    return True


def choice_citations(raw, key):
    chain = (raw.get("choiceCitations") or {}).get(key)
    if chain is not None:
        return chain
    single = (raw.get("choiceEvidence") or {}).get(key)
    return [single] if single else []


def supported_choices(case, raw):
    """Verify each displayed subject and its policy against the same signed choice."""
    if not concrete(case, raw):
        return False
    lines = case["original"].splitlines()
    for target in case["targets"]:
        key = target["answer"]
        policy = target["policyAliases"]
        if not policy or any(not a or a not in case["original"] for a in policy):
            raise ValueError(f"{case['id']} 缺少原文中的策略标注")
        label = raw["questionChoices"][key]
        # Version 9 has one excerpt per button. Version 10 can cite separate
        # title and requirement lines under the same button.
        excerpts = []
        for c in choice_citations(raw, key):
            line, quote = c.get("line"), c.get("quote")
            if type(line) is not int or not 1 <= line <= len(lines) or not quote or quote not in lines[line - 1]:
                return False
            excerpts.append(quote)
        # A single passage shared by both choices does not establish which
        # policy belongs to which option. Accept a policy in the button or
        # in an excerpt belonging exclusively to this side.
        other_key = "default" if key == "old" else "old"
        shared = {x.get("quote") for x in choice_citations(raw, other_key)}
        if not any(a in label and any(a in q for q in excerpts) for a in target["aliases"]):
            return False
        if not any(any(a in q and (a in label or q not in shared) for q in excerpts) for a in policy):
            return False
    return True


def compare(before, after, versions=("8", "9")):
    if any(r["status"] != "finished" for r in (before, after)):
        raise ValueError("评测尚未完成")
    if before["gold"] != after["gold"] or any(before["run"][k] != after["run"][k]
            for k in ("sourceSha256", "model", "agentPlanner", "baseUrl", "goldSha256", "methods")):
        raise ValueError("配对数据或模型配置不一致")
    previous = {}
    for version, report in zip(versions, (before, after)):
        scores, predictions = measure(report)
        cases = {c["id"]: c for c in report["gold"]}
        for method in METHODS:
            target_ids = set()
            hits = set()
            direct_asked = set()
            binding_cases = set()
            supported = set()
            settled = {cid for cid, c in cases.items() if c.get("settled") is True}
            for row in report["records"]:
                if row["method"] != method:
                    continue
                cid = row["caseId"]
                c, raw = cases[cid], row["raw"]
                predicted = predictions[cid, method]
                if predicted == "edit" and not verified_edit(c["original"], raw["proposed"], target_count(c)):
                    raise ValueError(f"{cid} 补丁不合规")
                if c.get("requiredDecision") in FOCUS and c["expected"] == "ask":
                    target_ids.add(cid)
                    if concrete(c, raw):
                        hits.add(cid)
                    if all("policyAliases" in t for t in c["targets"]):
                        binding_cases.add(cid)
                        if supported_choices(c, raw):
                            supported.add(cid)
                if c["expected"] in ("edit", "keep") and predicted == "ask":
                    direct_asked.add(cid)
            s = scores[method]
            print(f"step{version} {method}  正确 {s['correct']}/{s['cases']}  "
                  f"具体追问 {len(hits)}/{len(target_ids)}  误改 {s['misEdits']}/{s['misEditDenominator']}  "
                  f"多余追问 {len(direct_asked)}  应改命中 {s['confusion']['edit']['edit']}  "
                  f"应问命中 {s['necessaryQuestions']}  阻塞/错误 {s['blocked']}/{s['errors']}")
            print("  具体追问命中", sorted(hits), "未命中", sorted(target_ids - hits))
            if binding_cases:
                for kind in ("authority", "deliverable", "artifact"):
                    subset = {cid for cid in binding_cases if cases[cid]["requiredDecision"] == kind}
                    if subset:
                        print(" ", kind, "具体追问", f"{len(hits & subset)}/{len(subset)}",
                              "对应引文", f"{len(supported & subset)}/{len(subset)}")
                print("  要求与对象对应", f"{len(supported)}/{len(binding_cases)}",
                      "命中", sorted(supported), "未命中", sorted(binding_cases - supported))
            if settled:
                settled_correct = sum(predictions[cid, method] == cases[cid]["expected"] for cid in settled)
                print("  已拍板案例", len(settled), "正确", settled_correct,
                      "追问", sorted(direct_asked & settled))
            direct_blocked = sorted(cid for cid, c in cases.items()
                                    if c["expected"] in ("edit", "keep") and predictions[cid, method] == "blocked")
            if direct_blocked:
                print("  可直接判定却被阻塞", direct_blocked)
            report_hits = {cid for cid in supported if cases[cid]["requiredDecision"] == "deliverable"}
            if version == versions[0]:
                previous[method] = (direct_asked, report_hits)
            else:
                previous_asks, previous_reports = previous[method]
                print("  可直接判定案例中新增追问", sorted(direct_asked - previous_asks),
                      "解除追问", sorted(previous_asks - direct_asked))
                print("  有对应原文的报告题名追问  保留", sorted(previous_reports & report_hits),
                      "新命中", sorted(report_hits - previous_reports),
                      "退步", sorted(previous_reports - report_hits))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--steps", nargs=2, default=("8", "9"), metavar=("BEFORE", "AFTER"))
    args = parser.parse_args()
    compare(*(json.loads(p.read_text(encoding="utf-8")) for p in (args.before, args.after)), versions=args.steps)
