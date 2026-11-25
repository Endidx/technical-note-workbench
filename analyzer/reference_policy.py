"""Resolve current KMeans count requirements against attributable reference facts."""
import ast
import json
import re

from . import decision_gate, model_intent
from .engine import PYTHON_BLOCK
from .intent import INFO_ONLY, NEGATIVE, NEW_DEFAULT, OTHER, QUALIFIED, UNSETTLED

VERSION = re.compile(r'(?<![\w.])v?(\d+\.\d+(?:\.\d+)?)(?![.\d])', re.ASCII)
ALIGN = re.compile(r'一致|相同|相等|对齐|匹配|兼容|复现|保持不变|match|same|compatible', re.I)
SUBJECT = re.compile(r'初始化|重启次数|n_init|initiali[sz]ation|restarts', re.I)
REQUIRE = re.compile(r'要求|提出|必须|应当|需要|务必|保持|维持|对齐|must|shall|require', re.I)
OLD = re.compile(r'升级前后|迁移前后|旧版本?|升级前|参照版本|参考版本|previous version', re.I)
UNCERTAIN = re.compile(r'可能|据说|待核实|尚未|假设|例如|示例|曾经|曾要求|不再|曾用|而非|并非|不一致', re.I)
LIB = r'(?:scikit-learn|sklearn)'
NAME = r'(?:[A-Za-z][A-Za-z0-9_.-]*|[\u4e00-\u9fff]{1,12}?(?:端|实现|后端|引擎|模块|版本|库))'
PEER = re.compile(r'(?:与|和|同|跟|对齐|匹配|match(?:es)?\s+)\s*(' + NAME + ')', re.I)
REVERSE = re.compile(r'(' + NAME + r')\s*(?:实现|一侧|端)?\s*(?:与|和|同)\s*' + LIB, re.I)
NUM = r'(?<![-.\d零一二两三四五六七八九十百千])([1-9]\d{0,8}|[一二两三四五六七八九]?十[一二三四五六七八九]?|[一二两三四五六七八九])(?![.\d零一二两三四五六七八九十百千])'
COUNT = re.compile(NUM + r'\s*(?:次|轮)\s*(?:独立|随机)?(?:初始化|重启)|(?:n_init|初始化次数|重启次数)\s*(?:明确)?(?:=|为|是|设为|设置为|指定为|固定为|默认为|使用)\s*' + NUM, re.I)
DIGITS = {ch: i for i, ch in enumerate('零一二三四五六七八九')}
DIGITS['两'] = 2


def counts(text):
    values = set()
    for match in COUNT.finditer(text):
        raw = next(x for x in match.groups() if x)
        if raw.isascii():
            values.add(int(raw))
        elif '十' in raw:
            tens, ones = raw.split('十')
            values.add(10 * DIGITS.get(tens, 1) + DIGITS.get(ones, 0))
        else:
            values.add(DIGITS[raw])
    return values


def uncertain(text):
    return any(pattern.search(text) for pattern in (
        QUALIFIED, UNCERTAIN, UNSETTLED, NEGATIVE, INFO_ONLY, OTHER, model_intent.CONTROL))


CURRENT_SCOPE = re.compile(r'维护者|维护人员|作者|本次|当前|此(?:处|调用)|这(?:段|个)(?:代码|调用|函数)|'
                           r'(?:本|该)(?:次|调用|函数|包装|构造器|接口)|\bKMeans\b', re.I)
DECIDED = re.compile(r'要求|决定|指定|必须|确定|明确|务必|应当|改为|改用|设为|固定为|统一为|采用', re.I)
POSSIBILITY = re.compile(r'过去|上次|当时|原计划|曾|此前|当年|以前|去年|上个月|提议|考虑|设想|待选|备选|'
                         r'二选一|还是|或者|待定|尚待|仅供参考|仅作参考|有人建议|如若|只要|若是|若要|假如')
