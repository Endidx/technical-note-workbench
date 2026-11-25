"""Join a note's named recipients to their requirements through local identifiers."""

from dataclasses import dataclass
from difflib import SequenceMatcher
import re

from . import binding_records, bindings, model_intent, object_scope

BOOK = re.compile(r"《([^》]{1,60})》")
PAREN = re.compile(r"[（(]([^（）()]{1,42})[）)]")
QUOTED = re.compile(r"[“「‘`\"]([^”」’`\"]{1,48})[”」’`\"]")
NAME = re.compile(r"[\w-]{1,28}?(?:" + object_scope.DEVICE + r"|" + bindings.REPORT.pattern +
                  r"|简讯|季刊|刊物|构建|分支|发行包|版本|固件)")
PREFIX = re.compile(r"^(?:另(?:一(?:台|份|个|套))?|第一(?:台|份)|第二(?:台|份)|台账(?:上)?(?:记载|列出)|登记(?:为|的是))")
REVERSED = re.compile(r"(?:对应(?:于)?|属于|指的是|(?:的|那台|那份|那版)(?:是|叫)|题名为|名为|名称为|叫做|记作|代表|→|=>)\s*$")
UNSET = re.compile(r"待定|尚待|未定|未知|没.{0,4}(?:定|到|拿到)|还在(?:找|等)|仍(?:在|待)|等.{0,8}(?:确认|回传|送来)|缺失|丢失|通用|共用|两(?:种|款|份|套).{0,6}(?:都|均|通用)|哪(?:个|种|款|份|台|一)")
LOCAL = re.compile(r"本(?:次|轮|页|批|稿|单|件|段|次部署)|这(?:次|张|一页|份|批|次部署)|此次|当前|实际|手上|手中|现场|最终|已(?:经)?(?:选定|签收|确认|核对|查明|选中)|送印单|交付单|回执|工单|发货单")
OBSERVED = re.compile(r"属|给|随|选|是|为|交付|发往|部署|发货|送印|印|贴|盖|刻|写|标|记|带|采用|使用|装|显示|对应|核对|查明|读到|收到|看到|可见|勾|绑定|取自|来自")
DOUBTFUL = re.compile(r"假设|假如|如果|倘若|可能|也许|可以|可(?:用|装|选)|任选|任一|均可|待|尚未|还没|并非|不是|不再|不能|无从|无法|没有|还在找|还在等|未能|未见|未读|未填|示例|模拟|推测|猜|传闻|涂销|撤回|取消|作废|草案|计划|拟(?:定|选|用|给)|曾经|原先|上次|上期|隔壁|邻机|别台|另一(?:张|份|台)")
SEPARATE = re.compile(r"各自.{0,6}(?:调用|脚本|运行)|另(?:一|外一)(?:处|段)调用")
STOP = re.compile(r"(?:的是|要求|使用|采用|初始化|默认|新版|升级|这一|两种|分别|固定|中心|保留|方案|设备|运行|对应|版本|渠道|标记|编号|那个|那一|的那|标识|应当|记为|代码|需要|按照|那台|那份|那组|分组|当前|标为|标有|带有|必须)")
TOKEN = re.compile(r"[a-zA-Z0-9_.+-]+|[\u3400-\u9fff]+")


@dataclass(frozen=True)
class Recipient:
    name: str
    aliases: tuple
    kind: str
    declaration: binding_records.Span
    features: str


@dataclass(frozen=True)
class Link:
    recipient: Recipient
    feature: str
    rule: binding_records.Span
    side: str


def policy(text):
    if DOUBTFUL.search(text) or bindings.POLICY_NEG.search(text) or model_intent.MITIGATION.search(text):
        return None
    side = object_scope.decision(text)
    if not side and not bindings.NEW.search(text) and (bindings.OLD.search(text) or model_intent.COUNT_REFERENCE.search(text)):
        side = "old"
    return side


