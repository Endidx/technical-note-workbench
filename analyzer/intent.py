"""Conservative, evidence-bearing intent rules for the KMeans initialization upgrade.

Combine a quantity or default target with an authorial requirement and its scope.
Unsupported or contradictory statements leave the review pending.
"""
from dataclasses import dataclass
import re
import unicodedata


@dataclass(frozen=True)
class Finding:
    intent: str
    summary: str
    evidence: str


FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
OTHER = re.compile(r"(?:其他|其它|别的|外部|上游|隔壁|另一(?:个|套|支)?)(?:的)?(?:服务|项目|团队|环境|仓库|系统)|"
                   r"教程(?:中|里)|文档(?:中|里)(?:说|写|的例子)|(?:another|other) (?:team|project|service)")
LOCAL = re.compile(r"(?:本|该|这个|这段|这份|这套|我们的|当前的?)(?:段|项目|例|笔记|调用|服务|环境|脚本|手册|代码|实验)|"
                   r"(?:this|our) (?:project|example|service|environment|snippet)")
PAST = re.compile(r"曾(?:经)?|以往|过去|当时|当年|之前|上次|那次|那时|以前|旧资料|旧笔记|used to|previously|formerly")
CURRENT = re.compile(r"现在|如今|仍|依然|继续|本次|这次|以后|升级后|迁移后|新环境|\b(?:still|now|must)\b")
VERSION = re.compile(r"(?<![.\d])1\.1\.3(?![.\d])")
PIN = re.compile(r"锁(?:定|在|死)|钉(?:死|在)|固定(?:在|为|使用)?|依赖.{0,12}==|仍(?:用|在用|运行)|"
                 r"保持在|停留在|不升级|(?:pin(?:ned)?|stays? on|remains? on)")
ARCHIVE = re.compile(r"历史记录|(?:仅|只)(?:用于|供|记录|作).{0,10}(?:记录|归档|回溯|追溯|留档|复盘)|"
                     r"留档|原始记录|历史快照|历史截图|archive[ds]?|historical record")
MODAL = re.compile(r"需|须|要求|约定|务必|验收|请(?!求)|目标|目的|期望|希望|决定|要(?:求|做|跑|试|用|保|从|继续|沿用|跟随)|"
                   r"仍|继续|沿用|保留|固定|保持|维持|遵循|跟随|采用|对齐|复现|照旧|照常|直接|专门|打算|"
                   r"\b(?:must|shall|should|keep|preserve|retain|require[ds]?|want|use|follow|adopt)\b")
NEGATIVE = re.compile(r"不(?:必|要|再|用|需(?:要)?|应(?:该)?|打算|希望|采用|保留|允许|接受|能|可|锁定|跟随|沿用|执行|会保持)|"
                      r"无(?:须|需)|禁止|避免|放弃|拒绝|取消|\b(?:not|never|avoid|without|don't)\b")
UNSETTLED = re.compile(r"是否|要不要|待定|未(?:确定|决定|达成一致|敲定|拍板)|还没(?:想好|决定|定)|暂未|待(?:讨论|确认)|尚无定论|"
                       r"二选一|[？?]|\b(?:undecided|unclear|whether)\b")
# Preserve exact quantity. In particular, neither '二十次' nor a random seed of 10 is a ten-start requirement.
N = r"(?<![\d.零一二两三四五六七八九十百千])(?:10|十|\bten\b)(?![\d.零一二两三四五六七八九十百千])"
INITIAL = r"(?:初始化|重启)"
CENTERS = r"(?:初始|起始)(?:聚类)?(?:中心|质心)"
MODIFIER = r"(?:(?:不同|独立|随机|候选)(?:的)?\s*){0,2}"
TEN = re.compile(
    # Counting groups of starting centers or independent starts is distinct from
    # counting the centers inside one fit (n_clusters).
    N + r"\s*(?:次|轮|遍)\s*" + MODIFIER + INITIAL
    + r"|" + N + r"\s*(?:组|套)\s*" + MODIFIER + CENTERS
    + r"|" + INITIAL + r"(?:的)?(?:次数|轮数)\s*(?:(?:固定|设定|设置|设|保持|限定|必须|要|为|在|是|仍)\s*){0,4}" + N
    + r"|" + INITIAL + r"(?:要|需|必须|仍|重复|执行|做|跑|为|设为){0,4}\s*" + N + r"\s*(?:次|遍|轮)"
    + r"|" + CENTERS + r".{0,6}(?:做|进行|重复|执行|尝试)\s*" + N + r"\s*(?:次|轮)(?:试验|尝试|实验|启动|初始化)"
    + r"|\bn_init\s*(?:==?|为|设为|固定为)\s*" + N
    + r"|" + N + r"\s+(?:independent\s+|random\s+)?(?:initiali[sz]ations?|starts?|restarts?)\b"
)
QUALIFIED = re.compile(r"如果|假设|倘若|若需|如需|有时|可选|考虑是否|考虑用|不确定|上限|最多|至多|不超过|至少|不低于|大约|或许|"
                       r"(?:至少|最多|大约|约)\s*(?:10|十)|\b(?:if|unless|perhaps|at most|up to|at least)\b")
