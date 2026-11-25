"""Check whether a migration policy actually applies to the active call."""
import re

from . import intent, model_intent
from .engine import PYTHON_BLOCK

OLD = re.compile(r"(?:复现|重做|复做|重现|重跑|沿用|保留|延续|对齐|保持).{0,12}(?:老|旧|过往|历史|上期|上季|以前|原来|原有|此前)")
DEFAULT = re.compile(r"(?:库|新|新版本?|升级后|1\.4).{0,8}(?:默认|缺省|开箱)|(?:跟随|使用|采用).{0,5}(?:默认|缺省)")
MISSING = re.compile(r"(?:没(?:有)?|未|不曾|忘(?:了|记)|无法).{0,9}(?:记录|留下|写明|说|告知|告诉|指定|交代|说明|明确|决定|选定|确定|定下|想好|拍板|裁决|分清|交代|敲定)|"
                     r"(?:待|等待|等).{0,12}(?:确认|决定|答复|选定|裁决)|尚无定论|[不未]清楚|不知道|待定|未定|还没定|没想好")
PURPOSE = re.compile(r"用途|目的|任务|需求|题目|作业|报告|复现|复做|重做|目标|还是|二选一")
OWNER = re.compile(r"谁|哪(?:一)?(?:方|边|个|种|套)|优先|以.{0,6}为准|归属|听谁|裁决|取舍|两(?:边|方|套|种)")
SHARED = re.compile(r"(?:同一段|同一份|同一个|同一|这个|这段|当前这段|这一|本页这段|这份|这条|当前)(?:活动|实际|可执行|线上|正在使用的)?(?:调用|代码|脚本|实现|入口|示例|发布包|文件|产物|程序)|共用.{0,8}(?:代码|调用|脚本|入口)")
DISTINCT = re.compile(r"各自|互不影响|不适用|只[是供]|分别用于|另一(?:段|个|份)(?:代码|调用|脚本|入口)|(?:仅供|仅作)(?:引用|参考)|(?:举例|例如|摘录|转引|引用).{0,10}[“「]")
SELECTION = re.compile(r"(?:最终|已经|现已|最后|本次|本页|此处|此调用|这段|当前|结论|决定|定案|确定).{0,22}(?:确定|定为|决定|选择|采用|使用|跟随|保留|沿用|按|固定|复现|用于)|(?:最终|现已|已经).{0,12}(?:为准|优先)")
PAST = re.compile(r"上次|上回|去年|当年|以往|过去|曾经|此前|先前|之前|旧(?:资料|笔记|记录|报告)|当时|上一版|历史|原先")
MODAL = re.compile(r"坚持|让|要|请|必须|采用|跟随|固定|要求|希望|主张|保留|沿用|按|选择|使用")
SEPARATE_LINE = re.compile(r"^\s*#")


def policies(quote):
    old = bool(OLD.search(quote) or intent.TEN.search(quote) or intent.CANDIDATE_GROUP.search(quote)
               or model_intent.COUNT_REFERENCE.search(quote) or intent.OLD_TARGET.search(quote))
    return old, bool(DEFAULT.search(quote))


def active_prose(markdown):
    """Preserve physical lines while excluding separately labelled reference material."""
    block = PYTHON_BLOCK.search(markdown)
    if not block:
        return markdown
    active_line = markdown.count("\n",0,block.start()) + 1
    lines = markdown.splitlines(keepends=True)
    headings = {}
    stack = []
    for number,line in enumerate(lines,1):
        match = re.match(r"^ {0,3}(#{1,6})\s+(.+)",line)
        if match:
            level = len(match[1])
            stack = [(n,t) for n,t in stack if n < level]
            stack.append((level,match[2]))
        headings[number] = tuple(stack)
    active = headings[active_line]
    if not active:
        return markdown
    reference = re.compile(r"摘录|旧项目|旧例|其他(?:项目|脚本)|旁注|仅供参考|历史资料")
    for n,line in enumerate(lines,1):
        if headings[n] != active and any(reference.search(t) for level,t in headings[n] if (level,t) not in active):
            lines[n-1] = "\n" if line.endswith("\n") else ""
    return "".join(lines)