def recipient(row):
    text = row.quote
    if DOUBTFUL.search(text) or LOCAL.search(text) or policy(text):
        return None
    formal = BOOK.search(text)
    bracket = PAREN.search(text)
    quoted = QUOTED.search(text)
    match = formal or quoted
    alias = []
    if bracket:
        alias_text = re.sub(r"^(?:简称|别称|又名|代号|缩写)(?:为|是)?", "", bracket[1]).strip("《》「」“” ")
        alias.append(alias_text)
    if match:
        name, start, end = match[1], match.start(), match.end()
        if quoted and not formal and not bracket and not (
            NAME.fullmatch(name) or name.isascii() or REVERSED.search(text[:start]) or start == 0
        ):
            return None
    elif bracket and bracket.start():
        name = PREFIX.sub("", text[:bracket.start()]).strip()
        pos = re.split(r"(?:对应|属于|的是|名为|叫作|→|=>)", name)
        name = pos[-1].strip()
        if not re.fullmatch(r"[\w.-]{1,35}", name):
            return None
        start, end = text.index(name), bracket.start()
    else:
        candidate = PREFIX.sub("", text)
        after = re.search(r"(?:对应|属于|的是|叫作|名为|→|=>)\s*([\w-]{1,35})$", candidate)
        match = NAME.fullmatch(after[1]) if after else NAME.match(candidate)
        if not match:
            return None
        name = match[0]
        # A device word inside a longer name is not itself the recipient.
        suffix = candidate[len(name):] if not after else ""
        if suffix and re.match(r"[\w-]", suffix) and not re.match(r"的|用|是|为|带|标|刻|印|贴|盖|配|属|采|发|走|装|背|挂|在|记|由|以|编|编号|有", suffix):
            return None
        start, end = text.index(name), text.index(name) + len(name)
    if bracket and bracket.start() >= end:
        end = bracket.end()
    features = text[:start] + " " + text[end:]
    if not features.strip():
        return None
    kind = "deliverable" if formal or bindings.REPORT.search(name) or re.search(r"刊|简讯", name) else "artifact"
    return Recipient(name, tuple(dict.fromkeys([name, *alias])), kind, row, features)


def shared_markers(left, right, competing):
    """Return contiguous identifiers present on both edges but absent on competing edges."""
    markers = set()
    for block in SequenceMatcher(None, left, right, autojunk=False).get_matching_blocks():
        overlap = left[block.a:block.a + block.size]
        for token in TOKEN.findall(overlap):
            if token.isascii() and not all(object_scope.named_in([token], t) for t in (left, right)):
                continue
            for value in STOP.split(token):
                if len(value) >= 2 and not any(value in text for text in competing):
                    markers.add(value)
    return markers


# Capabilities identify candidates even when a declaration says “可以连接”.
# Only an independent statement about the current example can select one.
DEVICE_NAME = re.compile(r"([\w.-]{1,24}?" + object_scope.DEVICE + r")[（(]([^（）()]{1,32})[）)]")
INVENTORY = re.compile(r"^(?:.*(?:送修|送检|列有|列出|包括|登记为|分别为|有两台)(?:了)?|(?:以及|或者|和|与|及|、))")
CAPABILITY = re.compile(r"(?:支持|具备|配有|装有|能(?:够)?|可以|只能|只|负责|用于|专门|背面有|带有|设有|接[入收]|读取|采集|处理|驱动|订阅|连接|输出|导出)")
BARE_DEVICE = re.compile(r"^([\w-]{1,24}?" + object_scope.DEVICE + r")(?=" + CAPABILITY.pattern + r")")
REVERSE_DEVICE = re.compile(r"(.+?)(?:的那台是|的是|的设备是)([\w-]{1,24}?" + object_scope.DEVICE + r")$")
INVALID_FACT = re.compile(r"若|未必|未(?:连接|接入|读取|使用|采用|收到|选定|选择|确认)|假如|假设|如果|可能|或许|也许|据说|原先|原计划|上次|尚未|并非|不是|没有|不能|无法|不支持")
ASSIGNED = re.compile(r"选定|选中|(?:已确定|已确认|已核实).{0,18}(?:是|为)|(?:交付|随箱|装箱|寄回|签收|收到|借出|发往|实际运行|实际使用|实际启动)(?:的|了|为|是)|随.{1,25}(?:交付|出货)|(?:寄|交|附|配|发)给|取自|来自|源自|摘自|导出自|从.{1,30}(?:生成|导出|导入|采集|读取|提取|抄录)|由.{1,30}(?:生成|导出|执行)|在.{1,30}(?:生成|执行)|(?:要给|用于|适用于|部署到|对应|归属|归入|随附)")
ROLE_ONLY = re.compile(r"负责|分工|各自|分别负责")
NO_SELECTION = re.compile(r"空值|空白|空着|为空|无值|缺省|无记录|未(?:填写|记录|选择|选定)|不(?:选|取自|来自|随|用)|未选|没.{0,8}(?:选|决定|填写|注明|写明)|未填|留白|空白|未圈|仍空|不详|尚未|待核|待查")
INSUBSTANTIAL = re.compile(r"接口|端口|输入|输出|模块|那台|设备|负责|可以|只能|终端|系统|工具|要求|采用|支持|独立|读取|数据|使用|接收|处理|连接|一台|本站")