INFO_ONLY = re.compile(r"查(?:清|明|询|阅)|需要(?:知道|了解)|尚待核实|以供参考|资料称|文档(?:称|写)|需要比较|"
                       r"\b(?:check whether|investigate|look up|compare whether)\b")
OLD_TARGET = re.compile(r"(?:旧版|原先|原有|原来|之前|原版|上一版|历史)(?:的)?(?:默认(?:的)?)?"
                        r"(?:初始化次数|初始化策略|重启次数|起始中心数量)|"
                        r"(?:previous|old|original) (?:number of )?(?:initiali[sz]ations|restarts|starts)")
NEW_DEFAULT = re.compile(r"(?:新(?:版(?:本)?|环境)|发行版|该版本|升级后|迁移后|1\.4(?:\.\d+)?|库)(?:本身|的|库|版本|自带|原生|内置|当前|下|自身|现在|提供的|建议的|采用的)*"
                         r"(?:默认|缺省)|(?:默认|缺省)(?:行为|策略|设置|配置|参数)?(?:就)?(?:按|采用|跟随)(?:新|1\.4)|"
                         r"(?:new|upgraded|1\.4(?:\.\d+)?) (?:library )?defaults?|\bn_init\s*=\s*['\"]auto['\"]")


# Components of a multi-start policy. A quantifier binds to sets of starting
# configurations or to runs inside one fit, never to individual cluster centers.
CANDIDATE_GROUP = re.compile(
    N + r"\s*(?:组|套|批)\s*" + MODIFIER
    + r"(?:起点|初始点|初值|起始点|(?:初始|起始)(?:簇|中心|质心)|候选(?:簇|中心|质心)|(?:聚类)?中心|质心)"
)
RUN_COUNT = re.compile(
    r"(?:各自|独立|分别|重复|试跑|重跑|启动|运行|跑足|做足)\s*(?:跑|执行|启动|进行)?\s*"
    + N + r"\s*(?:遍|轮|次)|" + N + r"\s*(?:次|轮)\s*(?:不同的|独立的?)?(?:启动|起跑|试跑|初始化)"
)
START_OBJECT = re.compile(r"初始化|起始(?:中心|点|簇)|初始(?:中心|点|簇)|质心|候选中心|(?:多个|不同|随机|的)起点|n_init")
SELECTION = re.compile(r"择优|选优|取优|最佳|最优|最好的?|胜出|取其中|选一组|惯量.{0,8}(?:最低|最小)|"
                       r"误差.{0,8}(?:最低|最小)|目标函数.{0,8}(?:最低|最小)|best (?:run|result|inertia)")
PER_FIT = re.compile(r"一次拟合|单次拟合|每(?:个|一|次|个样本)?(?:批|次|周期|窗口|时段|类目|拟合|调用|请求|模型)|per fit")
PROCEDURE = re.compile(r"生成|准备|使用|评估|比较|挑选|选取|抽取|启动|分配|试跑|出发|采取|得到|执行|运行")
BUDGET = re.compile(r"预算|口径|验收|协议|硬(?:性|约束)|约定|规定|定额|必须|务必|固定条件|保证|务求")
POLICY = re.compile(r"沿用|维持|延续|保持|对齐|复现|兼容|不变|不动|照旧|有效|一致|相同|继续执行")
LEGACY = re.compile(r"旧(?:版本?|环境|库|系统|行为|默认)|原(?:有|先|来)(?:的)?(?:库|版本|默认)|1\.1(?:\.3)?")
DEFAULT_BEHAVIOR = re.compile(r"默认(?:初始化(?:次数|行为|策略)|值|次数|行为|策略|配置|参数|设置|语义)|缺省(?:值|次数|行为|设置|配置)|"
                              r"(?:省略|不传|未设置|未指定).{0,10}(?:n_init|初始化次数)")