DEFAULT_OF = re.compile(r'(?:采用|使用|遵循|沿用|取自|按|取)\s*(?:参照|参考)?(?:函数|包装器)?\s*'
                        r'([a-zA-Z_]\w*)\s*(?:\(\))?\s*(?:函数)?的?\s*(?:参数)?默认', re.ASCII)
COUNT_NAME = re.compile(r'n_init|(?:初始化|重启)(?:的)?次数', re.I)


def signature_count(markdown, name):
    """Find a uniquely bound top-level function's literal n_init default."""
    block = PYTHON_BLOCK.search(markdown)
    if not block:
        return None
    tree = ast.parse(block['code'])
    definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    if len(definitions) != 1 or definitions[0].decorator_list:
        return None
    function = definitions[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == name:
            return None  # rebinding, mutation of __defaults__, or other use not verified here
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name and node is not function:
            return None
        if isinstance(node, ast.alias) and (node.name == '*' or (node.asname or node.name.split('.')[0]) == name):
            return None
    args = function.args
    positional = args.posonlyargs + args.args
    defaults = list(zip(positional[len(positional) - len(args.defaults):], args.defaults))
    defaults.extend(zip(args.kwonlyargs, args.kw_defaults))
    for param, value in defaults:
        if param.arg == 'n_init' and isinstance(value, ast.Constant) and type(value.value) is int and value.value > 0:
            first = markdown.count('\n', 0, block.start('code'))
            lines = markdown.splitlines()
            evidence = [dict(line=first + n, quote=lines[first+n-1].strip())
                        for n in sorted({function.lineno, param.lineno, value.lineno})]
            return value.value, evidence
    return None


def direct_policy(items, markdown):
    """Require a current instruction and a quantity bound to the constructor's starts."""
    if any(re.search(r'(?:该|上述|原|这项)(?:决定|要求|方案|规定).{0,8}(?:撤销|取消|作废|失效|待定)', item.quote) for item in items):
        return None
    claims = []
    for item in items:
        q = item.quote.replace('`', '')
        if (uncertain(q) or POSSIBILITY.search(q) or not CURRENT_SCOPE.search(q)
                or not DECIDED.search(q) or re.search(r'父版本|原实现|原先的配置', q)):
            continue
        author_decision = re.search(r'要求|决定|必须|务必|应当|明确(?:指定|要求)|改用|改为', q)
        if not author_decision and not re.search(r'维护者|维护人员|作者', q):
            continue
        # Scope and quantitative instruction must apply to the same object.
        # A following clause can describe another implementation or a prior run.
        decision = re.search(r'(?:要求|决定|必须|明确|务必|应当|指定|改为|改用|设为|采用)', q)
        if not decision:
            continue
        instruction = q[author_decision.start():] if author_decision else q
        if not SUBJECT.search(instruction):
            wrapper = DEFAULT_OF.search(instruction) and re.search(r'包装|无参|未传|不传|未指定', instruction)
            constructor = NEW_DEFAULT.search(instruction) and re.search(r'KMeans|构造器|此调用|该调用|当前调用', instruction, re.I)
            if not (wrapper or constructor) or re.search(r'种子|簇数|n_clusters|random_state', instruction):
                continue
        if re.search(r'(?:要求|规定|让)\s*(?!当前|本次|本地|这边|scikit|sklearn|KMeans)(?:[\u4e00-\u9fff]{1,8}端|[a-zA-Z_]\w*实现)\s*(?:使用|采用|执行|改用|必须)', instruction, re.I):
            continue
        if re.search(r'(?:旁支|另一个|另一端|对照端|对照组|外部|其他|其它)(?:的|项目|调用|实现|默认|必须|使用|执行)?', instruction):
            continue
        reference = DEFAULT_OF.search(instruction)
        default = bool(NEW_DEFAULT.search(instruction))
        values = counts(instruction)
        if reference and not default:
            claims.append((item, 'function', reference[1], set()))
        elif default:
            claims.append((item, 'default', 'scikit-learn 1.4.2 默认行为', values))
        elif values or (COUNT_NAME.search(instruction) and re.search(r'正整数|整数值|具体次数', instruction)):
            claims.append((item, 'decision', '当前调用的维护要求', values))
    if not claims or decision_gate.examine(markdown):
        return None
    # Preserve the established hierarchy for pending ownership and purpose choices.
    if any(UNSETTLED.search(item.quote) and re.search(r'哪位|由谁|谁的|哪套|哪种用途|二选一|尚未决定|尚待签字', item.quote)
           for item in items):
        return None
    kind, name = claims[0][1:3]
    cites = [vars(claim[0]) for claim in claims]
    result = dict(kind=kind, reference=name, citations=cites)
    if kind == 'default' and any(re.search(r'''n_init\s*=\s*['"]auto['"]''', c[0].quote, re.I) for c in claims):
        result['literalAuto'] = True
    if len({(c[1], c[2]) for c in claims}) != 1:
        result['question'] = '当前记录包含多项初始化政策。请确认本次调用采用哪一项以及相应的初始化次数。'
        return result
    values = set().union(*(c[3] for c in claims))
    if kind == 'function':
        # Only the named function's initialization-count default supplies this value.
        definition = re.compile(r'^\s*(?:参照|参考)?(?:函数)?\s*' + re.escape(name)
                                + r'(?![a-zA-Z0-9_])\s*(?:\(\))?\s*(?:函数)?的?\s*'
                                  r'(?:参数)?\s*(?:n_init|初始化次数|重启次数)\s*(?:参数)?(?:的)?默认(?:值)?\s*(?:为|是|=)\s*' + NUM, re.I)
        for item in items:
            if uncertain(item.quote) or POSSIBILITY.search(item.quote):
                continue
            for clause in re.split(r'[，,；;]', item.quote.replace('`', '')):
                match = definition.match(clause)
                if match:
                    values.update(counts('n_init=' + match[1]))
                    if vars(item) not in cites:
                        cites.append(vars(item))
        signature = signature_count(markdown, name)
        if signature:
            count, locations = signature
            values.add(count)
            cites.extend(locations)
    if len(values) > 1:
        result['question'] = f'{name} 的初始化次数存在冲突（{sorted(values)}）。本次应使用哪一个？'
    elif values:
        result['specifiedCount'] = values.pop()
    elif kind != 'default':
        result['question'] = f'请补充{name}明确使用的 n_init 正整数，即一次拟合执行多少次初始化。'
    return result


def policy(markdown):
    items = model_intent.sentences(decision_gate.active_prose(markdown))
    requirements = []
    for item in items:
        q = item.quote
        if not (SUBJECT.search(q) and REQUIRE.search(q) and ALIGN.search(q)):
            continue
        if uncertain(q):
            continue
        peers = [m[1] for m in [*PEER.finditer(q), *REVERSE.finditer(q)]
                 if not re.fullmatch(LIB, m[1], re.I)]
        if peers and re.search(LIB, q, re.I):
            requirements.extend(('implementation', ref, item) for ref in peers)
        elif VERSION.search(q) or OLD.search(q):
            requirements.extend(('version', ref, item) for ref in VERSION.findall(q) or ['升级前'])
    if not requirements:
        return direct_policy(items, decision_gate.active_prose(markdown))
    kind, name, _ = requirements[0]
    evidence = dict(kind=kind, reference=name, citations=[vars(t) for t in dict.fromkeys(r[2] for r in requirements)])
    if kind == 'version':
        evidence['sameArguments'] = any(re.search(r'相同(?:的)?(?:参数|配置|调用)|参数不变|沿用(?:同一|原来)(?:组)?参数', item.quote)
                                        for _, _, item in requirements)
        evidence['referenceDefault'] = any(re.search(r'默认|缺省|default', item.quote, re.I)
                                           for _, _, item in requirements)
    if len({(kind, ref.casefold()) for kind, ref, _ in requirements}) > 1:
        evidence['question'] = '列出的参照目标不一致。请明确本次应对齐哪一个版本或实现，以及该目标的初始化次数。'
        return evidence
    # A question about ten starts and a number attributed to a third implementation
    # are neither observations of the selected reference nor count requirements.
    bound = set()
    version_facts = []
    if kind == 'version':
        for item in items:
            if uncertain(item.quote):
                continue
            # Distinguish the named baseline from a separate evaluation environment.
            for match in re.finditer(r'(?:升级前|迁移前|旧环境|旧版|原先|参照版本)\s*(?:使用|运行|采用|为|是)?\s*(?:scikit-learn|sklearn)?[ =v]*(\d+\.\d+(?:\.\d+)?)', item.quote, re.I):
                version_facts.append((match[1], item, match.end()))
        versions = {v for v, _, _ in version_facts}
        if versions and name != '升级前':
            versions.add(name)
        if len(versions) > 1:
            evidence['question'] = '升级前的参照版本存在冲突。请确认本次需要兼容的确切版本及实参。'
        elif versions:
            name = evidence['reference'] = versions.pop()
        for _, item, end in version_facts:
            if vars(item) not in evidence['citations']:
                evidence['citations'].append(vars(item))
            # Same-subject continuation may specify the former call's actual n_init.
            follow = re.match(r'^[，,\s]*(?:并|且)?(?:显式)?(?:设置|指定|采用|使用|传入)?\s*(.*)$', item.quote[end:])
            if follow and COUNT.match(follow[1]):
                bound.update(counts(follow[1]))
    literal = re.escape(name)
    local = []
    for item in items:
        q = item.quote
        if uncertain(q):
            continue
        if (vars(item) not in evidence['citations'] and REQUIRE.search(q)
                and re.search(r'当前调用|本次|此处|该调用|本页', q)
                and (counts(q) or NEW_DEFAULT.search(q))):
            local.append((item, sorted(counts(q)), bool(NEW_DEFAULT.search(q))))
        for clause in re.split(r'[，,：:]', q):
            # Anchor the observation to its named subject. Do not borrow a later
            # subject's value in a compound sentence.
            match = re.match(r'^\s*(?:参照|参考|旧版|升级前(?:的)?|实测|确认|其中|在)?\s*(?:scikit-learn\s+)?'
                             + literal + r'(?![\w.-])\s*(?:一侧|这边|侧|端|实现|版本|中|下)?'
                             r'\s*(?:以|执行|运行|进行了?|实际|使用|采用|设置|显式|传入|为|的|共|做|有|进行了|每次拟合|\s)*'
                             r'(.*)$', clause, re.I | re.ASCII)
            if not match:
                continue
            rest = match[1]
            found = counts(rest)
            if (found and COUNT.match(rest) and not re.search(r'(?:而|但是|或|另外|同时|另一个|另一侧)', rest)):
                bound.update(found)
                if vars(item) not in evidence['citations']:
                    evidence['citations'].append(vars(item))
    if local:
        evidence['localRequirements'] = [dict(citation=vars(item), counts=values, useDefault=use_default)
                                         for item, values, use_default in local]
        evidence['citations'].extend(vars(item) for item, _, _ in local)
    if len(bound) == 1:
        evidence['specifiedCount'] = bound.pop()
    elif bound:
        evidence['question'] = f'{name} 的实际初始化次数出现冲突（{sorted(bound)}）。本次比较采用哪一个？'
    return evidence


def call_facts(kw, *, callable_fact=False):
    def literal(name, default):
        node = kw.get(name)
        if node is None:
            return default
        return node.value if isinstance(node, ast.Constant) and type(node.value) in (str, int) else None
    init = literal('init', 'k-means++')
    if isinstance(kw.get('init'), ast.Lambda) or callable_fact:
        init = 'callable'
    elif init == 'callable':
        init = None
    count = literal('n_init', 'absent')
    if count == 'absent' and 'n_init' in kw:
        count = None
    return {'init': init, 'n_init': count}


def resolve(evidence, facts, snapshots, mapping=False, source_labels=None):
    """Bind the reference and the effective 1.4 count for this actual call."""
    result = dict(evidence)
    ref = result['reference']
    init, count = facts['init'], facts['n_init']
    known_init = init in ('k-means++', 'random', 'callable')
    current = count if type(count) is int and count > 0 else None
    if count in ('absent', 'auto') and known_init:
        current = 1 if init == 'k-means++' else 10
    result.update(currentCount=current, init=init, n_init=count)
    if 'question' in result:
        return result
    if result['kind'] == 'version':
        snapshot = snapshots.get(f'sklearn-{ref}.json')
        target = result.get('specifiedCount')
        if snapshot:
            doc = json.loads(snapshot)
            if doc['version'] != ref or doc['estimator'] != 'sklearn.cluster.KMeans':
                raise ValueError('参照快照与版本或估算器不符')
            result['source'] = doc['source']
            result['sourceDefaults'] = doc['constructor']
            if target is None:
                if count == 'absent' or result['referenceDefault']:
                    target = doc['constructor']['n_init']
                elif result['sameArguments'] and type(count) is int:
                    target = count
        elif ref in ('1.1.3', '1.4.2'):
            baseline = snapshots['sklearn-1.1.md' if ref == '1.1.3' else 'sklearn-1.4.md'].decode()
            result['source'] = (source_labels or {}).get(ref) or re.search(r'\((https://[^)]+)\)', baseline)[1]
            if target is None:
                use_default = count == 'absent' or result['referenceDefault']
                if use_default:
                    target = 10 if ref == '1.1.3' or init in ('random', 'callable') else 1
                elif result['sameArguments'] and (ref == '1.4.2' or type(count) is int):
                    target = current
        elif target is None:
            result['question'] = f'请补充{ref}所指的确切 scikit-learn 版本及其 KMeans 默认值来源，或该版本实际运行时的 init 和 n_init。'
    elif result['kind'] == 'default':
        target = 1 if init == 'k-means++' else 10 if init in ('random', 'callable') else None
        baseline = snapshots['sklearn-1.4.md'].decode()
        result['source'] = (source_labels or {}).get('1.4.2') or re.search(r'\((https://[^)]+)\)', baseline)[1]
        if result.get('literalAuto') and count != 'auto':
            result['question'] = "原文要求参数使用 'auto'。请直接核对该参数写法；固定整数不能表达这项要求。"
        elif target is None:
            result['question'] = '请核实当前调用实际传入的 init，才能确定 scikit-learn 1.4.2 的默认初始化次数。'
        elif 'specifiedCount' in result and result['specifiedCount'] != target:
            result['question'] = '给出的初始化次数与此 init 在新版中的默认次数不一致。请确认本次应遵循哪一项。'
    else:
        target = result.get('specifiedCount')
    if 'question' not in result:
        for claim in evidence.get('localRequirements', []):
            required = set(claim['counts'])
            if claim['useDefault'] and known_init:
                required.add(1 if init == 'k-means++' else 10)
            if target is not None and required - {target}:
                result['question'] = f'本次调用的要求与参照对象 {ref} 的次数冲突。请确认本次以哪项为准，以及目标次数。'
                return result
        if target is None or target < 1:
            result['question'] = f'请确认参照对象 {ref} 在本次运行中实际使用的 init 和 n_init，或实际执行的初始化次数。'
        elif current is None or not known_init:
            result['question'] = f'为与 {ref} 对齐，请补充当前调用实际传入的 init 和 n_init。'
        elif current != target and mapping:
            result['question'] = f'请将当前 init 和 n_init 展开为直接的正整数配置，以核对与 {ref} 的次数差异。'
        else:
            result['targetCount'] = target
    return result
