"""Parse searchable Markdown passages, preserving physical source line numbers."""

import ast
from bisect import bisect_left
from collections import Counter
from difflib import SequenceMatcher
import hashlib
import math
import re

HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.+?)(?:\s+#+)?\s*$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
VERSION = re.compile(r"(?<![\w.])(?:v\d+(?:\.\d+){0,2}|\d+\.\d+(?:\.\d+)?)(?![\w.])", re.I)
STOP = set(
    "a an as at by and or in is if to it are of for from the that this was were be will has have been with only on uses use now previously default defaults changed version int null true false auto python py markdown md api import docs documentation release guide notes note examples example library overview migration updated 迁移 说明 默认 版本 现在 更新 变更 文档 接口 使用 参数 旧版 新版 支持 原来 代码 以及 成为 的是 这些 中的 一个 部分 进行 这个 情况 下的 为了".split()
)
WORDS = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[\u3400-\u9fff]+")
CONCEPTS = {
    "重试": ("retry", "retries", "重试", "再次尝试", "重新尝试"),
    "超时": ("timeout", "timeouts", "deadline", "超时", "等待时限"),
    "容量限制": ("capacity", "quota", "配额", "容量上限"),
    "聚类": ("kmeans", "k-means", "cluster", "clustering", "聚类", "分群"),
    "初始化": ("n_init", "seed", "initialization", "initialisation", "初始化", "随机种子"),
    "并发": ("concurrency", "concurrent", "parallel", "并发", "并行"),
    "编码": ("encoding", "charset", "字符集", "字符编码"),
    "分隔符": ("delimiter", "separator", "分隔符", "分隔字符"),
    "缓存": ("cache", "caching", "缓存", "快取"),
    "精度": ("precision", "rounding", "精度", "舍入"),
    "缺失值": ("nan", "missing value", "null value", "缺失值", "缺测值"),
    "身份认证": ("authentication", "credential", "身份认证", "凭据", "凭证"),
    "分页": ("pagination", "page_size", "分页", "每页条数"),
    "去重": ("deduplicate", "deduplication", "duplicates", "去重", "消除重复"),
}


def tokens(text):
    words = []
    for token in WORDS.findall(text.lower()):
        if token.isascii():
            words.append(token)
        else:
            words.extend(token[i : i + 2] for i in range(len(token) - 1))
    return [s for s in words if s not in STOP and len(s.strip("_")) >= 2]


def concepts(text):
    normalized = " ".join(text.lower().split())
    return [
        name
        for name, aliases in CONCEPTS.items()
        if any(
            re.search(r"(?<![a-z0-9_])" + re.escape(a) + r"(?![a-z0-9_])", normalized)
            if a.isascii()
            else a in normalized
            for a in aliases
        )
    ]


def features(text):
    terms = {word: 1 + math.log(n) for word, n in Counter(tokens(text)).items()}
    for concept in concepts(text):
        terms["概念·" + concept] = 4.0
    return terms


def body_sections(content):
    lines = content.splitlines()
    stack, groups, fence = [], [], None
    start = 0
    for i, line in enumerate(lines):
        marker = FENCE.match(line)
        if marker:
            delim, tail = marker.groups()
            if fence is None:
                fence = delim
            elif delim[0] == fence[0] and len(delim) >= len(fence) and not tail.strip():
                fence = None
            continue
        heading = HEADING.match(line) if fence is None else None
        if heading:
            if i > start or stack:
                groups.append((tuple(s[1] for s in stack), start, lines[start:i]))
            level, label = len(heading[1]), heading[2].strip()
            stack = [s for s in stack if s[0] < level] + [(level, label)]
            start = i + 1
    if start < len(lines) or stack:
        groups.append((tuple(s[1] for s in stack), start, lines[start:]))
    return groups


def chunks(content):
    result = []
    source_lines = content.splitlines()
    groups = body_sections(content)
    for group_id, (path, offset, lines) in enumerate(groups):
        if not any(line.strip() for line in lines):
            following = groups[group_id + 1][0] if group_id + 1 < len(groups) else ()
            if path and not (following[: len(path)] == path and len(following) > len(path)):
                result.append(
                    dict(
                        heading=" › ".join(path),
                        startLine=offset,
                        endLine=offset,
                        text=source_lines[offset - 1],
                    )
                )
            continue
        # Keep physical line references even when a source contains one long line.
        pieces = [
            (offset + i + 1, line[j : j + 2000])
            for i, line in enumerate(lines)
            for j in range(0, max(1, len(line)), 2000)
        ]
        start = 0
        while start < len(pieces):
            if not pieces[start][1].strip():
                start += 1
                continue
            end = start
            size = 0
            while end < len(pieces) and end - start < 36:
                length = len(pieces[end][1]) + int(end > start)
                if size + length > 2400:
                    break
                size += length
                end += 1
            if end < len(pieces):
                blanks = [i for i in range(start + 8, end) if not pieces[i][1].strip()]
                if blanks:
                    end = blanks[-1]
            last = end
            while last > start and not pieces[last - 1][1].strip():
                last -= 1
            result.append(
                dict(
                    heading=" › ".join(path),
                    startLine=pieces[start][0],
                    endLine=pieces[last - 1][0],
                    text="\n".join(val for _, val in pieces[start:last]),
                )
            )
            start = end
    return result


def source_sections(content):
    sections, occurrences = {}, Counter()
    groups = body_sections(content)
    roots = {path[0] for path, _, _ in groups if path}
    for i, (path, _, lines) in enumerate(groups):
        body = "\n".join(l.rstrip() for l in lines).strip()
        descendant_follows = (
            i + 1 < len(groups)
            and groups[i + 1][0][: len(path)] == path
            and len(groups[i + 1][0]) > len(path)
        )
        if not body and (not path or descendant_follows):
            continue
        label = " › ".join(path)
        key = [p.strip().casefold() for p in path]
        if key and len(roots) == 1:
            key[0] = VERSION.sub("", key[0]).strip()
        key = tuple(key)
        occurrences[key] += 1
        sections[(key, occurrences[key])] = (label, body)
    return sections


def changes(before, after):
    old, new = source_sections(before), source_sections(after)
    changeset = []
    for key in dict.fromkeys([*new, *old]):
        heading, new_text = new.get(key, ("", ""))
        old_heading, old_text = old.get(key, ("", ""))
        # Empty leaf headings are still meaningful when added or removed.
        if key not in new and not old_text:
            old_text = "# " + old_heading
        if key not in old and not new_text:
            new_text = "# " + heading
        old_lines, new_lines = old_text.splitlines(), new_text.splitlines()
        if old_lines == new_lines:
            continue
        # One line of unchanged context keeps the changed clause intelligible,
        # while separating distant changes under the same heading.
        matcher = SequenceMatcher(None, old_lines, new_lines, autojunk=len(old_lines) > 200)
        for group in matcher.get_grouped_opcodes(1):
            i1, i2, j1, j2 = group[0][1], group[-1][2], group[0][3], group[-1][4]
            left, right = "\n".join(old_lines[i1:i2]).strip(), "\n".join(new_lines[j1:j2]).strip()
            if left == right:
                continue
            signature = repr((key, i1, j1, left, right)).encode()
            changeset.append(
                dict(
                    id=hashlib.sha256(signature).hexdigest()[:20],
                    heading=heading or old_heading,
                    before=left,
                    after=right,
                )
            )
    return changeset


def ast_evidence(text):
    """Locate static call evidence in full fences, even when chunk boundaries split them."""
    evidence = []
    newlines = [i for i, c in enumerate(text) if c == "\n"]
    pattern = r"^ {0,3}```(?:python|py)[ \t]*\n(.*?)^ {0,3}```[ \t]*$"
    for match in re.finditer(pattern, text, re.M | re.S | re.I):
        snippet = match[1]
        line_offset = bisect_left(newlines, match.start(1))
        try:
            tree = ast.parse(snippet)
        except (ValueError, SyntaxError, RecursionError):
            continue
        aliases = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for name in node.names:
                    aliases[name.asname or name.name] = (node.module or "") + "." + name.name
            if isinstance(node, ast.Import):
                for name in node.names:
                    aliases[name.asname or name.name.split(".")[0]] = (
                        name.name if name.asname else name.name.split(".")[0]
                    )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            target = node.func
            parts = []
            while isinstance(target, ast.Attribute):
                parts.insert(0, target.attr)
                target = target.value
            if isinstance(target, ast.Name):
                resolved = ".".join([aliases.get(target.id, target.id), *parts])
                evidence.append(
                    (line_offset + node.lineno, resolved, [arg.arg for arg in node.keywords if arg.arg])
                )
    return evidence