def device_edges(rows, rules):
    """Collect inventory, capability and policy spans without assuming list order."""
    devices = {}
    facts = {}
    policies = {r for r, _ in rules}
    descriptions = [r for r in rows if r not in policies and not INVALID_FACT.search(r.quote)
                    and not LOCAL.search(r.quote) and not object_scope.LOCAL.search(r.quote)]
    for row in descriptions:
        text = row.quote
        declarations = []
        last = 0
        for match in DEVICE_NAME.finditer(text):
            name = INVENTORY.sub("", match[1]).strip()
            alias = re.sub(r"^(?:简称|别称|又名|代号)(?:为|是)?", "", match[2]).strip("「」“” ")
            if name:
                declarations.append((name, alias))
            last = match.end()
        if not declarations:
            direct = BARE_DEVICE.match(text)
            reverse = REVERSE_DEVICE.fullmatch(text)
            if reverse and CAPABILITY.search(reverse[1]):
                declarations.append((reverse[2], ""))
            elif direct and not any(name.endswith(direct[1]) for name in devices):
                declarations.append((direct[1], ""))
        for name, alias in declarations:
            devices[name] = (alias, row)
            facts.setdefault(name, [])
        if len(declarations) == 1 and CAPABILITY.search(text[last:]):
            facts[declarations[0][0]].append(row)
    if len(devices) != 2:
        return []
    names = list(devices)
    for name, (alias, declaration) in devices.items():
        for row in descriptions:
            if row == declaration:
                continue
            cap = CAPABILITY.search(row.quote)
            if cap:
                subject = row.quote[:cap.start()].strip("的")
                if len(subject) >= 2 and (subject == alias or [n for n in names if n.endswith(subject)] == [name]):
                    facts[name].append(row)
    if not all(facts.values()):
        return []

    def signature(name):
        alias, _ = devices[name]
        return [name, alias, *(r.quote for r in facts[name])]

    links = []
    for rule, side in rules:
        competing = [r.quote for r, s in rules if s != side]
        owners = []
        for name in devices:
            other = next(n for n in names if n != name)
            markers = set()
            for feature in signature(name):
                markers.update(shared_markers(feature, rule.quote, [*signature(other), *competing]))
            markers = {m for m in markers if not INSUBSTANTIAL.fullmatch(m)}
            if markers:
                alias, declaration = devices[name]
                owners.append((Link(Recipient(name, (name, alias) if alias else (name,), "artifact", declaration,
                                              " ".join(signature(name))), max(sorted(markers), key=len), rule, side),
                               tuple(dict.fromkeys(facts[name]))))
        if len(owners) == 1:
            links.extend(owners)
    return links if len(links) == 2 and len({l.recipient.name for l, _ in links}) == 2 else []


def named_feature_links(candidates, rules):
    links = []
    for rule, side in rules:
        opposite = [r.quote for r, s in rules if s != side]
        if not opposite:
            continue
        owners = []
        for candidate in candidates:
            others = [c.features for c in candidates if c != candidate]
            markers = shared_markers(candidate.features, rule.quote, [*others, *opposite])
            if markers:
                owners.append(Link(candidate, max(sorted(markers), key=len), rule, side))
        if len(owners) == 1:
            links.extend(owners)
    return links


