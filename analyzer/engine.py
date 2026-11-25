"""Offline impact review for the bundled scikit-learn 1.1 → 1.4 change."""
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTES = ROOT / "examples" / "notes"
PYTHON_BLOCK = re.compile(r"^```python[ \t]*\r?\n(?P<code>.*?)^```[ \t]*\r?$", re.MULTILINE | re.DOTALL)


def find_call(code):
    tree = ast.parse(code)
    names = {
        name.asname or name.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "sklearn.cluster"
        for name in node.names if name.name == "KMeans"
    }
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id in names]
    if len(calls) != 1 or any(arg.arg is None for arg in calls[0].keywords):
        raise ValueError("示例需要一个可静态识别的 KMeans 调用和明确的参数列表")
    return calls[0]


def call_insertion(original, block, call):
    # Python AST columns count UTF-8 bytes, not Unicode characters.
    lines = block["code"].splitlines(keepends=True)
    last_line = lines[call.end_lineno - 1]
    end_column = len(last_line.encode()[:call.end_col_offset].decode())
    offset = block.start("code") + sum(map(len, lines[:call.end_lineno - 1])) + end_column - 1
    if original[offset] != ")":
        raise ValueError("无法定位调用结束位置")
    before = original[:offset]
    insertion = "n_init=10" if before.rstrip().endswith(("(", ",")) else ", n_init=10"
    return offset, insertion


def patch_call(original, block, call):
    offset, insertion = call_insertion(original, block, call)
    return original[:offset] + insertion + original[offset:]


def analyze_note(path):
    original = path.read_text(encoding="utf-8")
    blocks = list(PYTHON_BLOCK.finditer(original))
    if len(blocks) != 1:
        raise ValueError(f"{path.name} 需要包含一个 Python 示例")
    block = blocks[0]
    call = find_call(block["code"])
    kwargs = {arg.arg: arg.value for arg in call.keywords}
    prose = (original[:block.start()] + original[block.end():]).splitlines()
    history = next((line for line in prose if line.startswith("历史记录：") and "1.1.3" in line), "")
    intent = next((line for line in prose if "仍需保留 10 次初始化" in line), "")
    snippet = ast.get_source_segment(block["code"], call)
    proposed = None

    if history:
        kind, evidence = "history", history
        reason = "这段文字记载的是 1.1.3 的既有实验，当时默认执行 10 次初始化。修改示例会改变历史记录。"
    elif "n_init" in kwargs:
        kind, evidence = "explicit", snippet
        reason = "调用已显式设置 n_init，本次默认值变更不会覆盖这个参数。"
    else:
        if "init" in kwargs:
            raise ValueError("首版省略次数的示例仅支持默认 k-means++ 初始化")
        proposed = patch_call(original, block, call)
        if intent:
            kind, evidence = "change", intent
            reason = "调用省略了 n_init 和 init。升级后默认从 10 次变为 1 次，与笔记要求保留 10 次的意图冲突。"
        else:
            kind, evidence = "confirm", snippet
            reason = "在 1.4 中，此调用默认只运行 1 次。笔记没有指定次数；请确认要保留旧版 10 次，还是沿用新版默认。"

    return dict(id=path.stem, title=original.splitlines()[0].removeprefix("# "),
                filename=path.name, original=original, proposed=proposed,
                kind=kind, reason=reason, evidence=evidence)


def analyze_all():
    return [analyze_note(path) for path in sorted(NOTES.glob("*.md"))]


if __name__ == "__main__":
    path = ROOT / "analysis.json"
    path.write_text(json.dumps(analyze_all(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