STAKEHOLDER = re.compile(r"([^，,；;。]{1,22}?)(?:让我|让我们|留言|提出|主张|希望|要求|坚持|建议|却要|想要|要(?:使用|保留|固定|采用))")
CLOSED = re.compile(r"(?:最终|现在|本页|此次|这里|此处|确定|已经|已决定).{0,20}(?:为准|优先|说了算|拍板)|(?:确认|决定|最终).{0,6}(?:听|采纳|按)")
SUBJECT = re.compile(r"(?:本次|这次|这回|下回|当前|接下来|升级后|新版|迁移后|新任务|这段|本页|任务|用途|目的|题目|报告)")


def actor(quote):
    match = STAKEHOLDER.search(quote)
    if not match:
        return ""
    name = match[1].strip("，,：: ")
    if PAST.search(name) or re.search(r"^(?:本次|这一|参数|初始化|最终)",name):
        return ""
    return name


def resolution(statements, start, people):
    for s in reversed(statements):
        if s.sentence < start:
            continue
        for clause in reversed(re.split(r"[，,]", s.quote)):
            if (MISSING.search(clause) or intent.QUALIFIED.search(clause) or intent.NEGATIVE.search(clause)
                    or COUNTERFACTUAL.search(clause) or REJECTED.search(clause)):
                continue
            if not (SELECTION.search(clause) or CLOSED.search(clause)):
                continue
            sides = policies(clause)
            if sum(sides) == 1:
                return {"resolved":"old" if sides[0] else "default", "citation":s}
            supported = [kind for kind,name in people.items() if name and name in clause]
            if CLOSED.search(clause) and len(supported)==1:
                return {"resolved":supported[0], "citation":s}
    return None


ALTERNATIVES = re.compile(r"(?:既|也|有)?可能.{0,80}(?:也可能|或)|(?:还是|或是|或者|二选一)")
LEGACY_PRODUCT = re.compile(r"(?:旧|过去|原来|以前|历史).{0,12}(?:报告|图|照|数据|结果|标签|效果)|(?:重做|复现|还原|补印|复刻|再现)")
DELEGATED = re.compile(r"(?:按|照|跟|随|由|让).{0,9}(?:新版|库|1\.4).{0,12}(?:决定|选|配置|运行|跑)|"
                       r"(?:新版|库|1\.4).{0,5}(?:怎么|如何).{0,8}(?:选|定|跑).{0,9}(?:怎么|照|就)|"
                       r"(?:只想|只要|专门|目标|只测).{0,14}(?:全新安装|开箱|原装|原生).{0,12}(?:运行|表现|结果|效果|1\.4)")
COUNTERFACTUAL = re.compile(r"如果|假如|假设|倘若|本来可能|原本打算|本来打算|一度|曾打算|已被否决|已被撤销|不再适用|不予采用")
REJECTED = re.compile(r"否决|放弃|撤销|取消|驳回|不再采纳")
TASK = re.compile(r"任务|用途|交付|目的|拿去|拿来|新版|需求|目标|题目|复做|做哪|做什么|用来|用在|用于|哪件事")


def rejected_policy(clause, policy):
    if REJECTED.search(clause) and not re.search(r"(?:未|没有|并未|尚未).{0,3}(?:撤销|取消|否决|放弃|驳回)",clause):
        return True
    target = r"(?:保留|固定|沿用|执行)" if policy == "old" else r"(?:采用|测|用|跟随|看)"
    return bool(re.search(r"(?:不再|不应|不要|不想|不显式|不必|无需).{0,12}"+target,clause))


def role_claims(statements):
    claims = {"old": [], "default": []}
    for s in statements:
        # Coordinate clauses can assign different policies to different people in one sentence.
        for clause in re.split(r"[，,]",s.quote):
            if (not MODAL.search(clause) or PAST.search(clause) or MISSING.search(clause)
                    or COUNTERFACTUAL.search(clause) or intent.QUALIFIED.search(clause)):
                continue
            sides = policies(clause)
            if sum(sides) == 1:
                policy = "old" if sides[0] else "default"
                if rejected_policy(clause, policy):
                    continue
                claims[policy].append((s,actor(clause)))
        # The second clause may explain the default policy of the owner in the first.
        if actor(s.quote) and policies(s.quote) == (False,True) and not rejected_policy(s.quote,"default") and not any(
                guard.search(s.quote) for guard in (COUNTERFACTUAL, MISSING, PAST, intent.QUALIFIED)):
            claims["default"].append((s,actor(s.quote)))
    return claims


