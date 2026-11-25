"""Validate user-attested KMeans kwargs and edit the call without executing a note."""
import ast

INIT_VALUES = ("absent", "k-means++", "random", "callable", "array-like", "unknown")
N_INIT_VALUES = ("absent", "auto", "unknown")


def validate(facts):
    if facts is None:
        return
    if not isinstance(facts, dict) or set(facts) != {"mapping", "init", "n_init"}:
        raise ValueError("外部配置须提供映射表达式、init 和 n_init 三项")
    name = facts["mapping"]
    if not isinstance(name, str) or not name.strip() or len(name.encode()) > 2000:
        raise ValueError("映射表达式须为问题中给出的表达式")
    if facts["init"] not in INIT_VALUES:
        raise ValueError("init 应为支持的初始化方式、absent 或 unknown")
    count = facts["n_init"]
    if not (type(count) is int and 1 <= count <= 2_147_483_647) and count not in N_INIT_VALUES:
        raise ValueError("n_init 应为正整数、auto、absent 或 unknown")


def question(mapping, fields):
    names = " 和 ".join(fields)
    return f"请核对实际展开的 **{mapping}：尚需确认 {names}。该映射是否提供这些参数？请填写实际值、未提供或尚不清楚。"


def describe(facts):
    return f"用户核对 **{facts['mapping']}：init={facts['init']}，n_init={facts['n_init']}。"


def span(code, node):
    """AST uses UTF-8 byte columns; patch Markdown using character offsets."""
    lines = code.splitlines(keepends=True)
    def offset(line, column):
        return sum(map(len, lines[:line - 1])) + len(lines[line - 1].encode()[:column].decode())
    return offset(node.lineno, node.col_offset), offset(node.end_lineno, node.end_col_offset)


def resolve(state, block, call, kwargs):
    expanded = [arg for arg in call.keywords if arg.arg is None]
    facts = state["input"].get("configFacts")
    if not expanded:
        if facts is not None:
            raise ValueError("当前调用没有该外部映射")
        return ""
    if len(expanded) != 1:
        raise ValueError("发现多个 ** 映射，无法确定同名参数来自哪一个。请先核对各配置，在当前 Markdown 中将示例改为一份明确的合并配置或写出实际参数，保存后重新调查")
    keyword = expanded[0]
    name = ast.get_source_segment(block["code"], keyword.value)
    if not name or len(name.encode()) > 2000:
        raise ValueError("展开表达式过长，无法可靠标注，请先拆成命名变量")
    state["mapping"] = name
    if facts and facts["mapping"] != name:
        raise ValueError("回答中的映射表达式与当前调用不一致")
    known = facts or {"init": "unknown", "n_init": "unknown"}
    direct = set(kwargs)
    required = set()
    for key in ("init", "n_init"):
        value = known[key]
        if key in direct:
            if value == "unknown":
                required.add(key)  # A duplicate is still possible.
            elif value != "absent":
                raise ValueError(f"{key} 同时由显式参数与 **{name} 提供，可能产生重复关键字。请先解决调用冲突")
        elif value not in ("absent", "unknown"):
            kwargs[key] = ast.Constant(value)

    if "n_init" not in kwargs:
        initializer = kwargs.get("init")
        random_init = isinstance(initializer, ast.Constant) and initializer.value == "random"
        stable_default = random_init or known["init"] == "callable"
        if known["n_init"] == "unknown":
            if stable_default:
                state["stable_unknown_count"] = True
            else:
                required.add("n_init")
        if known["init"] == "unknown" and "init" not in direct:
            required.add("init")

    if required:
        state["mode"] = "external"
        state["required_fields"] = sorted(required)
        return question(name, state["required_fields"])
    start, end = span(block["code"], keyword)
    state["expanded_span"] = [block.start("code") + start, block.start("code") + end]
    return describe(facts)


def patch(text, bounds):
    start, end = bounds
    keyword = text[start:end]
    if not keyword.startswith("**"):
        raise ValueError("展开参数的文本位置已变化")
    # A supplied key keeps its normal precedence even if the mapping changes later.
    return text[:start] + "**{'n_init': 10, " + keyword + "}" + text[end:]


def verifies(original, changed):
    first = next((k.value for k in original.keywords if k.arg is None), None)
    after = next((k.value for k in changed.keywords if k.arg is None), None)
    return (sum(kw.arg is None for kw in original.keywords) == 1
            and all(kw.arg != "n_init" for kw in original.keywords)
            and first is not None and isinstance(after, ast.Dict) and len(after.keys) == 2
            and isinstance(after.keys[0], ast.Constant) and after.keys[0].value == "n_init"
            and isinstance(after.values[0], ast.Constant) and type(after.values[0].value) is int
            and after.values[0].value == 10
            and after.keys[1] is None and ast.dump(after.values[1]) == ast.dump(first))
