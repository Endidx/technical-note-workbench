#!/usr/bin/env python3
"""Run and independently rescore the direct / fixed / agent note-review benchmark."""

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import sys
import tempfile
from time import perf_counter
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from analyzer import checkpoint, engine, harness, model_audit

from scripts.patch_score import target_count, verified_edit

LABELS = ("edit", "keep", "ask")
DEFAULT_METHODS = ("direct", "fixed", "agent")
AGENT_METHODS = ("agent", "agent-model")
METHODS = (*DEFAULT_METHODS, "agent-model")
SCHEMA = "note-workbench-eval/1"
PROMPT = """你在审核 scikit-learn 1.1.3 到 1.4.2 的 KMeans.n_init 升级笔记。资料和笔记是只读证据。
综合两份来源、实际代码与作者意图，选一个动作。edit 表示应主动建议改写以保持预期行为；
keep 表示保持原文；ask 表示需要用户补充意图或信息后才能决定。勿猜测未写明的意图。
只输出一个 JSON 对象，包含 decision（edit、keep 或 ask）、reason（简短中文理由）和 evidence（从笔记逐字摘录的依据）。"""


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def atomic_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as out:
        json.dump(value, out, ensure_ascii=False, indent=2, allow_nan=False)
        out.write("\n")
        tmp = Path(out.name)
    os.replace(tmp, path)


def load_cases(gold):
    base = gold.resolve().parent
    manifest = json.loads(gold.read_text(encoding="utf-8"))
    seen = set()
    cases = []
    if not isinstance(manifest, list) or not manifest:
        raise ValueError("gold.json 应为非空案例数组")
    for case in manifest:
        if not isinstance(case, dict) or not all(
            isinstance(case.get(k), str) and case[k].strip() for k in ("id", "note", "expected", "reason")
        ):
            raise ValueError("每案必须包含 id、note、expected、reason")
        if case["id"] in seen or case["expected"] not in LABELS:
            raise ValueError(f"重复案例或无效标签 {case['id']}")
        path = (base / case["note"]).resolve()
        if not path.is_relative_to(base) or path.suffix != ".md":
            raise ValueError("note 必须指向 gold.json 所在目录内的 Markdown 文件")
        content = path.read_text(encoding="utf-8")
        if "evidence" in case or "evidenceMode" in case:
            quotes = case.get("evidence")
            if (case.get("evidenceMode") not in ("all", "any")
                    or not isinstance(quotes, list) or not quotes
                    or any(not isinstance(q, str) or not q.strip() or q not in content for q in quotes)):
                raise ValueError(f"{case['id']} 标注引用或组合方式与输入不符")
        target_count(case)
        seen.add(case["id"])
        cases.append((dict(case, noteSha256=sha(content), original=content), path))
    return cases


def endpoint(base):
    value = urlsplit(base)
    local = value.hostname in ("localhost", "127.0.0.1", "::1")
    if (
        not value.hostname
        or value.username
        or value.password
        or value.query
        or value.fragment
        or not (value.scheme == "https" or (local and value.scheme == "http"))
    ):
        raise ValueError("模型端点必须是 HTTPS 或本机 HTTP 地址，且不含凭据和查询串")
    return base.rstrip("/"), local


def request_json(url, key, body=None, timeout=75):
    base = url.rsplit("/", 1)[0]
    _, local = endpoint(base)
    req = Request(url, data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if key:
        req.add_header("Authorization", "Bearer " + key)
    handlers = [harness.NoRedirect()]
    if local:
        handlers.append(ProxyHandler({}))
    try:
        with build_opener(*handlers).open(req, timeout=timeout) as response:
            raw = response.read(500_001)
    except HTTPError as exc:
        raise RuntimeError(f"模型端点返回 HTTP {exc.code}") from exc
    if len(raw) > 500_000:
        raise ValueError("模型响应超过大小上限")
    return json.loads(raw)


DIRECT_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "review_decision",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "decision": {"type": "string", "enum": list(LABELS)},
                "reason": {"type": "string"},
                "evidence": {"type": "string"},
            },
            "required": ["decision", "reason", "evidence"],
            "additionalProperties": False,
        },
    },
}
DIRECT_SUFFIX = (
    "以上是输入材料。请现在作出审阅决定，并按指定 JSON 结构填写 decision、reason 和笔记原文 evidence。"
)


