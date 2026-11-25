"""Resolve local author/title-to-policy relations and independent approval statements."""

from dataclasses import dataclass

import re

from . import model_intent, referents

TITLE = re.compile(r"[《「“]([^》」”]{2,45})[》」”]")
REPORT = re.compile(
    r"报告|[周月季年快简速通]报|月结|小结|复核单|验收单|附录|附件|文稿|清单|说明书|明细表|核对表|汇总表|复盘|纪要"
)
# Consume title and optional alias together, before splitting policy clauses.
REPORT_TITLE = re.compile(
    rf"(?:另一份|第一份|第二份)?(?P<title>[\w\-]{{1,24}}?(?:{REPORT.pattern}))"
    r"(?:[（(](?:(?:又名|简称|别称|也叫)[：:]?\s*)?[《「“]?"
    r"(?P<parenthetical>[\w\-]{2,24})[》」”]?[）)]|"
    r"[，,]\s*(?:简称|又名|别称|也叫)[为是：:\s]*[《「“]?"
    r"(?P<short>[\w\-]{2,24})[》」”]?(?=[，,：:。；;]|$))?"
    r"(?=约定|写的|写明|注明|要求|采用|使用|展示|直接|规定|沿用|固定|保留|"
    r"主张|需要|希望|应|按|[，,：:。；;]|$)"
)
REPORT_SELECTED = re.compile(
    r"(?:题名|稿名|标题)(?:已|正式|最终)?(?:定为|选为|选定|确认为|填为|填写为|是|为|[：:])|"
    r"(?:已|正式|最终)(?:签收|批准送印|批准装订|确认交付|选定|选中)|"
    r"(?:本次|最终)(?:只)?(?:印发|送印|装订|提交|交付)|(?:获批|选中)(?:的是|题名为)"
)
REPORT_PENDING = re.compile(
    r"(?:批件|批复|送印单|装订单|稿名|题名).{0,8}(?:未到|未回|未填|未定|待定|待批|空缺)|"
    r"(?:待|缺|等候)(?:批件|批复)"
)


ALIAS = re.compile(
    r"(?:简称|也叫|别称|缩写|又名|也就是)[为叫是：:\s《「“]*([\w\u3400-\u9fff]{2,16})"
)
ATTRIBUTION = re.compile(
    r"^(.{1,25}?)(?:的(?:批注|意见|要求|方案|建议|规范|主张|指令)|坚持|主张|要求|建议|提出|批示|批注|注明|明确主张|希望)"
)
ROLE = re.compile(
    r"组|部|席|员|主管|主任|负责人|老师|编辑|代表|经理|工程师|审核|签发|主编|研究者|导师|专家|同学"
)
AUTH = re.compile(
    r"授权|终审|签发|签字|签名|会签|盖章|签章|审阅|裁定|裁决|签署|签批|签核|签定|拍板|选定|指定|决定|为准|勾选|定稿|交付|确认采用|以.{0,16}意见"
)
VACANT = re.compile(
    r"无人指定|没有.{0,8}栏|只.{0,8}一份|没(?:写|列|发)|尚未|暂未|未(?:签|填|勾|选|指定|交接|定|说|给)|空(?:着|白|缺)|漏(?:填|勾|签)|缺的是|缺少|谁|哪(?:位|人|份|种|一)|待定|等.{0,5}(?:签字|裁决)|没有.{0,8}(?:给|选|签|定|题名|名字)|只(?:说|叫|知|有)|不能判定"
)
INVALID = re.compile(
    r"不是|未授权|无权|未获|没有获得|不由|不得|并非|未被|未签|没签|假如|如果|假设|拟由|建议由|希望由|自称|自行宣称|过期|失效|作废|撤回|撤销|取消|曾经|上次|上一版|上期"
)
EXPIRE = re.compile(r"撤回|取消|撤销|作废|失效|不再有效|不再由|已过期")
COMMIT = re.compile(
    r"已(?:经)?(?:签|授权|指定|选|确认|决定|勾|批准|敲定|定稿)|已由|正式(?:授权|指定|委任|签|选|决定)|"
    r"(?:最终|本次|本期|本版|现在|此次|当前|终审|终签).{0,18}(?:由|归|以|选|交付|确定|采用|签)|"
    r"(?:授权|委任|指定|交给).{1,14}(?:签|审|裁定)|由.{1,18}(?:终审|签发|签批|裁定)|"
    r"(?:签发人|终审人|授权人|审阅人|选定题名|勾选项)[为是：:]|(?:确认为|签字同意|签署生效|盖章生效|最终采用|以.{1,18}为准)"
)
SEPARATE = re.compile(
    r"分别用于|各自运行|另一段代码|不同调用|互不影响|各跑一次|各跑各的"
)
CLAUSES = re.compile(r"[^，,：:]+")
OLD = re.compile(
    r"(?:照(?:旧|原来)|沿用|保留|维持|按以往|旧).{0,14}(?:次数|初始化|十|10|预算|重算|复算)|(?:十|10)\s*(?:轮|次初始|套中心|组起点|组初值|组初始(?:化|中心))|(?:重试|试|拟合)(?:十|10)次"
)
NEW = re.compile(
    r"默认|缺省|原生配置|开箱|出厂(?:配置|表现)|新安装.{0,8}(?:原样|直接运行)|(?:不加|不设|省略|不指定)(?:参数|初始化次数).{0,8}(?:效果|行为|表现)"
)
POLICY_NEG = re.compile(
    r"(?:不要|不应|不再|拒绝|否决).{0,12}(?:初始化|默认|缺省|旧版|十次)"
)
QUOTED_POLICY = re.compile(
    r"(?:不同意|否定|反对|不采纳|废止|取消).{0,10}(?:原|旧|新|默认|十)"
)
REFER = re.compile(r"前者|后者|第一(?:位|份|项|人)|第二(?:位|份|项|人)")


