#!/usr/bin/env python3
"""Compare first-pass Agent judgments on the same inputs, and check proposed edits."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.patch_score import target_count, verified_edit
from evaluate import evaluate_prediction


def compare(before, after):
    if before['status'] != 'finished' or after['status'] != 'finished':
        raise ValueError("需要两份完整运行记录")
    if before['gold'] != after['gold'] or any(before['run'][k] != after['run'][k]
            for k in ('model', 'sourceSha256', 'agentPlanner')):
        raise ValueError("两次运行使用的笔记、标注、版本资料或模型设置不同")
    def index(report):
        rows = [r for r in report['records'] if r['method'] == 'agent']
        by_id = {r['caseId']: r for r in rows}
        if len(rows) != len(by_id) or by_id.keys() != {c['id'] for c in report['gold']}:
            raise ValueError("Agent 记录缺失或重复")
        return by_id
    old, new = index(before), index(after)
    print("案例\t参考\t旧 Agent\t新 Agent\t修改检查")
    for c in after['gold']:
        case = c['id']
        first = evaluate_prediction(old[case], c)[0]
        last = evaluate_prediction(new[case])[0]
        verified = verified_edit(c['original'], new[case]['raw']['proposed'], target_count(c)) if last == 'edit' else None
        print(case, c['expected'], first, last, {True:'通过', False:'失败', None:'—'}[verified], sep='\t')
        if verified is False:
            raise ValueError(f"{case} 的修改超出目标参数或无法解析")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    args = parser.parse_args()
    compare(*(json.loads(p.read_text(encoding='utf-8')) for p in (args.before, args.after)))