def settled_default(items):
    past = [s for s in items if PAST.search(s.quote) and policies(s.quote)[0]]
    if not past:
        return None
    later = [s for s in items if s.sentence > past[-1].sentence]
    if any(MISSING.search(s.quote) or COUNTERFACTUAL.search(s.quote) or "？" in s.quote for s in later):
        return None
    for s in later:
        if (DELEGATED.search(s.quote) and not intent.NEGATIVE.search(s.quote)
                and not DISTINCT.search(s.quote) and not intent.OTHER.search(s.quote)):
            if any(policies(t.quote)[0] and MODAL.search(t.quote) and not PAST.search(t.quote) for t in later):
                return None
            return {"resolved":"default","citation":s}
    return None


def examine(markdown):
    items = model_intent.sentences(markdown)
    if any(model_intent.CONTROL.search(s.quote.lower()) for s in items):
        return None
    sections = {}
    section = 0
    for n,line in enumerate(markdown.splitlines(),1):
        if SEPARATE_LINE.match(line):
            section += 1
        sections[n] = section
    for index, anchor in enumerate(items):
        q = anchor.quote
        if DISTINCT.search(q) or not (MISSING.search(q) or SHARED.search(q)):
            continue
        nearby = [s for s in items[max(0,index-6):index+7] if sections[s.line] == sections[anchor.line]]
        shared = [s for s in nearby if SHARED.search(s.quote) and not DISTINCT.search(s.quote)]
        local = [s for s in nearby if not DISTINCT.search(s.quote)
                 and (not intent.OTHER.search(s.quote) or shared)]
        if anchor not in local:
            continue
        past = [s for s in local if PAST.search(s.quote) and policies(s.quote)[0]]
        claims = role_claims(local)
        pairs = [(left,right) for left in claims["old"] for right in claims["default"]
                 if left[1] and right[1] and left[1] != right[1]]
        explicit_priority = MISSING.search(q) and OWNER.search(q)
        if not pairs and explicit_priority and claims["old"] and claims["default"]:
            pairs = [(claims["old"][0],claims["default"][0])]
        if shared and pairs:
            gap = "requirement_owner"
            (old,name_old),(new,name_new) = pairs[0]
            people = {"old":name_old,"default":name_new}
            authority = next((s for s in local if MISSING.search(s.quote) and OWNER.search(s.quote)), None)
            witnesses = [old,new,shared[0]] + ([authority] if authority else [])
            choices = {"old": (people["old"]+" · " if people["old"] else "")+"保留十次初始化",
                       "default": (people["default"]+" · " if people["default"] else "")+"采用新版默认"}
            question = "同一段调用有两种现行要求。这次以哪方为准？"+" / ".join(choices.values())
            cutoff = max(s.sentence for s in [old, new] + ([authority] if authority else []))
        elif MISSING.search(q) and not re.search(r"(?:配色|排版|文件名|截止|交付时间|标题|图表|署名|格式)",q) and (
                (past and PURPOSE.search(q) and SUBJECT.search(q)) or
                (TASK.search(q) and any(ALTERNATIVES.search(s.quote) and LEGACY_PRODUCT.search(s.quote)
                                      and policies(s.quote)[1] for s in local))):
            gap = "migration_purpose"
            people = {}
            alternatives = next((s for s in local if ALTERNATIVES.search(s.quote) and LEGACY_PRODUCT.search(s.quote)),anchor)
            witnesses = past[:1] + [alternatives,anchor]
            question = "这次交付要复现旧结果，还是记录新版默认设置的效果？需要先确定这段代码的用途。"
            choices = {"old":"复现旧结果，保留十次初始化","default":"记录新版默认效果，保留省略写法"}
            cutoff = anchor.sentence
        else:
            continue
        decided = resolution(local,cutoff+1,people)
        if decided:
            return decided
        evidence = sorted(set(witnesses),key=lambda s:s.sentence)
        return {"decisionGap":gap,"citations":[vars(s) for s in evidence],
                "question":question,"questionChoices":choices}
    sections_with_prose = {}
    for s in items:
        sections_with_prose.setdefault(sections[s.line], []).append(s)
    decisions = [r for group in sections_with_prose.values() if (r := settled_default(group))]
    return decisions[0] if len(sections_with_prose) == 1 and decisions else None