FOREIGN_QUANTITY = re.compile(
    N + r"\s*(?:次|遍|轮|组|套)?\s*(?:计时|测速|测时|耗时采样|网络|请求延迟|模型|时段|数据集|交叉验证|折|采样窗口|簇数|类别|类目)"
    + r"|(?:计时|测速|耗时采样|网络请求|交叉验证|整个脚本|整个程序)\s*(?:跑|运行|重复|测量)?\s*" + N
    + r"\s*(?:次|遍|轮)|(?:random_state|随机种子)\s*(?:==?|设为|为|固定为)?\s*" + N
)
CHOICE_SUBJECT = re.compile(r"初始化|起点|n_init|用途|目标|口径|方案|模式|入口|默认|两者|其一|哪[个种一]|"
                            r"(?:采用|执行|遵循|采用哪|以哪|继续用)|尚未拍板|未定稿")
HISTORY_ONLY = re.compile(r"旧系统|(?<!新)旧环境|旧版(?:下|中|会)|过去|当时|那时|原先|此前|曾经|以往")
BUDGET_REF = re.compile(r"(?:这个|这条|此|上述|之前的|初始化|启动|尝试)(?:的)?(?:次数|预算|约定|口径)|"
                        r"(?:预算|次数).{0,12}(?:照旧|继续有效|保持不变|不得改变)")
NUM_GROUP = re.compile(N + r"\s*(?:组|套)(?=\s*(?:$|[，,。;；：:]|以便|来|进行|参与|并|选))")


def multi_start_policy(sentence, previous):
    """Resolve a bounded local relation between quantity, object and acceptance criterion."""
    if OTHER.search(sentence) or FOREIGN_QUANTITY.search(sentence):
        return False
    if (HISTORY_ONLY.search(sentence) and not CURRENT.search(sentence)
            and not (POLICY.search(sentence) and re.search(r"必须|务必|要求|验收|硬性|当前",sentence))):
        return False
    requirement = (MODAL.search(sentence) or BUDGET.search(sentence)
                   or (PER_FIT.search(sentence) and PROCEDURE.search(sentence)))
    if not requirement:
        return False
    if LEGACY.search(sentence) and DEFAULT_BEHAVIOR.search(sentence) and POLICY.search(sentence):
        return True
    if LEGACY.search(sentence) and POLICY.search(sentence) and START_OBJECT.search(sentence) and re.search(r"次数|预算|份数|轮数|组数",sentence):
        return True
    individual_starts = re.search(N + r"\s*个\s*" + MODIFIER + r"(?:随机起点|起点|初始方案|独立起跑)",sentence)
    if individual_starts and PER_FIT.search(sentence) and SELECTION.search(sentence):
        return True
    if CANDIDATE_GROUP.search(sentence):
        # A set of centers is only initialization evidence when the note either
        # names the start object or says to compare the candidate solutions.
        return bool(START_OBJECT.search(sentence) or SELECTION.search(sentence) or "试" in sentence)
    if START_OBJECT.search(sentence) and RUN_COUNT.search(sentence) and (SELECTION.search(sentence) or PER_FIT.search(sentence)):
        return True
    if START_OBJECT.search(sentence) and NUM_GROUP.search(sentence) and BUDGET.search(sentence):
        return True
    # One adjacent authored sentence can define the quantity to which "this
    # initialization budget" refers. Never inherit a hypothetical/maximum.
    if previous and BUDGET_REF.search(sentence) and POLICY.search(sentence):
        return bool((TEN.search(previous) or CANDIDATE_GROUP.search(previous))
                    and not (QUALIFIED.search(previous) or NEGATIVE.search(previous)
                             or UNSETTLED.search(previous) or FOREIGN_QUANTITY.search(previous)))
    return False


