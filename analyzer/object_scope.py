"""Associate the current instruction sheet with its physical recipient."""

import re
from dataclasses import dataclass

from . import bindings, intent, model_intent

DOCUMENT = r"(?:说明书?|手册|卡片|操作卡|使用卡|说明卡|卡|页|笔记|脚本|代码|调用|段落|示例|例子|程序|文档)"
LOCAL = re.compile(r"(?:本|当前|此|这(?:一|份|张|段|篇|个|页|本)?|下(?:面|方)(?:的)?)" + DOCUMENT)
RELATION = re.compile(r"(?:实际|专门|仍然?|只|已经|确定|确认|是|将|的|应|要|仅|已|最后|最终|现在|本次|此次|随附)*"
                      r"(?:随附于|随同|随|附在|装入|装进|配给|寄给|交给|发给|给|属于|归属(?:于)?|适用(?:于)?|用于|供|面向|针对|运行在|对应|绑定到)")
PHYSICAL = re.compile(r"实物|随箱|装箱|随货|发货|随附|随车|工位|机器|设备|机型|硬件|套件|终端|机柜|台架|铭牌|装箱单")
MISSING = re.compile(r"哪(?:一?[台只件套款种个座箱]|边)|未(?:知|明|定|核实|核对|确认)|没.{0,5}(?:核实|确认|核对|辨明|查清)|不(?:清楚|知道|确定)")
UNSAFE = re.compile(r"如果|假如|假设|可能|是否|拟给|原先|原本|曾经|曾给|上次|上一版|并非|不是|不再|取消|作废|撤回|尚待|计划")
QUOTED = re.compile(r'^[“「"‘]([^”」"’]{1,40})[”」"’](?:\s*[（(]([^）)]{1,35})[）)])?')
DEVICE = r"(?:设备|终端|工作站|工位|机柜|套件|台架|机组|平台|系统|工具包|样机|底座|匣|机|台|箱|盒|架|仪|器|车|柜|板|站|包)"
PLAIN = re.compile(r"^([\w-]{1,24}?" + DEVICE + r")(?=的|在|仍|还|已|只|应|须|装|按|要|运行|使用|采用|要求|需|保持|固定|保留|升级|沿用|则|[（(，,:：])")
OLD_VERSION = re.compile(r"(?<![.\d])1\.1\.3(?![.\d])")
NEW_VERSION = re.compile(r"(?<![.\d])1\.4(?:\.\d+)?(?![.\d])|新版|新环境")
RUNS = re.compile(r"(?:一直用|仍用|在用|运行|使用|安装|锁定|锁在|停留在|保持在|固定在|版本为|版本是|环境为)\s*(?:scikit-learn\s*)?$", re.I)
VERSION_DEVICE = re.compile(r"^\s*(?:的)?\s*[\u3400-\u9fff]{0,6}?" + DEVICE + r"(?:$|[，,；;。]|上|运行)")
STORED = re.compile(r"样本|样例|存档|截图|旧图|文件|数据|备份|镜像|日志|备忘|记录文件")
OTHER_DEVICE = re.compile(r"另(?:一|个|台|有)|隔壁|旁边|对面|其他|别的")
QUALIFIER = re.compile(r"(?:从|原为|曾用|原先|原本|以前|由)\s*(?:版本\s*)?$")


@dataclass(frozen=True)
class DeviceRule:
    name: str
    decision: str
    source: model_intent.Sentence
    policy: str
    entity_source: model_intent.Sentence


def decision(text):
    if UNSAFE.search(text) or MISSING.search(text) or bindings.POLICY_NEG.search(text):
        return None
    version = OLD_VERSION.search(text)
    if version and not NEW_VERSION.search(text) and not QUALIFIER.search(text[:version.start()]):
        before, after = text[:version.start()].rstrip(), text[version.end():]
        if not STORED.search(after) and (RUNS.search(before) or VERSION_DEVICE.match(after)):
            return "pinned"
    old = bool(intent.TEN.search(text) or intent.OLD_TARGET.search(text)
               or re.search(r"(?:十|10)\s*(?:套|组)(?:初始(?:化|中心|起点|值)|候选起点)", text))
    new = bool(bindings.NEW.search(text))
    if old != new:
        return "old" if old else "default"
    return None