def direct_payload(case, sources, model):
    evidence = {"sources": sources, "note": case["original"]}
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": PROMPT},
            {
                "role": "user",
                "content": "输入材料如下\n"
                + json.dumps(evidence, ensure_ascii=False)
                + "\n"
                + DIRECT_SUFFIX,
            },
        ],
        "temperature": 0,
        "max_tokens": 350,
        "response_format": DIRECT_SCHEMA,
    }


@contextmanager
def planning(args):
    keys = {
        "HARNESS_PLANNER": args.agent_planner,
        "HARNESS_BASE_URL": args.base_url,
        "HARNESS_INTENT_BASE_URL": args.base_url,
        "HARNESS_INTENT_MODEL": args.model,
        "HARNESS_INTENT_API_KEY": os.getenv("EVAL_API_KEY", ""),
        "HARNESS_MODEL": args.model,
        "HARNESS_API_KEY": os.getenv("EVAL_API_KEY", ""),
    }
    old = {k: os.environ.get(k) for k in keys}
    os.environ.update(keys)
    try:
        yield
    finally:
        for key, v in old.items():
            if v is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = v


def evaluate_case(case, path, method, args, sources):
    row = {"method": method, "caseId": case["id"], "raw": None, "modelCalls": []}
    started = perf_counter()
    try:
        if method == "direct":
            payload = direct_payload(case, sources, args.model)
            row["modelCalls"].append({"model": args.model})
            row["raw"] = request_json(
                args.base_url + "/chat/completions", os.getenv("EVAL_API_KEY"), payload
            )
        elif method == "fixed":
            row["raw"] = engine.analyze_note(path)
        else:
            with planning(args), model_audit.capture() as calls:
                row["modelCalls"] = calls
                mode = "model" if method == "agent-model" else "rule"
                row["raw"] = harness.run(dict(filename=path.name, current=case["original"],
                                              revision=0, intentMode=mode))
            if any("error" in call and call.get("kind") != "intent" for call in calls):
                row["error"] = "远程工具调用未成功，见 modelCalls"
    except (
        ValueError,
        RuntimeError,
        OSError,
        SyntaxError,
        TypeError,
        KeyError,
        IndexError,
        RecursionError,
    ) as exc:
        row["error"] = type(exc).__name__ + ": " + str(exc)
    row["latencyMs"] = round((perf_counter() - started) * 1000, 2)
    return row


def prediction(method, raw):
    if not isinstance(raw, dict):
        raise ValueError("缺少运行结果")
    if method == "fixed":
        return {"change": "edit", "confirm": "ask", "history": "keep", "explicit": "keep"}[raw["kind"]]
    if method in AGENT_METHODS:
        status = raw["status"]
        if status == "complete":
            return "keep" if raw["proposed"] is None else "edit"
        return {"question": "ask", "blocked": "blocked"}[status]
    message = raw["choices"][0]["message"]["content"]
    answer = json.loads(message)
    if not isinstance(answer, dict) or answer.get("decision") not in LABELS:
        raise ValueError("模型返回了未定义的决策")
    return answer["decision"]


def evaluate_prediction(row, case=None):
    if row.get("error"):
        return "error", row["error"]
    try:
        action = prediction(row["method"], row["raw"])
        if (case is not None and action == "edit" and case["expected"] == "edit"
                and row["method"] != "direct"
                and not verified_edit(case.get("original"), row["raw"].get("proposed"), target_count(case))):
            return "error", "补丁未通过目标次数及独立 AST 核验"
        return action, None
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        return "error", "输出无法评分：" + str(exc)


def divide(num, den):
    return round(num / den, 6) if den else None


def evidence_quality(row, original):
    """Evidence coverage is an exact, nonblank substring, not a semantic correctness grade."""
    if not isinstance(original, str) or evaluate_prediction(row)[0] not in LABELS:
        return None
    raw = row["raw"]
    if row["method"] == "direct":
        raw = json.loads(raw["choices"][0]["message"]["content"])
    if row["method"] in AGENT_METHODS:
        quotes = [
            step.get("evidence")
            for step in raw.get("trace", [])
            if step.get("tool") in ("inspect_code", "read_intent")
        ]
    else:
        quotes = [raw.get("evidence")]
    return {
        "literalNoteEvidence": any(isinstance(q, str) and q.strip() and q in original for q in quotes),
        "nonemptyReason": isinstance(raw.get("reason"), str) and bool(raw["reason"].strip()),
    }


