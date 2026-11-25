"""Investigate the two supported sklearn changes against uploaded Markdown, offline."""
import ast
from dataclasses import dataclass, field
import re

from . import callsite, intent, library_text, reference_policy
from .engine import ROOT
from .external_config import span

TARGETS = {"sklearn.cluster.KMeans": "KMeans",
           "sklearn.preprocessing.OneHotEncoder": "OneHotEncoder"}
FIELDS = {"KMeans": "init 和 n_init", "OneHotEncoder": "sparse 和 sparse_output"}
FENCE = re.compile(
    r"^ {0,3}(?P<marker>`{3,}|~{3,})(?P<lang>[^\r\n]*)\r?\n"
    r"(?P<code>.*?)^ {0,3}(?P=marker)[`~]*[ \t]*\r?$", re.M | re.S)
RULES = {
    ("KMeans", "before"): r"\bn_init\b.{0,100}?(?:default(?:s to| value)?|默认(?:值)?(?:为)?)[^\w\n]*10\b|\bn_init\s*=\s*10\b",
    ("KMeans", "after"): r"(?:\bn_init\b.{0,100}?(?:default|默认|changed to|改为|变为|更改为).{0,28}?\bauto\b|\bn_init\s*=\s*['\x22]auto['\x22])",
    ("OneHotEncoder", "before"): r"\bsparse\s*(?:=|:|bool)|\bsparse\b.{0,10}(?:参数|控制|parameter)",
    ("OneHotEncoder", "after"): r"\bsparse_output\s*(?:=|:|bool)|(?:renamed|替换|更名|改名|重命名|改为).{0,45}\bsparse_output\b|\bsparse_output\b.{0,45}(?:renamed|替代|取代)",
}


def citations(source, target, side):
    """Keep physical line numbers and bind each parameter clause to its API."""
    rows = []
    for path, offset, lines in library_text.body_sections(source["content"]):
        local_heading = next((h for h in reversed(path) if re.search(
            r"KMeans|OneHotEncoder|\b[A-Z][a-z]+[A-Z]\w*", h)), "")
        target_pattern = rf"(?<![A-Za-z0-9_]){target}(?![A-Za-z0-9_])"
        local = bool(re.search(target_pattern, local_heading))
        for number, line in enumerate(lines, offset + 1):
            explicit = [name for name in FIELDS if name in line]
            if explicit:
                relevant = bool(re.search(target_pattern, line))
            else:
                relevant = local
            if relevant and not re.search(r"^\s*\[.*\]\(https?://", line):
                rows.append((number, line))
    pattern = RULES[target, side]
    matches = [(n, line) for n, line in rows if re.search(pattern, line, re.I)]
    if target == "OneHotEncoder" and side == "after":
        # A target signature that still accepts both names cannot prove removal.
        if any(re.search(r"\bOneHotEncoder\s*\(.*?\bsparse\s*=", line) for _, line in rows):
            return [], ""
    if not matches:
        return [], ""
    if target == "KMeans" and side == "after":
        matches.extend((n, line) for n, line in rows
                       if re.search(r"k-means\+\+|\brandom\b", line, re.I) and (n, line) not in matches)
    refs = [f"{source['filename']} · {source['version']} · L{n} · {line.strip()[:500]}"
            for n, line in matches[:6]]
    return refs, " ".join(line for _, line in matches).lower()


@dataclass
class Decision:
    status: str
    reason: str
    question: str = ""
    edit: tuple = ()


@dataclass
class Review:
    name: str
    note: str
    before: dict
    after: dict
    policy: intent.Finding
    evidence: list = field(default_factory=list)
    decisions: list = field(default_factory=list)
    sources: dict = field(default_factory=dict)


def ask(question):
    return Decision("ask", "需要补充证据才能决定这处调用如何迁移。", question)


def version_pair(before, after):
    def parts(source):
        match = re.fullmatch(r"v?(\d+)\.(\d+)(?:\.\d+)?", source["version"].strip(), re.I)
        return tuple(map(int, match.groups())) if match else ()
    return parts(before) == (1, 1) and parts(after) == (1, 4)