# Separate the instrument that establishes ownership from the device policy.
PROOF = re.compile(r"工单|派机单|交接单|派单|签收单|派工单|清点单|库位|位置|货位|机位|工位|铭牌|背板|钢印|封签|底座|落款|盖章|库存号|资产号|铅封号|序列号|编号|机号|箱号|标签|派机栏|资产卡")
LOCAL_CARD = re.compile(r"手上(?:的)?(?:卡|页)|随箱(?:的)?卡|说明卡|操作卡|使用卡")
UNAVAILABLE = re.compile(r"(?:未|没(?:有)?|无法|不能|尚待|待)(?:能|再|经)?(?:拆|打开|开盖|翻|读|查|看|揭|核|填|扫|找|取|辨|认|登记|对)|空(?:着|白)|被.{0,8}(?:带掉|撕掉|遮住)|模糊|看不清|丢失|未到")
FOREIGN = re.compile(r"另一(?:台|份|张|页|件)|别台|隔壁|邻机|上次|上回|旧工单|往年|之前|先前|当时|曾经|原先|过去")
NEGATIVE = re.compile(r"并?未|不符|不匹配|对不上|没有|不是|并非|尚待|假如|如果|可能|作废|拟定|原计划|待查|待核")
VERIFIED = re.compile(r"查到|查明|核实|核对|对上|对应|相符|一致|登记(?:为|的是)|确认为|显示|写(?:着|明|的是)|印着|记载|指向|查得|读到|更正为|已对过|落款.{0,6}是")
JOINED = re.compile(r"(?:和|与|跟)\s*[「“]?([\w-]{1,24}?" + DEVICE + r")[」”]?\s*(?:已(?:经)?)?(?:对上|一致|相符|吻合)")
LIST_PREFIX = re.compile(r"^(?:.{0,14}?(?:列着|列有|包括|列出|分别为|列为)|(?:还有|另有|以及))")
ALIAS = re.compile(r"^[（(]([^（）()]{1,35})[）)]")
IDENTIFIER = re.compile(r"(?:编号|机号|库存号|资产号|工单号|序列号|库位|位置|货位)(?:为|是|在|写着)?[：:\s]*([\w-]{1,22})(?=$|[，,])")
LOCATION = re.compile(r"^(?:位于|设在|放在|安放在|在)([\w-]{1,14}(?:仓|室|库|区|工位|站|架))(?=$|[，,])")
CONTINUATION = re.compile(r"^(?:该(?:设备|机|台|柜|匣)|这台(?:设备|机器)|其(?:运行|要求|环境|检验)|柜内|机内|箱内|该处|台上)")


def declarations(items):
    """Collect labels first so that ownership evidence can precede device rules."""
    rules, labels, aliases = [], [], {}
    previous = None
    for source in items:
        text = source.quote.rstrip("。；;！？!?")
        candidate = LIST_PREFIX.sub("", text, count=1)
        candidate = re.sub(r"^(?:换盘|升级|迁移)后的", "", candidate)
        name = QUOTED.match(candidate) or PLAIN.match(candidate)
        if LOCAL.search(text) or CONTINUATION.match(text):
            name = None
        joined = JOINED.search(text)
        if joined and (FOREIGN.search(text) or NEGATIVE.search(text)):
            joined = None
        if joined:
            key, tail = joined[1], text[joined.end():]
            tags = []
        elif name:
            key, tail = name[1], candidate[name.end():]
            tags = list(filter(None, name.groups()[1:]))
            alias = ALIAS.match(tail)
            if alias:
                tags.append(alias[1])
                tail = tail[alias.end():]
        elif previous and CONTINUATION.match(text):
            key, entity_source = previous
            tail = text
            tags = []
        else:
            previous = None
            continue
        if name or joined:
            entity_source = source
            previous = (key, entity_source)
            labels.append((key, source))
        ids = [m[1] for m in IDENTIFIER.finditer(tail)]
        location = LOCATION.match(tail)
        if location:
            ids.append(location[1])
        records = aliases.setdefault(key, {})
        records.setdefault(key, entity_source)
        for tag in tags + ids:
            records[tag] = source
        policy = tail.strip(" ，,：:")
        chosen = decision(OTHER_DEVICE.split(policy, maxsplit=1)[0])
        if chosen and OTHER_DEVICE.search(policy):
            policy = OTHER_DEVICE.split(policy, maxsplit=1)[0].rstrip(" ，,")
        if chosen:
            rules.append(DeviceRule(key, chosen, source, policy, entity_source))
    return rules, labels, aliases


