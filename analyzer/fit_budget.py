"""Recognise an affirmative per-fit multi-start budget and its current mandate."""

import re

from . import bindings, intent, model_intent

CANDIDATE = r"(?:初始|起始|候选)(?:中心|质心|点|位置|方案|配置)|起点|初值"
DIRECT = re.compile(
    intent.N + r"\s*(?:组|套|份)\s*(?:不同的?|独立的?)?(?:" + CANDIDATE + r")"
)
INVERSE = re.compile(
    r"(?:"
    + CANDIDATE
    + r")(?:的)?(?:配置|方案|组合|数量)?(?:设(?:定|置)?|配(?:置)?|取|定)?(?:为|成|是|共|有)\s*"
    + intent.N
    + r"\s*(?:组|套|份)"
)
PER_FIT = re.compile(r"拟合|每(?:一)?(?:批|块|次调用|个窗口|个样本集)|聚类时")
RULE = re.compile(r"规则|规范|约定|必须|需要|要求|应当|固定|每.{0,10}(?:取|试|用|拟合)")
HISTORY = re.compile(
    r"以前|过去|上次|曾经|旧(?:版|规范|标准|例|教程|任务)|过往|历史|原先"
)
SIGNATURE = re.compile(r"签字|签批|签发|审批|工单|任务单|批准|核准")
EFFECTIVE = re.compile(
    r"(?:已经|已|正式)(?:签|确认|批准|核准|发布|生效|批准)|签字(?:生效|确认)|盖章(?:生效|确认)"
)
CARRY = re.compile(
    r"(?:延续|保持|遵循|维持|沿用|复现|对齐).{0,12}(?:旧|既有|之前|原有|历史|先前).{0,10}(?:预算|次数|口径|规约|规范|标准)"
)
INACTIVE = re.compile(
    r"仅供(?:参考|背景)|(?:此次|本次|此处).{0,4}不(?:送审|采用|执行|使用|适用)|无需(?:提交|执行|处理)|(?:不在|不属).{0,8}范围|另行处理"
)
PENDING = re.compile(
    r"未(?:签|批|定|授权|确认)|待(?:签|批|授权|确认)|尚待|还没|未获|谁(?:来|签|批准)|没有.{0,5}(?:签|确认|批准)|[？?]"
)
REVOKED = re.compile(
    r"已取消|已失效|已作废|已撤回|已撤销|不得沿用|不再(?:适用|采用|沿用|生效)|(?:拒绝|否决).{0,8}(?:旧|预算|要求)"
)


def unqualified(text):
    return not any(
        p.search(text)
        for p in (
            intent.QUALIFIED,
            intent.UNSETTLED,
            PENDING,
            REVOKED,
            bindings.POLICY_NEG,
        )
    )


def budget(text):
    # The qualifier must count *sets* of starts, not centers inside one set.
    return bool(
        (DIRECT.search(text) or INVERSE.search(text))
        and PER_FIT.search(text)
        and (intent.SELECTION.search(text) or model_intent.COMPARE.search(text))
        and unqualified(text)
        and not intent.FOREIGN_QUANTITY.search(text)
    )


def inspect(items):
    practices = [s for s in items if budget(s.quote)]
    if len(practices) != 1 or any(not unqualified(s.quote) for s in items):
        return None
    practice = practices[0]
    # Default behavior is compatible only when explicitly identified as background.
    for s in items:
        if (
            bindings.NEW.search(s.quote)
            or re.search(
                r"(?:库|新版|实现).{0,6}(?:自行|自动|自己)(?:决定|选)|只(?:试|跑|执行)一(?:次|套)",
                s.quote,
            )
        ) and not INACTIVE.search(s.quote):
            return None
    signatures = [
        s
        for s in items
        if SIGNATURE.search(s.quote)
        and EFFECTIVE.search(s.quote)
        and CARRY.search(s.quote)
        and not HISTORY.search(s.quote.split("已")[0])
    ]
    if (
        len(signatures) == 1
        and not any(intent.OTHER.search(s.quote) for s in signatures + [practice])
        and abs(signatures[0].sentence - practice.sentence) <= 2
    ):
        evidence = [
            signatures[0],
            practice,
            *[s for s in items if bindings.NEW.search(s.quote)],
        ]
        return (
            "candidate_claims",
            "已签发的当前预算引用旧规范，规范明确每次拟合从十套起点择优",
            evidence,
        )
    if (
        HISTORY.search(practice.quote)
        or not RULE.search(practice.quote)
        or SIGNATURE.search(" ".join(s.quote for s in items))
    ):
        return None
    return (
        "single_goal",
        "当前拟合规则明确从十组起点择优，计数单位为候选起点组",
        [practice],
    )


def peripheral(text):
    if INACTIVE.search(text):
        return True
    orthogonal = re.search(
        r"簇数|簇的数量|几个簇|随机种子|迭代(?:上限|次数|几轮|多少轮|轮数)|random_state|n_clusters|max_iter",
        text,
    )
    return bool(
        orthogonal
        and not (
            DIRECT.search(text)
            or INVERSE.search(text)
            or re.search(r"初始化|旧预算|终审|签批|授权", text)
        )
    )


def irrelevant_objection(items, origin, objections):
    """Only a verified single policy survives an objection exclusively about
    other parameters or an explicitly out-of-scope reference."""
    if not objections or not all(peripheral(c.get("quote", "")) for c in objections):
        return None
    cited = {
        (c.get("sentence"), c.get("line"), c.get("quote"))
        for c in origin.get("citations", [])
    }
    positions = origin.get("evidenceRoles", {})
    by_id = {s.sentence: s for s in items}
    practice = by_id.get(positions.get("practice"))
    commitment = by_id.get(positions.get("commitment"))
    if (
        not practice
        or not commitment
        or any(
            (s.sentence, s.line, s.quote) not in cited for s in (practice, commitment)
        )
    ):
        return None
    if not (
        DIRECT.search(practice.quote)
        or INVERSE.search(practice.quote)
        or intent.TEN.search(practice.quote)
    ):
        return None
    if not (
        model_intent.present_commitment(commitment.quote)
        or RULE.search(commitment.quote)
    ) or HISTORY.search(commitment.quote):
        return None
    remaining = [
        s for s in items if s not in (practice, commitment) and not peripheral(s.quote)
    ]
    if not all(unqualified(s.quote) for s in [practice, commitment, *remaining]):
        return None
    if any(bindings.NEW.search(s.quote) or PENDING.search(s.quote) for s in remaining):
        return None
    return [vars(s) for s in dict.fromkeys((practice, commitment))]