@dataclass(frozen=True)
class Claim:
    key: str
    aliases: tuple
    kind: str
    side: str
    entity: object
    rule: object
    policy_text: str


SIGNED_NAME = re.compile(r"([\u3400-\u9fff]{2,4})[（(]([^()（）]{2,16})[）)]")
SPEAKER = re.compile(
    r"(?:先发言的|随后|而后|另一位|另一名|而)?([^，；：。]{2,22}?)(?=坚持|主张|要求|批示|批注|要(?:求|发布|采用|保留|按)|提议|负责)"
)
ANONYMOUS = re.compile(
    r"^(?:则|应|要求|约定|写的是|规定|签发时|升级后|运行时|当前|本次|此处|按|要|给|用|呈现)|(?:初始化|默认|复算|重印|效果)$"
)


def descriptor(text):
    text = re.sub(r"^(?:[-*+] |\d+[.)] )", "", text.strip())
    names = TITLE.findall(text)
    # A book title bracket identifies a publication independently of its suffix.
    formal = re.search(r"《([^》]{1,45})》", text)
    if formal or (
        names
        and (REPORT.search(" ".join(names)) or re.search(r"报告|题名|文稿|标题", text))
    ):
        alias = ALIAS.search(text)
        title = formal[1] if formal else names[0]
        aliases = tuple(dict.fromkeys([title, *names] + ([alias[1]] if alias else [])))
        return title, aliases, "deliverable"
    bilingual = re.search(
        r"(?:([A-Za-z][A-Za-z0-9_-]{2,30})[（(]([^（）()]{2,18})[）)]|[“「]([^”」]{2,30})[”」][（(]([A-Za-z][A-Za-z0-9_-]{2,30})[）)])",
        text,
    )
    if bilingual:
        words = tuple(w for w in bilingual.groups() if w)
        return words[0], words, "artifact"
    signed = SIGNED_NAME.search(text)
    if signed and (
        ROLE.search(signed[2]) or re.search(r"(?:岗|席|主审|主检)$", signed[2])
    ):
        return signed[0], (signed[0], signed[1], signed[2]), "authority"
    speaker = SPEAKER.match(text)
    if (
        speaker
        and not ANONYMOUS.search(speaker[1])
        and (
            ROLE.search(speaker[1])
            or 2 <= len(speaker[1]) <= 3
            or re.search(
                r"(?:监制|主检|校核|主审|负责人|批准人)[\u3400-\u9fff]{2,3}$",
                speaker[1],
            )
        )
    ):
        name = speaker[1].removesuffix("的")
        return name, (name,), "authority"
    trailing = re.search(
        r"(?:这(?:条|项|个建议)|上述(?:要求|建议)|此项).{0,5}(?:由|来自)(.{2,18}?)(?:提出|签名|建议|批注|负责)",
        text,
    )
    owner = trailing or ATTRIBUTION.match(text.strip())
    label = (
        owner[1].strip()
        if owner
        else text.strip("：:。；; ")
        if len(text.strip()) < 20 and ROLE.search(text)
        else ""
    )
    plain_name = bool(
        owner
        and re.fullmatch(r"[\u3400-\u9fff]{2,3}", label)
        and not re.search(r"这个|本次|程序|本页|大家|代码|现在|这次|模型", label)
    )
    if (
        not label
        or ANONYMOUS.search(label)
        or not (ROLE.search(label) or plain_name)
        or VACANT.search(label)
        or (AUTH.search(text) and not owner and not ROLE.fullmatch(label))
    ):
        return None
    label = re.sub(r"^(?:而|但|另一边|另一方|同一份.+?的意见中)", "", label)
    aliases = [label]
    # 姓名或较短的职位可能在签发结论中独立出现；不任意抽取尾部汉字。
    match = re.search(
        r"(席|主管|负责人|专员|保管员|审核员|经理|老师|主任|工程师|代表|组长)(?:的)?([\u3400-\u9fff]{2,4})$",
        label,
    )
    if match:
        aliases.extend([match[2], label[: match.end(1)]])
    return label, tuple(aliases), "authority"