CODE = re.compile(r"(?<![A-Za-z0-9_-])(?=[A-Za-z0-9_-]*[0-9])[A-Za-z0-9][A-Za-z0-9_-]{1,24}(?![A-Za-z0-9_.-])")
REGISTER = re.compile(r"台账|登记册|对照表|库存表|索引|清册|编号表|资产表|登记表")
ASSIGNMENT = re.compile(r"随|配给|发货|交付|分配|发往|接收|贴在|装箱|选设备|归属")


def named_in(tags, text):
    return [tag for tag in tags if (re.search(r"(?<![A-Za-z0-9_-])" + re.escape(tag) +
                                               r"(?![A-Za-z0-9_-])", text, re.I)
                                     if tag.isascii() else tag in text)]


OPERATIONS = (re.compile(r"拆|卸|开盖|打开|揭开|翻开"), re.compile(r"扫(?:描|码)?"),
              re.compile(r"查阅|查询|翻查|查单"), re.compile(r"核验|核对"))
PREREQUISITE = re.compile(r"才能|才可|方可|之后.{0,6}(?:读取|辨认|确认)|必须先")


def proof_links(items, aliases):
    """Join the sheet's credential and a verified reading to its inventory record."""
    for source in items:
        if not REGISTER.search(source.quote) or FOREIGN.search(source.quote) or NEGATIVE.search(source.quote):
            continue
        for entry in re.split("[，,、]", source.quote):
            owners = [tags for tags in aliases.values() if named_in(tags, entry)]
            if len(owners) == 1:
                for code in CODE.findall(entry):
                    owners[0].setdefault(code, source)
    sources, missing, anchors = [], [], {}
    prerequisites = [s for s in items if PROOF.search(s.quote) and PREREQUISITE.search(s.quote)]
    proof_context = any(PROOF.search(s.quote) for s in items)
    for source in items:
        text = source.quote
        local = LOCAL.search(text) or LOCAL_CARD.search(text)
        kinds = set(PROOF.findall(text))
        foreign = FOREIGN.search(text)
        if local and kinds and not foreign:
            for kind in kinds:
                anchors.setdefault(kind, source)
        linked = [anchors[k] for k in sorted(kinds) if k in anchors]
        if local and ASSIGNMENT.search(text) and not foreign:
            missing.append(source)
        if proof_context and UNAVAILABLE.search(text) and not foreign:
            required = [s for s in prerequisites if kinds.intersection(PROOF.findall(s.quote))
                        or any(op.search(s.quote) and op.search(text) for op in OPERATIONS)]
            if linked or local or kinds or required:
                missing.extend([*required, source])
        if not linked or foreign or PREREQUISITE.search(text) or REGISTER.search(text) or NEGATIVE.search(text) or UNSAFE.search(text):
            continue
        found = [(key, tags[tag]) for key, tags in aliases.items() for tag in named_in(tags, text)]
        if VERIFIED.search(text) and len({key for key, _ in found}) == 1:
            sources.append((source, found[0][0], [*linked, *(s for _, s in found)]))
        if local and kinds and not VERIFIED.search(text):
            missing.append(source)
    return sources, missing