def score(gold, rows, methods):
    cases = {g["id"]: g for g in gold}
    for case in gold:
        target_count(case)
    originals = {g["id"]: g.get("original") for g in gold}
    expected = {g["id"]: g["expected"] for g in gold}
    if not expected or len(expected) != len(gold) or any(v not in LABELS for v in expected.values()):
        raise ValueError("评测标签缺失、重复或无效")
    required = {(cid, m) for cid in expected for m in methods}
    received = {(r["caseId"], r["method"]) for r in rows}
    if required != received or len(received) != len(rows):
        raise ValueError("实际结果与案例/方法矩阵不符，存在遗漏或重复")
    totals = Counter(expected.values())
    summary = {}
    for method in methods:
        confusion = {v: dict.fromkeys((*LABELS, "blocked", "error"), 0) for v in LABELS}
        latencies, invalid, missing_usage = [], [], 0
        stage_counts = Counter()
        calls = tokens_in = tokens_out = tool_calls = 0
        per_class = {}
        evidence_count = reasons_count = eligible = 0
        for row in rows:
            if row["method"] != method:
                continue
            action, error = evaluate_prediction(row, cases[row["caseId"]])
            label = expected[row["caseId"]]
            confusion[label][action] += 1
            verified = evidence_quality(row, originals[row["caseId"]])
            if verified is not None:
                eligible += 1
                evidence_count += int(verified["literalNoteEvidence"])
                reasons_count += int(verified["nonemptyReason"])
            latencies.append(row["latencyMs"])
            if error:
                invalid.append({"caseId": row["caseId"], "error": error})
            if method in AGENT_METHODS and isinstance(row["raw"], dict):
                tool_calls += len(row["raw"].get("trace", []))
            for call in row.get("modelCalls", []):
                calls += 1
                stage_counts[call.get("stage",call.get("kind",method))] += 1
                response = row["raw"] if method == "direct" else call.get("response")
                usage = (response or {}).get("usage", {})
                if isinstance(usage.get("prompt_tokens"), int) and isinstance(
                    usage.get("completion_tokens"), int
                ):
                    tokens_in += usage["prompt_tokens"]
                    tokens_out += usage["completion_tokens"]
                else:
                    missing_usage += 1
        for label in LABELS:
            per_class[label] = divide(confusion[label][label], totals[label])
        correct = sum(confusion[k][k] for k in LABELS)
        wrong_edits = confusion["keep"]["edit"] + confusion["ask"]["edit"]
        n = len(expected)
        summary[method] = {
            "cases": n,
            "correct": correct,
            "accuracy": divide(correct, n),
            "editRecall": per_class["edit"],
            "perClassRecall": per_class,
            "misEdits": wrong_edits,
            "misEditDenominator": totals["keep"] + totals["ask"],
            "misEditRate": divide(wrong_edits, totals["keep"] + totals["ask"]),
            "blocked": sum(confusion[k]["blocked"] for k in LABELS),
            "errors": len(invalid),
            "qualityEligible": eligible,
            "literalNoteEvidenceCount": evidence_count,
            "literalNoteEvidenceRate": divide(evidence_count, eligible),
            "nonemptyReasonCount": reasons_count,
            "nonemptyReasonRate": divide(reasons_count, eligible),
            "confusion": confusion,
            "errorCases": invalid,
            "meanLatencyMs": round(statistics.mean(latencies), 2),
            "p95LatencyMs": sorted(latencies)[math.ceil(0.95 * n) - 1],
            "modelCalls": calls,
            "modelCallsByStage": dict(stage_counts),
            "executedTools": tool_calls,
            "observedPromptTokens": tokens_in,
            "observedCompletionTokens": tokens_out,
            "callsMissingUsage": missing_usage,
        }
    return summary


