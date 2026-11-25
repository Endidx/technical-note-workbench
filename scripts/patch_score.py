"""Offline AST and source checks against the annotated initialization count."""
import ast

from analyzer.callsite import locate
from analyzer.engine import PYTHON_BLOCK
from analyzer.external_config import span


def target_count(case):
    target = case.get("targetNInit", 10)
    if type(target) is not int or target < 1:
        raise ValueError("gold.targetNInit 须为正整数")
    return target


def verified_edit(before, after, count=10):
    if not isinstance(before, str) or not isinstance(after, str) or type(count) is not int or count < 1:
        return False
    blocks = [list(PYTHON_BLOCK.finditer(note)) for note in (before, after)]
    if any(len(items) != 1 for items in blocks):
        return False
    a, b = (items[0] for items in blocks)
    if before[:a.start("code")] != after[:b.start("code")] or before[a.end("code"):] != after[b.end("code"):]:
        return False
    old, new = a["code"], b["code"]
    try:
        old_tree, new_tree = ast.parse(old), ast.parse(new)
        original, edited = locate(old, tree=old_tree), locate(new, tree=new_tree)
        if any(kw.arg is None for site in (original, edited) for kw in site.keywords):
            # Historical attested mapping patch. The existing mapping wins on collisions.
            old_maps = [kw for kw in original.keywords if kw.arg is None]
            new_maps = [kw for kw in edited.keywords if kw.arg is None]
            if (count != 10 or len(old_maps) != 1 or len(new_maps) != 1
                    or any(kw.arg == "n_init" for kw in original.keywords)):
                return False
            mapped = new_maps[0].value
            key = ast.dump(ast.Constant("n_init"))
            if (not isinstance(mapped, ast.Dict) or len(mapped.keys) != 2 or mapped.keys[0] is None
                    or ast.dump(mapped.keys[0]) != key or mapped.keys[1] is not None
                    or ast.dump(mapped.values[0]) != ast.dump(ast.Constant(count))):
                return False
            start, end = span(old, old_maps[0])
            if new != old[:start] + "**{'n_init': 10, " + old[start:end] + "}" + old[end:]:
                return False
            new_maps[0].value = mapped.values[1]
            return ast.dump(old_tree) == ast.dump(new_tree)
        initial = next((kw for kw in original.keywords if kw.arg == "n_init"), None)
        param = next((kw for kw in edited.keywords if kw.arg == "n_init"), None)
        if not param or not isinstance(param.value, ast.Constant) or type(param.value.value) is not int or param.value.value != count:
            return False
        if initial:
            value = initial.value
            if not isinstance(value, ast.Constant):
                return False
            allowed = value.value == "auto" or (type(value.value) is int and value.value > 0)
            if not allowed or value.value == count:
                return False
            s, e = span(old, value)
            x, y = span(new, param.value)
            if old[:s] != new[:x] or old[e:] != new[y:] or "#" in old[s:e]:
                return False
            value.value = count
        else:
            # Compare every source character outside the keyword and its separator.
            # AST equality below independently enforces identical program structure.
            x, y = span(new, param)
            left = new[:x].rstrip(" \t\r\n,")
            right = new[y:].lstrip(" \t\r\n,")
            if not old.startswith(left) or not old.endswith(right) or "#" in new[x:y]:
                return False
            middle = old[len(left):len(old)-len(right)]
            if middle.strip(" \t\r\n,"):
                return False
            edited.keywords.remove(param)
        return ast.dump(old_tree) == ast.dump(new_tree)
    except (ValueError, SyntaxError, RecursionError):
        return False