def paragraphs(markdown):
    """Skip examples/quotations while retaining actual prose lines as evidence."""
    fence = None
    lines = []
    for line in markdown.splitlines():
        marker = FENCE.match(line)
        if marker:
            delim, tail = marker.groups()
            if fence is None:
                fence = delim
            elif delim[0] == fence[0] and len(delim) >= len(fence) and not tail.strip():
                fence = None
            continue
        if fence or line.lstrip().startswith(("#", ">")) or line.startswith(("    ", "\t")):
            continue
        if line.strip():
            lines.append(line.strip())
        elif lines:
            yield lines
            lines = []
    if lines:
        yield lines


def infer(markdown, answer=None):
    positive, negative, speculative = {}, {}, {}
    seen_lines = []
    for lines in paragraphs(markdown):
        seen_lines.extend(lines)
        # Scope propagation is confined to a paragraph. A new local subject
        # supersedes a preceding description of a different project.
        external = False
        previous = previous_line = ""
        for line in lines:
            normalized = unicodedata.normalize("NFKC", line).casefold().replace("`", "")
            for sentence in re.split(r"[。!！;；]|(?<!\d)\.\s+", normalized):
                if not sentence.strip():
                    continue
                undecided = bool(UNSETTLED.search(sentence) or QUALIFIED.search(sentence) or INFO_ONLY.search(sentence))
                # A pending choice of purpose can appear after an otherwise clear
                # description of one option, without repeating the option itself.
                if (UNSETTLED.search(sentence) and CHOICE_SUBJECT.search(sentence)
                        and not OTHER.search(sentence) and (not external or LOCAL.search(sentence))):
                    speculative.setdefault("choice", line)
                if (not external or LOCAL.search(sentence)) and multi_start_policy(sentence,previous):
                    budget_bucket = speculative if undecided else negative if NEGATIVE.search(sentence) else positive
                    quote = line
                    if previous_line and previous_line != line and not multi_start_policy(sentence,""):
                        adjacent = previous_line + "\n" + line
                        if adjacent in markdown:
                            quote = adjacent
                    budget_bucket.setdefault("old",quote)
                for clause in re.split("[，,]", sentence):
                    local = list(LOCAL.finditer(clause))
                    other = list(OTHER.finditer(clause))
                    if local or other:
                        external = bool(other and (not local or other[-1].start() >= local[-1].start()))
                    if external or not clause.strip():
                        continue
                    past_only = PAST.search(clause) and not CURRENT.search(clause)
                    negative_clause = NEGATIVE.search(clause)
                    targets = []
                    if VERSION.search(clause) and not past_only and PIN.search(clause):
                        targets.append("pinned")
                    if VERSION.search(sentence) and ARCHIVE.search(sentence) and not negative_clause:
                        targets.append("history")
                    if not past_only and MODAL.search(clause):
                        if TEN.search(clause) or OLD_TARGET.search(clause):
                            targets.append("old")
                        if NEW_DEFAULT.search(clause):
                            targets.append("default")
                    for target in targets:
                        bucket = speculative if undecided else negative if negative_clause else positive
                        bucket.setdefault(target,line)
                previous = sentence if not external and not OTHER.search(sentence) else ""
                previous_line = line if previous else ""

    active = set(positive)
    protected = active and active <= {"pinned", "history"}
    incompatible = bool(active & set(negative)) or bool(speculative)
    if protected and not incompatible:
        kind = "pinned" if "pinned" in active else "history"
        return Finding(kind,"正文将该段限定在旧版本或历史记录中",positive[kind])
    if answer in ("old", "default"):
        return Finding(answer,"读取用户对当前笔记版本的选择",
                       "保留旧版 10 次初始化" if answer == "old" else "采用新版默认")
    if len(active)==1 and not incompatible and not protected:
        kind = next(iter(active))
        return Finding(kind,"核对了该段的适用范围、目标行为与明确要求",positive[kind])
    witnesses = list(dict.fromkeys([*positive.values(), *negative.values(), *speculative.values()]))
    return Finding("unknown", "需要核实适用范围、迁移目标或互相冲突的要求",
                   "\n".join(witnesses or seen_lines)[:500])
