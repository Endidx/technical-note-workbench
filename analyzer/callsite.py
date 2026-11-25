"""Resolve a single statically imported sklearn constructor without executing note code."""
import ast

import io
import tokenize

from .external_config import span


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted(node.value)
        return f"{prefix}.{node.attr}" if prefix else None
    return None


def locate(code, *, tree=None):
    if tree is None:
        tree = ast.parse(code)
    # compile checks invalid argument lists and other syntax ast.parse accepts.
    compile(tree, "<note>", "exec")
    imports = {}
    for node in tree.body:
        if not isinstance(node, (ast.ImportFrom, ast.Import)) or getattr(node, "level", 0):
            continue
        for alias in node.names:
            if isinstance(node, ast.ImportFrom):
                full = f"{node.module}.{alias.name}"
            else:
                full = alias.name
            local = alias.asname or alias.name
            if full == "sklearn.cluster.KMeans":
                imports[local] = (alias, node.lineno)
            elif full == "sklearn.cluster":
                imports[local + ".KMeans"] = (alias, node.lineno)

    matches = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and dotted(n.func) in imports]
    if len(matches) != 1:
        raise ValueError("需要一个可静态定位且唯一的 sklearn.cluster.KMeans 调用")
    call = matches[0]
    target = dotted(call.func)
    imported, import_line = imports[target]
    root = target.split(".")[0]
    if import_line >= call.lineno or len(call.args) > 1 or any(isinstance(a, ast.Starred) for a in call.args):
        raise ValueError("无法确认调用前的参数或导入绑定")
    # A conservative scope check also catches parameters that shadow a module import.
    for n in ast.walk(tree):
        if isinstance(n, (ast.Name, ast.Attribute)) and isinstance(n.ctx, (ast.Store, ast.Del)):
            binding = dotted(n)
            if binding and (target == binding or target.startswith(binding + ".")):
                raise ValueError("KMeans 或其模块名在笔记中被重新绑定")
        if isinstance(n, ast.alias) and n is not imported:
            if n.name == "*" or (n.asname or n.name.split(".")[0]) == root:
                raise ValueError("其他导入可能覆盖 KMeans 绑定")
        if (isinstance(n, ast.arg) and n.arg == root or
                isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.ExceptHandler))
                and n.name == root or
                type(n).__name__ in ("MatchAs", "MatchStar", "MatchMapping")
                and root in (getattr(n, "name", None), getattr(n, "rest", None))):
            raise ValueError("局部名称可能覆盖 KMeans 绑定")
    return call


def insertion(original, block, call, count=10):
    # Insert before an existing keyword on its own line, preserving commas,
    # trailing comments, indentation and CRLF.
    if call.keywords:
        kw = call.keywords[0]
        lines = block['code'].splitlines(keepends=True)
        line = lines[kw.lineno - 1]
        prefix = line.encode()[:kw.col_offset].decode()
        if kw.lineno > call.lineno and not prefix.strip():
            start = block.start('code') + sum(map(len, lines[:kw.lineno - 1]))
            newline = '\r\n' if line.endswith('\r\n') else '\n'
            return start, prefix + f'n_init={count},' + newline
    code = block["code"]
    start, end = span(code, call)
    segment = code[start:end]
    tokens = [t for t in tokenize.generate_tokens(io.StringIO(segment).readline)
              if t.type not in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE,
                                tokenize.ENDMARKER, tokenize.INDENT, tokenize.DEDENT)]
    if not call.args and not call.keywords:
        return block.start("code") + end - 1, f"n_init={count}"
    # Insert directly after the final argument, before its optional comma/comment.
    last = tokens[-3] if tokens[-2].string == "," else tokens[-2]
    line, column = last.end
    offset = start + sum(map(len, segment.splitlines(keepends=True)[:line - 1])) + column
    return block.start("code") + offset, f", n_init={count}"