def inspect(prose):
    items = bindings.note_items(prose)
    if any(model_intent.CONTROL.search(s.quote.lower()) or bindings.SEPARATE.search(s.quote)
           or SEPARATE.search(s.quote) for s in items):
        return None
    rows = binding_records.spans(items)
    rules = [(r, side) for r in rows if (side := policy(r.quote))]
    if len(rules) < 2:
        return None
    device = device_edges(rows, rules)
    if device:
        links = [link for link, _ in device]
    else:
        candidates = [c for r in rows if (c := recipient(r))]
        links = named_feature_links(candidates, rules)
    if len(links) != 2 or {link.side for link in links} not in ({"old", "default"}, {"old", "pinned"}):
        return None
    a, b = links
    if a.recipient.name == b.recipient.name or a.recipient.kind != b.recipient.kind:
        return None

    facts = dict(device)

    def chain(link):
        return [link.recipient.declaration, *facts.get(link, ()), link.rule]

    evidence = [edge for link in links for edge in chain(link)]
    pending, selected = [], []
    last_pending = -1
    for index, row in enumerate(rows):
        if row in evidence:
            continue
        if UNSET.search(row.quote) or bindings.VACANT.search(row.quote) or (device and NO_SELECTION.search(row.quote)):
            pending.append(row)
            last_pending = index
        context = re.sub(r"(?:本页|本次|下面(?:的)?)示例", "本页", row.quote) if device else row.quote
        if DOUBTFUL.search(context) or object_scope.MISSING.search(context) or UNSET.search(context):
            continue
        if device:
            if not (LOCAL.search(row.quote) or object_scope.LOCAL.search(row.quote)):
                continue
            if (not ASSIGNED.search(row.quote) or ROLE_ONLY.search(row.quote)
                    or NO_SELECTION.search(row.quote) or INVALID_FACT.search(row.quote)):
                continue
        elif not (LOCAL.search(row.quote) and OBSERVED.search(row.quote)):
            continue
        matches = []
        for link in links:
            labels = [*link.recipient.aliases, link.feature]
            if device:
                # Rules may use a shorter capability name. For an observation,
                # additionally admit the actual interface/input after the verb,
                # never an arbitrary overlap with a field or predicate name.
                other = next(l for l in links if l != link)
                for fact in facts[link]:
                    reverse = REVERSE_DEVICE.fullmatch(fact.quote)
                    description = reverse[1] if reverse else fact.quote
                    for match in CAPABILITY.finditer(description):
                        value = description[match.end():].strip("的 ")
                        if len(value) >= 2 and value not in other.recipient.features:
                            labels.append(value)
            if object_scope.named_in(labels, row.quote):
                matches.append(link)
        if len(matches) == 1:
            selected.append((matches[0], row, index))

    def citations(parts):
        return [vars(r) for r in dict.fromkeys(parts)]

    if selected and len({link.side for link, _, _ in selected}) == 1:
        link, proof, proof_index = selected[-1]
        if last_pending < proof_index:
            return dict(resolved=link.side, citation=proof,
                        citations=citations([*chain(link), proof]))
    labels = {"old" if link.side == "old" else "default": link for link in links}
    kind = a.recipient.kind
    target = "份报告" if kind == "deliverable" else "台设备" if device else "个对象"
    prompt = f"本页实际对应哪一{target}，是「{a.recipient.name}」还是「{b.recipient.name}」？"
    return dict(decisionTarget=kind, decisionGap="migration_purpose", question=prompt,
                questionChoices={k: f"{v.recipient.name} · {v.rule.quote}" for k, v in labels.items()},
                choiceEvidence={k: vars(v.rule) for k, v in labels.items()},
                choiceCitations={k: citations(chain(v)) for k, v in labels.items()},
                citations=citations([*evidence, *pending, *(row for _, row, _ in selected)]))