def count_edit(note, block, call, kwargs, count, reason):
    if "n_init" in kwargs:
        value = kwargs["n_init"].value
        if not isinstance(value, ast.Constant) or not (type(value.value) is int or value.value == "auto"):
            return ask(f"请核实 n_init={ast.get_source_segment(block['code'], value)} 的实际次数，目标是 {count} 次。")
        if value.value == count:
            return Decision("keep", f"KMeans 已设置要求的 {count} 次初始化。")
        start, end = span(block["code"], value)
        base = block.start("code")
        return Decision("edit", reason, edit=(base + start, base + end, str(count)))
    start, insertion = callsite.insertion(note, block, call, count)
    return Decision("edit", reason, edit=(start, start, insertion))


def reference_decision(review, reference, block, call, kwargs, new_clause):
    before, after = review.before, review.after
    snapshots = {"sklearn-1.1.md": before["content"].encode(), "sklearn-1.4.md": after["content"].encode()}
    if reference["reference"] == "1.0.2":
        snapshots["sklearn-1.0.2.json"] = (ROOT / "examples/sources/sklearn-1.0.2.json").read_bytes()
    facts = reference_policy.call_facts({key: kw.value for key, kw in kwargs.items()})
    resolved = reference_policy.resolve(reference, facts, snapshots,
                                        source_labels={"1.1.3": before["filename"], "1.4.2": after["filename"]})
    ref = resolved["reference"]
    review.evidence.extend(f"{review.name} · L{c['line']} · {c['quote']}" for c in resolved["citations"])
    if resolved.get("source"):
        review.evidence.append(f"{ref} · {resolved['source']}" +
                        (f" · {resolved['sourceDefaults']}" if "sourceDefaults" in resolved else ""))
    if resolved.get("question"):
        return ask(resolved["question"])
    init = facts["init"]
    if facts["n_init"] in ("auto", "absent") and not source_auto_count(init, new_clause):
        return ask(f"请补充新版资料中 init={init} 时 n_init='auto' 执行几次的条款，以核对 {ref}。")
    count = resolved["targetCount"]
    if count == resolved["currentCount"]:
        return Decision("keep", f"KMeans 的实际初始化次数与 {ref} 对应的 {count} 次一致。")
    return count_edit(review.note, block, call, kwargs, count, f"将 KMeans 的初始化次数调整为 {count}，与 {ref} 的要求一致。")


def source_auto_count(init, text):
    tokens = {"k-means++": (r"k-means\+\+", "1"), "random": (r"random", "10"),
              "callable": (r"callable|可调用", "10")}
    if init not in tokens:
        return False
    word, count = tokens[init]
    # Official passages describe one mode at a time, in either language.
    clauses = re.split(r"[。;；]|\band (?=\d)", text)
    return any(re.search(rf"(?:{word}).{{0,44}}?(?<!\d){count}(?!\d)|(?<!\d){count}(?!\d).{{0,40}}?(?:{word})", c)
               for c in clauses)