def inspect(prose):
    items = bindings.note_items(prose)
    if not items or any(model_intent.CONTROL.search(s.quote.lower()) for s in items):
        return None
    rules, labels, aliases = declarations(items)
    selections, pending = proof_links(items, aliases)
    physical = False
    for s in items:
        text = s.quote.rstrip("。；;！？!?")
        physical |= bool(PHYSICAL.search(text))
        if MISSING.search(text) and not re.search(r"(?:无论|不管).{0,8}哪", text) and (PHYSICAL.search(text) or LOCAL.search(text)):
            pending.append(s)
        for clause in re.split("[，,]", text):
            local = LOCAL.search(clause)
            if not local or MISSING.search(text) or UNSAFE.search(text) or FOREIGN.search(clause) or re.search(r"(?:未|没有|不)(?:发给|配给|属于|随|核实|确认)", clause):
                continue
            relation = RELATION.match(clause, local.end())
            if relation:
                recipient = clause[relation.end():]
                physical |= bool(re.search(DEVICE + r"(?:$|[上中])", recipient))
                selections.append((s, recipient, []))
    if not physical and not any(PLAIN.match(s.quote) for s in items) and not any(
        re.search(DEVICE + "$", rule.name) for rule in rules
    ):
        return None
    matches = []
    for source, recipient, chain in selections:
        owners = [key for key, tags in aliases.items() if named_in(tags, recipient)]
        if len(owners) > 1:
            pending.append(source)
            continue
        found = [r for r in rules if r.name in owners]
        if len(found) == 1:
            rule = found[0]
            matches.append((rule.decision, source, [*chain, rule.entity_source, rule.source, source]))
        elif not found and OLD_VERSION.search(recipient) and re.search(DEVICE, recipient):
            if decision(recipient) == "pinned":
                matches.append(("pinned", source, [source]))
        elif not found and NEW_VERSION.search(recipient) and re.search(DEVICE, recipient):
            # The current sheet can declare its recipient and behavior together.
            context = OTHER_DEVICE.split(source.quote, maxsplit=1)[0]
            result = decision(context)
            if result in ("old", "default"):
                matches.append((result, source, [source]))
            elif OTHER_DEVICE.search(source.quote):
                return dict(incomplete=True, reason="已知本页所用设备，仍需补充该设备自己的初始化要求。",
                            citations=[vars(source)])
    if matches and len({r[0] for r in matches}) == 1:
        result, source, evidence = max(matches, key=lambda item: item[1].sentence)
        if not pending or max(s.sentence for s in pending) <= source.sentence:
            return dict(resolved=result, citation=source, citations=[vars(s) for s in dict.fromkeys(evidence)])
    if not pending or len(rules) != 2 or len({r.name for r in rules}) != 2:
        if pending and physical and any(PHYSICAL.search(s.quote) for s in pending):
            names = "、".join(dict.fromkeys(name for name, _ in labels)) or "实际随附的设备或套件"
            return dict(incomplete=True, reason=f"实物归属待核对。请补全候选对象（{names}）各自的运行条件与初始化要求。",
                        citations=[vars(s) for s in dict.fromkeys([*(s for _, s in labels), *pending])])
        return None
    evidence = [vars(s) for s in dict.fromkeys([*(r.entity_source for r in rules), *(r.source for r in rules), *pending])]
    prompt = f"这份说明实际随哪个对象交付，是「{rules[0].name}」还是「{rules[1].name}」？"
    if {r.decision for r in rules} not in ({"old", "default"}, {"old", "pinned"}):
        return dict(incomplete=True, reason=prompt, citations=evidence)
    by_answer = {"old" if r.decision == "old" else "default": r for r in rules}
    return dict(decisionTarget="artifact", decisionGap="migration_purpose", question=prompt,
                questionChoices={answer: f"{r.name} · {r.policy}" for answer, r in by_answer.items()},
                choiceEvidence={answer: bindings.citation(r.source, r.policy) for answer, r in by_answer.items()},
                choiceCitations={answer: [bindings.citation(r.entity_source, r.name),
                                              bindings.citation(r.source, r.policy)] for answer, r in by_answer.items()},
                citations=evidence)