def report_clauses(text):
    offset = 0
    while offset < len(text):
        title = REPORT_TITLE.match(text, offset)
        start = title.end() if title else offset
        end = CLAUSES.match(text, start)
        stop = end.end() if end else start
        if stop > offset:
            yield text[offset:stop], title
        offset = stop + 1
        while offset < len(text) and text[offset].isspace():
            offset += 1


def claims(items):
    result = []
    current = None
    ordered_labels = []
    for s in items:
        if SEPARATE.search(s.quote):
            current = None
            continue
        titles = TITLE.findall(s.quote)
        if (
            len(titles) == 2
            and titles[0] != titles[1]
            and not ALIAS.search(s.quote)
            and not referents.ARTIFACT.search(" ".join(titles))
        ):
            ordered_labels = [(title, (title,), "deliverable", s) for title in titles]
        editions = re.search(
            r"([^，,；：:和与、]{1,10}(?:版|包|箱))和([^，,；：:的和与、]{1,10}(?:版|包|箱))",
            s.quote,
        )
        if editions:
            ordered_labels = [
                (editions[i], (editions[i],), "artifact", s) for i in (1, 2)
            ]
        roster = re.search(
            r"(?:两位|两名|两方)(?:负责人|签发人|审阅人|审核人|代表|老师)?(?:分别是|为|是|有)?(.{2,10}?)(?:和|与|、)(.{2,10}?)(?:参与|共同|均|都|负责|[。；，,:：])",
            s.quote,
        )
        if roster:
            ordered_labels = [(roster[i], (roster[i],), "authority", s) for i in (1, 2)]
        for piece, report in report_clauses(s.quote):
            part = piece.strip("。；;？！ ")
            if not part:
                continue
            # Words in an entity name (e.g. “原生风速表”) do not describe
            # executable policy. Evaluate only the remaining clause.
            requirement = TITLE.sub("", part)
            requirement = re.sub(
                r"[（(](?:又名|简称|别称)[^）)]*[）)]", "", requirement
            )
            if report:
                requirement = piece[len(report[0]):]
            ordinal = REFER.search(part)
            if (
                ordinal
                and len(ordered_labels) == 2
                and s.sentence - ordered_labels[0][3].sentence <= 3
            ):
                label = ordered_labels[int(bool(re.search(r"后者|第二", ordinal[0])))]
                current = label
                entity = None
            elif report:
                name = report["title"]
                aliases = tuple(n for n in (name, report["parenthetical"], report["short"]) if n)
                entity = name, aliases, "deliverable"
            else:
                entity = descriptor(part)
            if (
                not entity
                and not ordinal
                and len(part) <= 28
                and REPORT.search(part)
                and not (OLD.search(part) or NEW.search(part))
                and not any(p.search(part) for p in (AUTH, VACANT, SEPARATE))
            ):
                if (
                    not ANONYMOUS.search(part)
                    and not re.search(r"[的，：]|两个|两份|报告.*(?:要|将|包括)", part)
                    and REPORT.search(part).end() == len(part)
                ):
                    entity = part, (part,), "deliverable"
            if entity:
                current = (*entity, s)
                # A following attribution can name the author of a just-stated
                # policy (e.g. “这条由…提出”). It never reaches across another label.
                if (
                    re.search(
                        r"(?:这(?:条|项|个建议)|上述(?:要求|建议)|此项).{0,6}(?:由|来自)",
                        part,
                    )
                    and s.sentence > 1
                ):
                    prior = items[s.sentence - 2]
                    if (
                        not descriptor(prior.quote)
                        and not INVALID.search(prior.quote)
                        and not POLICY_NEG.search(prior.quote)
                    ):
                        sides = (
                            bool(OLD.search(prior.quote)),
                            bool(NEW.search(prior.quote)),
                        )
                        if sum(sides) == 1 and s.line - prior.line <= 1:
                            current_name, aliases, kind, _ = current
                            result.append(
                                Claim(
                                    current_name,
                                    aliases,
                                    kind,
                                    "old" if sides[0] else "default",
                                    s,
                                    prior,
                                    prior.quote,
                                )
                            )
            if (
                not current
                or s.sentence - current[3].sentence > (3 if ordinal else 1)
                or s.line - current[3].line > (3 if ordinal else 1)
            ):
                current = None
                continue
            if (
                INVALID.search(part)
                or POLICY_NEG.search(part)
                or QUOTED_POLICY.search(part)
            ):
                current = None
                continue
            old, new = bool(OLD.search(requirement)), bool(NEW.search(requirement))
            if old == new:
                continue
            name, aliases, kind, identity = current
            result.append(
                Claim(
                    name, aliases, kind, "old" if old else "default", identity, s,
                    requirement.strip("。；;？！ ") if report else part,
                )
            )
            current = None
    return result