def owned_mapping(review, block, nodes, call, expansion):
    """Prove a literal is private to this one call, without evaluating its values."""
    if isinstance(expansion, ast.Dict):
        return expansion, ""
    code = block["code"]
    label = ast.get_source_segment(code, expansion)
    unresolved = (f"请确认 **{label} 实际传入的 sparse 和 sparse_output。"
                  "若配置只供这一处使用，请在同一 Python 代码块的调用前补上实际字典定义，"
                  "或在调用处写出准确参数。")
    if not isinstance(expansion, ast.Name):
        return None, unresolved
    name = expansion.id
    uses = [n for n in nodes if isinstance(n, ast.Name) and n.id == name]
    outside = any(re.search(rf"\b{re.escape(name)}\b", b["code"]) for b in FENCE.finditer(review.note)
                  if b.start() != block.start() and b["lang"].strip().lower() in ("py", "python", "python3"))
    if len(uses) > 2 or outside:
        return None, (f"{name} 还出现在其他位置，可能被共享或修改。请确认其他读写方是否也应迁移，"
                      f"并提供传给 OneHotEncoder 的 sparse 和 sparse_output。")
    if len(uses) != 2 or not any(isinstance(n.ctx, ast.Store) for n in uses):
        return None, unresolved
    # Only a straight-line definition immediately followed by its consumer proves order.
    # Checking the entire example also rules out aliases and later consumers.
    for scope in nodes:
        if not isinstance(scope, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for definition, use in zip(scope.body, scope.body[1:]):
            if isinstance(definition, ast.AnnAssign):
                target = definition.target
            elif isinstance(definition, ast.Assign) and len(definition.targets) == 1:
                target = definition.targets[0]
            else:
                continue
            if not (isinstance(target, ast.Name) and target.id == name and isinstance(definition.value, ast.Dict)
                    and isinstance(use, (ast.Assign, ast.AnnAssign, ast.Expr, ast.Return)) and use.value):
                continue
            consumer = list(ast.walk(use.value))
            if call not in consumer or any(isinstance(n, (ast.Lambda, ast.GeneratorExp)) for n in consumer):
                continue
            if (shadowed([n for n in nodes if n is not target], name, None, name)
                    or any(isinstance(n, (ast.Global, ast.Nonlocal)) and name in n.names for n in nodes)
                    or any(isinstance(n, ast.Name) and n.id in {"globals", "locals", "vars", "exec", "eval"}
                           for n in nodes)):
                return None, unresolved
            cite_code_line(review, block, definition)
            return definition.value, ""
    return None, unresolved


def cite_code_line(review, block, node):
    code_line = block["code"].splitlines()[node.lineno - 1].strip()
    physical = review.note.count("\n", 0, block.start("code")) + node.lineno
    review.evidence.append(f"{review.name} · L{physical} · {code_line[:500]}")


def encoder_config(review, block, nodes, call, kwargs):
    code = block["code"]
    expansions = [kw.value for kw in call.keywords if kw.arg is None]
    label = ", ".join(ast.get_source_segment(code, value) for value in expansions)
    if len(expansions) != 1:
        return ask(f"请分别核对 {label}，确定哪个映射提供 sparse 或 sparse_output，以及是否重名。")
    mapping, question = owned_mapping(review, block, nodes, call, expansions[0])
    if question:
        return ask(question)
    keys = {}
    for key in mapping.keys:
        if not isinstance(key, ast.Constant) or type(key.value) is not str:
            return ask(f"**{label} 含动态键或映射展开，请确认最终的 sparse 和 sparse_output。")
        if key.value in keys or key.value in kwargs:
            return ask(f"**{label} 或调用中重复提供了 {key.value}，请确认生效的值。")
        keys[key.value] = key
    all_names = keys.keys() | kwargs.keys()
    if {"sparse", "sparse_output"} <= all_names:
        return ask(f"OneHotEncoder 的调用和 **{label} 合计设置了 sparse 和 sparse_output，应保留哪个？")
    if "sparse" not in all_names:
        return Decision("keep", "已核对展开配置和显式参数，OneHotEncoder 没有使用旧关键字 sparse。")
    if "sparse" in keys:
        key = keys["sparse"]
        cite_code_line(review, block, key)
        start, end = span(code, key)
        literal = code[start:end]
        if not re.fullmatch(r"""(['"])sparse\1""", literal):
            return ask(f"**{label} 使用特殊字面量写法表示 sparse，请确认配置键如何改为 sparse_output。")
        start += 1  # Preserve the opening quote as well as the value expression.
    else:
        start = span(code, kwargs["sparse"])[0]
    start += block.start("code")
    return Decision("edit", "已核对本地展开配置，将 sparse 改为 sparse_output 并保留原值表达式。",
                    edit=(start, start + len("sparse"), "sparse_output"))


def inspect_call(review, target, block, nodes, call, new_clause):
    policy, note = review.policy, review.note
    code = block["code"]
    kwargs = {kw.arg: kw for kw in call.keywords}
    if policy.intent in ("history", "pinned"):
        return Decision("keep", "笔记将这段调用限定在旧版环境或历史记录中。")
    if any(isinstance(a, ast.Starred) for a in call.args) or len(call.args) > int(target == "KMeans"):
        return ask(f"请确认 {target} 的位置参数和实际传入的 {FIELDS[target]}。")
    if None in kwargs:
        if target == "OneHotEncoder":
            return encoder_config(review, block, nodes, call, kwargs)
        configs = ", ".join(ast.get_source_segment(code, k.value) for k in call.keywords if k.arg is None)
        return ask(f"请提供 {target} 实际展开的 {configs} 配置。它传入了哪些 {FIELDS[target]} 参数和值？")
    if target == "OneHotEncoder":
        if "sparse" not in kwargs:
            return Decision("keep", "OneHotEncoder 调用没有使用旧关键字 sparse。")
        if "sparse_output" in kwargs:
            return ask("OneHotEncoder 同时设置了 sparse 和 sparse_output。应保留哪个输出设置？")
        start = block.start("code") + span(code, kwargs["sparse"])[0]
        return Decision("edit", "将 OneHotEncoder 的 sparse 改为 sparse_output，保留原来的输出设置。",
                        edit=(start, start + len("sparse"), "sparse_output"))
    reference = reference_policy.policy(note)
    if reference:
        return reference_decision(review, reference, block, call, kwargs, new_clause)
    if "n_init" in kwargs and policy.intent == "old":
        return count_edit(note, block, call, kwargs, 10, "按笔记要求保留 KMeans 的 10 次初始化。")
    if "n_init" in kwargs and policy.intent == "default":
        return ask("笔记要求沿用新版默认，但代码显式设置了 n_init。请确认应保留该值还是采用 'auto'。")
    if "n_init" in kwargs:
        return Decision("keep", "KMeans 已显式设置 n_init，默认值变更不会覆盖它。")
    if policy.intent == "default":
        return Decision("keep", "笔记要求 KMeans 沿用新版默认值。")
    initializer = kwargs["init"].value if "init" in kwargs else ast.Constant("k-means++")
    if isinstance(initializer, ast.Constant) and initializer.value == "random":
        if source_auto_count("random", new_clause):
            return Decision("keep", "新版资料确认 random 初始化仍执行 10 次。")
        return ask("请补充新版资料中 init='random' 时 n_init='auto' 的实际运行次数。")
    if not isinstance(initializer, ast.Constant) or initializer.value != "k-means++":
        return ask(f"当前 init={ast.get_source_segment(code, initializer)} 实际使用哪类初始化器，要求运行几次？")
    if policy.intent != "old":
        return ask("升级后，这个 KMeans 调用要保留旧版的 10 次初始化，还是采用新版 n_init='auto'？")
    return count_edit(note, block, call, kwargs, 10, "依据笔记对初始化次数的要求，为 KMeans 显式保留 n_init=10。")


def import_paths(tree):
    """Only unconditional top-level imports provide evidence for an edit."""
    paths = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 0:
            for name in node.names:
                paths[name.asname or name.name] = (f"{node.module}.{name.name}", name, node.lineno)
        elif isinstance(node, ast.Import):
            for name in node.names:
                root = name.name.split(".")[0]
                paths[name.asname or root] = (name.name if name.asname else root, name, node.lineno)
    return paths


def shadowed(nodes, root, imported, full_local):
    for node in nodes:
        if isinstance(node, ast.alias) and node is not imported and (
                node.name == "*" or (node.asname or node.name.split(".")[0]) == root):
            return True
        if isinstance(node, (ast.Name, ast.Attribute)) and isinstance(node.ctx, (ast.Store, ast.Del)):
            binding = callsite.dotted(node)
            if binding and (binding == full_local or full_local.startswith(binding + ".")):
                return True
        if isinstance(node, ast.arg) and node.arg == root:
            return True
        if getattr(node, "name", None) == root and not isinstance(node, ast.alias):
            return True
    return False


def investigate_block(review, block, prose):
    name, note = review.name, review.note
    before, after = review.before, review.after
    evidence, decisions, sources = review.evidence, review.decisions, review.sources
    code = block["code"]
    first = note.count("\n", 0, block.start("code"))
    try:
        tree = ast.parse(code)
        compile(tree, "<note>", "exec")
    except (SyntaxError, ValueError, RecursionError):
        if any(target in code or target in prose for target in FIELDS):
            decisions.append(ask(f"请补充 {name} 第 {first + 1} 行开始的完整 Python 示例和调用参数。"))
        return
    paths, nodes = import_paths(tree), list(ast.walk(tree))
    candidates = []
    indirect = {}
    for assignment in (n for n in nodes if isinstance(n, ast.Assign)):
        rhs = callsite.dotted(assignment.value)
        if rhs in paths and paths[rhs][0] in TARGETS:
            for lhs in assignment.targets:
                if isinstance(lhs, ast.Name):
                    indirect[lhs.id] = TARGETS[paths[rhs][0]]
    for call in (node for node in nodes if isinstance(node, ast.Call)):
        raw = callsite.dotted(call.func) or ""
        root, dot, tail = raw.partition(".")
        path, imported, lineno = paths.get(root, (root, None, 0))
        target = TARGETS.get(path + dot + tail)
        if not target:
            names = [t for t in FIELDS if t in prose and
                     (raw and raw.split(".")[-1] in prose or any(kw.arg in (None, "sparse", "n_init") for kw in call.keywords))]
            if raw in indirect:
                names = [indirect[raw]]
            elif imported is None and raw.split(".")[-1] in FIELDS:
                names = [raw.split(".")[-1]]
            if raw and names:
                candidates.append((raw, ast.get_source_segment(code, call) or raw, first + call.lineno, names))
            continue
        snippet = ast.get_source_segment(code, call) or raw
        evidence.append(f"{name} · L{first + call.lineno} · {snippet[:500]}")
        if imported is None or lineno >= call.lineno or shadowed(nodes, root, imported, raw):
            decisions.append(ask(f"请确认 {raw} 的导入和绑定，并提供实际构造 {target} 的调用。"))
            continue
        if target not in sources:
            old_refs, _ = citations(before, target, "before")
            new_refs, new_clause = citations(after, target, "after")
            evidence.extend(old_refs + new_refs)
            sources[target] = (old_refs, new_refs, new_clause)
        old_refs, new_refs, new_clause = sources[target]
        if not version_pair(before, after) or not old_refs or not new_refs:
            decisions.append(ask(f"请核对版本范围，并补充两份资料中 {target} 的 {FIELDS[target]} 条款。"))
            continue
        decisions.append(inspect_call(review, target, block, nodes, call, new_clause))
    for raw, snippet, line, mentioned in candidates:
        params = "、".join(FIELDS[t] for t in mentioned)
        decisions.append(ask(f"请提供 {raw} 的实现或参数转发表，确认它如何向 {'、'.join(mentioned)} 传入 {params}。"))
        evidence.append(f"{name} · L{line} · {snippet[:500]}")


def investigate(name, note, before, after):
    review = Review(name, note, before, after, intent.infer(note))
    policy, decisions, evidence = review.policy, review.decisions, review.evidence
    prose = FENCE.sub("", note)
    for block in FENCE.finditer(note):
        if block["lang"].strip().lower() in ("python", "py", "python3"):
            investigate_block(review, block, prose)
    if not decisions and any(t in prose for t in FIELDS):
        names = [t for t in FIELDS if t in prose]
        decisions.append(ask(f"请提供 {'、'.join(names)} 的导入、实际构造调用和配置，便于核对版本影响。"))
    if policy.intent != "unknown" and decisions and policy.evidence:
        evidence.append(f"{name} · {policy.evidence[:500]}")
    trace = [d.reason if not d.question else d.question for d in decisions]
    questions = list(dict.fromkeys(d.question for d in decisions if d.question))
    edits = [d.edit for d in decisions if d.edit]
    proposed = None
    if questions:
        status, reason = "ask", "需要核对以下信息后才能确定整篇笔记的修改。"
    elif edits:
        status, reason, proposed = "edit", " ".join(dict.fromkeys(d.reason for d in decisions if d.edit)), note
        for start, end, value in sorted(edits, reverse=True):
            proposed = proposed[:start] + value + proposed[end:]
    elif decisions:
        status, reason = "keep", " ".join(dict.fromkeys(trace))
    else:
        status, reason = "irrelevant", "未发现涉及这两项 scikit-learn 变更的笔记内容。"
    result = dict(status=status, reason=reason, proposed=proposed, evidence=list(dict.fromkeys(evidence)),
                  trace=list(dict.fromkeys(trace)) or [reason])
    if questions:
        result["question"] = " ".join(questions)
    return result
