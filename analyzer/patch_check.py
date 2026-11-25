"""Construct a localized count edit and verify its syntax and source boundaries."""
import ast
import re

from . import callsite, external_config
from .engine import PYTHON_BLOCK


def _block(note):
    blocks = list(PYTHON_BLOCK.finditer(note))
    if len(blocks) != 1:
        raise ValueError("需要唯一的 Python 代码块")
    return blocks[0]


def _positive(value):
    return type(value) is int and value > 0


def _direct(call):
    if any(kw.arg is None for kw in call.keywords):
        raise ValueError("无法直接修改带 ** 映射的调用")
    param = next((kw for kw in call.keywords if kw.arg == "n_init"), None)
    if param and not (isinstance(param.value, ast.Constant)
                      and (_positive(param.value.value) or param.value.value == "auto")):
        raise ValueError("原 n_init 须为正整数或 auto 字面值")
    return param


def propose_count(original, count):
    if not _positive(count):
        raise ValueError("目标 n_init 必须是正整数")
    block = _block(original)
    call = callsite.locate(block["code"])
    param = _direct(call)
    if param:
        start, end = external_config.span(block["code"], param.value)
        base = block.start("code")
        proposed = original[:base + start] + str(count) + original[base + end:]
    else:
        offset, added = callsite.insertion(original, block, call, count)
        proposed = original[:offset] + added + original[offset:]
    verify(original, proposed, expanded=False, count=count)
    return proposed


def _insertion_only(old, new, param):
    start, end = external_config.span(new, param)
    delta = len(new) - len(old)
    # The added keyword and its separator must form a single insertion.
    left = next((i for i, (a, b) in enumerate(zip(old, new)) if a != b), len(old))
    pos = min(left, start)
    padding = new[pos:start] + new[end:pos + delta]
    return (delta > 0 and pos + delta >= end and old[pos:] == new[pos + delta:]
            and re.fullmatch(r"[\s,]*", padding) and "#" not in new[start:end])


def verify(original, proposed, *, expanded, count=10):
    if not _positive(count):
        raise ValueError("目标 n_init 必须是正整数")
    a, b = _block(original), _block(proposed)
    if original[:a.start("code")] != proposed[:b.start("code")] or original[a.end("code"):] != proposed[b.end("code"):]:
        raise ValueError("候选修改改变了代码块外的笔记原文")
    old, new = a["code"], b["code"]
    before = callsite.locate(old)
    tree = ast.parse(new)
    after = callsite.locate(new, tree=tree)
    if expanded:
        if count != 10 or not external_config.verifies(before, after):
            raise ValueError("候选修改未能保留原映射的覆盖优先级")
        unpack = next(kw for kw in after.keywords if kw.arg is None)
        old_kw = next(kw for kw in before.keywords if kw.arg is None)
        start, end = external_config.span(old, old_kw)
        if new != external_config.patch(old, (start, end)):
            raise ValueError("候选修改改变了映射之外的原文")
        unpack.value = unpack.value.values[1]
    else:
        initial, changed = _direct(before), _direct(after)
        if not changed or changed.value.value != count:
            raise ValueError(f"候选修改未在目标调用中指定 n_init={count}")
        if initial:
            a0, a1 = external_config.span(old, initial.value)
            b0, b1 = external_config.span(new, changed.value)
            if (initial.value.value == count or "#" in old[a0:a1]
                    or old[:a0] != new[:b0] or old[a1:] != new[b1:]):
                raise ValueError("候选修改须仅替换不一致的 n_init 字面值")
            changed.value = initial.value
        else:
            if not _insertion_only(old, new, changed):
                raise ValueError("候选修改改变了新增关键字之外的原文")
            after.keywords.remove(changed)
    if ast.dump(tree) != ast.dump(ast.parse(old)):
        raise ValueError("候选修改改变了目标参数之外的代码")