FIELD_DECISION = re.compile(
    r"(?:签发栏|签批栏|终审栏|签发人)[：:]|(?:本机|本次交付|当前设备)(?:实际)?(?:使用|采用|选用)|决定只交|改由|后改为|定下只交|签发栏.{0,3}(?:填|写)"
)
SPECULATIVE = re.compile(
    r"可能|也许|请问|打算|有望|若|假如|有待|尚待|提议|建议最终|建议由|曾拟|拟议|草拟"
)
SIGNING_OPINION = re.compile(
    r"签了?(?:自己的)?(?:意见|建议|批注)|签(?:字|名).{0,5}(?:提议|建议)"
)
FINAL_AUTHORITY = re.compile(r"终审|获授权|签发栏|正式采纳")
OTHER_TASK = re.compile(
    r"(?:另一个|另一份|其他|旁边的|别的)(?:任务|项目|文件|报告|程序|调用|版本)"
)


def approval_statement(text, deliverable=False):
    if any(
        pattern.search(text) for pattern in (VACANT, INVALID, SPECULATIVE, OTHER_TASK)
    ):
        return False
    if SIGNING_OPINION.search(text) and not FINAL_AUTHORITY.search(text):
        return False
    if deliverable and REPORT_PENDING.search(text):
        return False
    return bool(
        COMMIT.search(text) or FIELD_DECISION.search(text)
        or (deliverable and REPORT_SELECTED.search(text))
    )


def approved(items, pair):
    ordered = sorted(
        pair, key=lambda c: (c.entity.sentence, c.entity.quote.find(c.key))
    )
    last_name = max(c.entity.sentence for c in pair)
    chosen = None
    conflict = False
    for sentence in items:
        # Keep the colon in a signed field. Commas can separate a superseding decision.
        for clause in re.split(r"[，,]", sentence.quote):
            mentioned = [
                claim for claim in pair if any(name in clause for name in claim.aliases)
            ]
            if (
                not mentioned
                and REFER.search(clause)
                and sentence.sentence >= last_name
            ):
                index = 1 if re.search(r"后者|第二", clause) else 0
                mentioned = [ordered[index]]
            if len(mentioned) != 1:
                continue
            claimant = mentioned[0]
            if EXPIRE.search(clause):
                if chosen and chosen[0] == claimant:
                    chosen = None
            elif approval_statement(clause, claimant.kind == "deliverable"):
                supersedes = re.search(
                    r"后改|改由|改为|取代|变更|重新指定|接替|最终改|现改", clause
                )
                if chosen and chosen[0] != claimant and not supersedes:
                    conflict = True
                elif supersedes:
                    conflict = False
                chosen = (claimant, sentence)
    return (None if conflict else chosen), conflict


def citation(sentence, quote):
    return {"sentence": sentence.sentence, "line": sentence.line, "quote": quote}


def choice_citations(claim):
    name = citation(claim.entity, claim.key)
    policy = citation(claim.rule, claim.policy_text)
    return [policy] if name == policy else [name, policy]