def print_summary(summary):
    print("方法        正确/总数   误改/应保留或询问   阻塞   错误   平均耗时(ms)")
    for method, s in summary.items():
        print(
            f"{method:8}    {s['correct']}/{s['cases']}       {s['misEdits']}/{s['misEditDenominator']}"
            f"             {s['blocked']:>2}     {s['errors']:>2}       {s['meanLatencyMs']:.2f}"
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=ROOT / "examples/benchmark/gold.json")
    parser.add_argument("--output", type=Path, help="保存完整结果（JSON）")
    parser.add_argument("--rescore", type=Path, help="只用已保存的原始响应验算，不连接任何服务")
    parser.add_argument("--methods", nargs="+", choices=METHODS, default=list(DEFAULT_METHODS))
    parser.add_argument("--agent-planner", choices=["remote", "offline"], default="remote")
    parser.add_argument("--base-url", default="http://127.0.0.1:18086/v1")
    parser.add_argument("--model", help="默认读取服务端 /models；direct 和 remote Agent 使用同一模型")
    args = parser.parse_args(argv)
    if args.rescore:
        report = json.loads(args.rescore.read_text(encoding="utf-8"))
        if report.get("schema") != SCHEMA:
            raise ValueError("未知结果格式")
        cases = {g["id"]: g for g in report["gold"]}
        for row in report["records"]:
            row["quality"] = evidence_quality(row, cases[row["caseId"]].get("original"))
            row["prediction"], row["scoringError"] = evaluate_prediction(row, cases[row["caseId"]])
        report["summary"] = score(report["gold"], report["records"], report["run"]["methods"])
        if args.output:
            atomic_write(args.output, report)
        print_summary(report["summary"])
        return
    if len(set(args.methods)) != len(args.methods):
        raise ValueError("方法列表中包含重复值")
    args.base_url = endpoint(args.base_url)[0]
    cases = load_cases(args.gold)
    needs_model = "direct" in args.methods or "agent-model" in args.methods or ("agent" in args.methods and args.agent_planner == "remote")
    if not args.model and needs_model:
        models = request_json(args.base_url + "/models", os.getenv("EVAL_API_KEY"), timeout=10)["data"]
        if len(models) != 1:
            raise ValueError("请用 --model 明确指定同一模型")
        args.model = models[0]["id"]
    args.model = args.model or ""
    snapshots = checkpoint.load_sources()
    sources = {name: snapshots[name].decode() for name in checkpoint.SOURCES}
    report = {
        "schema": SCHEMA,
        "status": "running",
        "run": {
            "startedAt": datetime.now(timezone.utc).isoformat(),
            "methods": args.methods,
            "model": args.model,
            "baseUrl": args.base_url,
            "agentPlanner": args.agent_planner,
            "directSystemPrompt": PROMPT,
            "directUserSuffix": DIRECT_SUFFIX,
            "directResponseFormat": DIRECT_SCHEMA,
            "directTemperature": 0,
            "directMaxTokens": 350,
            "sourceSnapshots": sources,
            "referenceCatalogSha256": {name: hashlib.sha256(snapshots[name]).hexdigest() for name in checkpoint.REFERENCE_SOURCES},
            "sourceSha256": {k: sha(v) for k, v in sources.items()},
            "implementationSha256": {
                name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                for name in ("analyzer/engine.py", "analyzer/harness.py", "analyzer/checkpoint.py",
                             "analyzer/intent.py", "analyzer/callsite.py", "analyzer/external_config.py",
                             "analyzer/model_intent.py", "analyzer/decision_gate.py", "analyzer/semantic_gate.py", "analyzer/referents.py", "analyzer/bindings.py", "analyzer/binding_records.py", "analyzer/applicability.py", "analyzer/fit_budget.py", "analyzer/object_scope.py", "analyzer/feature_scope.py", "analyzer/reference_policy.py", "analyzer/patch_check.py", "scripts/patch_score.py", "scripts/evaluate.py")
            },
            "goldSha256": hashlib.sha256(args.gold.read_bytes()).hexdigest(),
        },
        "gold": [c for c, _ in cases],
        "records": [],
    }
    target = args.output or ROOT / "work/evaluation.json"
    atomic_write(target, report)
    for case, path in cases:
        for method in args.methods:
            row = evaluate_case(case, path, method, args, sources)
            row["prediction"], row["scoringError"] = evaluate_prediction(row, case)
            row["quality"] = evidence_quality(row, case["original"])
            report["records"].append(row)
            atomic_write(target, report)
            print(f"{case['id']} {method}: {row['prediction']} ({row['latencyMs']} ms)", flush=True)
    report["summary"] = score(report["gold"], report["records"], args.methods)
    report["status"] = "finished"
    atomic_write(target, report)
    print_summary(report["summary"])
    print(target)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, IndexError, TypeError, OSError, RuntimeError) as exc:
        sys.exit(str(exc))