def heading_label(line):
    m = re.match(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
    if not m:
        return None
    text = m[1]
    entity = descriptor(text)
    if entity:
        return text
    if (
        len(text) <= 28
        and REPORT.search(text)
        and not re.search(r"两个|两份|为何|怎么|我|汇总如下", text)
    ):
        return text
    return None


def note_items(prose):
    # Reuse the Markdown fence/quote exclusions, admitting only meaningful
    # author or report headings. Reference lines remain literal in the original.
    lines = [heading_label(line) or line for line in prose.splitlines()]
    return model_intent.sentences("\n".join(lines))


def signed_default(items):
    # A signed scope change can settle a previously proposed behavior without
    # assigning a final reviewer by name. Require the scope, native behavior,
    # and evidence of actual supersession (not simply the newest sentence).
    for index, sentence in enumerate(items):
        if not re.search(r"重新签发|重新签署|正式签发|已盖章|已签署", sentence.quote):
            continue
        tail = items[index : index + 2]
        if any(p.search(s.quote) for p in (INVALID, SPECULATIVE, VACANT) for s in tail):
            continue
        selection = next(
            (
                s
                for s in tail
                if re.search(
                    r"(?:此处|这段|本次|当前).{0,10}(?:使用|采用|按|选用)", s.quote
                )
                and NEW.search(s.quote)
            ),
            None,
        )
        displaced = any(
            re.search(
                r"(?:另行|转给|移至|移交|转移).{0,12}(?:测试|实验|其他|另)", s.quote
            )
            for s in tail
        )
        if selection and displaced:
            return {
                "resolved": "default",
                "citation": selection,
                "citations": [vars(s) for s in tail],
            }
    return None


def inspect(prose):
    items = note_items(prose)
    if (
        not items
        or len(items) > 40
        or any(model_intent.CONTROL.search(s.quote.lower()) for s in items)
    ):
        return None
    findings = claims(items)
    for kind in ("authority", "deliverable", "artifact"):
        distinct = {(c.key, c.side): c for c in findings if c.kind == kind}
        candidates = list(distinct.values())
        if (
            len(candidates) != 2
            or candidates[0].side == candidates[1].side
            or candidates[0].key == candidates[1].key
        ):
            continue
        pair = sorted(candidates, key=lambda c: c.side == "default")
        if abs(pair[0].entity.sentence - pair[1].entity.sentence) > 6:
            continue
        first = min(c.entity.line for c in pair)
        last = max(c.rule.line for c in pair)
        if any(
            line.lstrip().startswith("#") and not heading_label(line)
            for line in prose.splitlines()[first:last]
        ):
            continue
        context = [
            s
            for s in items
            if min(c.entity.sentence for c in pair) - 3
            <= s.sentence
            <= max(c.rule.sentence for c in pair) + 4
        ]
        if any(SEPARATE.search(s.quote) for s in context):
            continue
        witnesses = [
            s
            for s in context
            if (
                AUTH.search(s.quote)
                or VACANT.search(s.quote)
                or (kind == "deliverable" and REPORT_PENDING.search(s.quote))
                or referents.SCOPE.search(s.quote)
            )
        ]
        outcome, conflicting_approvals = approved(context, pair)
        if outcome:
            choice, approval = outcome
            support = sorted(
                set([choice.entity, choice.rule, approval]), key=lambda s: s.sentence
            )
            return {
                "resolved": choice.side,
                "citation": approval,
                "citations": [vars(s) for s in support],
            }
        if (
            not conflicting_approvals
            and not any(VACANT.search(s.quote) or (kind == "deliverable" and REPORT_PENDING.search(s.quote))
                        for s in witnesses)
            and not (
                kind == "authority"
                and any(referents.SCOPE.search(s.quote) for s in witnesses)
            )
        ):
            continue
        if any(
            EXPIRE.search(s.quote)
            and not re.search(r"(?:未|没).{0,8}(?:撤|取消|过期)", s.quote)
            for s in context
        ):
            return {
                "incomplete": True,
                "reason": "有主张已撤回或授权已失效，缺少当前生效的签发决定。",
                "citations": [vars(s) for s in context],
            }
        options = {
            c.side: c.key
            + " · "
            + ("沿用旧初始化预算" if c.side == "old" else "采用新版默认")
            for c in pair
        }
        prompt = (
            "这次由谁终审"
            if kind == "authority"
            else "此脚本属于哪个包"
            if kind == "artifact"
            else "本次需要交付哪份报告"
        ) + f"，是「{pair[0].key}」还是「{pair[1].key}」？"
        citations = sorted(
            set(witnesses + [s for c in pair for s in (c.entity, c.rule)]),
            key=lambda s: s.sentence,
        )
        return {
            "decisionTarget": kind,
            "decisionGap": "requirement_owner"
            if kind == "authority"
            else "migration_purpose",
            "questionChoices": options,
            "question": prompt,
            "choiceCitations": {c.side: choice_citations(c) for c in pair},
            "choiceEvidence": {c.side: citation(c.rule, c.policy_text) for c in pair},
            "citations": [vars(s) for s in citations],
        }
    return signed_default(items)
