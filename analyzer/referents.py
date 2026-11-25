"""Bind each migration behavior to the note's selectable object or authority."""
from dataclasses import dataclass
import re

from . import decision_gate as legacy, model_intent


@dataclass(frozen=True)
class Branch:
    side: str
    text: str
    source: model_intent.Sentence
    owner: str
    descriptor: model_intent.Sentence = None

    @property
    def label(self):
        if self.descriptor:
            return self.descriptor.quote.rstrip("：:") + " · " + self.text
        return self.text

    def citation(self):
        return {"sentence":self.source.sentence,"line":self.source.line,"quote":self.text}


ARTIFACT = re.compile(r"(?:[\w./-]+\.(?:py|ipynb|md|zip|ya?ml|toml|json)|(?:实验|项目|发布|练习)?包(?!括|含)|文件|目录|脚本|版本号|分支|副本|附件|入口|快捷方式|模板|后缀|路径|文件名|文件夹)")
MISSING_ID = re.compile(r"截(?:掉|断|去)|缺(?:了|少)|只(?:有|给|剩|发|写|留)|未(?:标|填|说|写|区分)|没(?:有)?(?:标|填|说|写|给|带|区分)|同名|重名|不全|模糊|相同|共用|同一(?:个)?(?:编号|代码|编码)")
CHOOSE = re.compile(r"哪(?:一|种|个|份|件|边)|问清|弄清|待确认|先确认|没决定|未(?:明|定)|不知道|不清楚|不确定|未指定|未说明|没说|没给|未说")
ALTERNATE = re.compile(r"另一个|另一(?:份|套|个|件|支|种)|一个.{0,100}(?:另|一个)|一份.{0,100}一份|既.{0,70}也|可能.{0,70}可能|还是|二选一|两(?:份|个|种|套)")
SCOPE = re.compile(r"共用|同一|同次|两方|双方|两边|两份合同|都指向|都对|都必须|都还有效|共同|不能.{0,6}(?:分开|拆分|再跑)")
NEW = re.compile(r"默认|缺省|开箱|出厂|原生|新版.{0,8}(?:原样|直接运行)|新安装.{0,12}(?:设置|配置)|不显式固定")
OLD = re.compile(r"旧(?:版|的|十|预算|行为|结果|报告|流程|例|图|照)|复现|复刻|还原|重做|对齐旧|(?:十|10)\s*(?:组起|次初始|轮预算|套初)")
CUT = re.compile(r"[，,：:。！？!?；;]|(?=另一个|另一份|还是|或是|或者|也可能)")
DENIED = re.compile(r"拒绝|被否决|已撤|撤回了|已取消|不再|放弃|原本打算|假设|曾经建议")
CLOSED = re.compile(r"最终|已经(?:明确|确定|决定|定稿)|已定稿|已选定|已选择|确认选择|确定用|指定用|最后决定|现已|确定交|确认要交|已确认|现在只|这次只|本次只|这次确定|以.{0,15}为准")
IDENTIFIER = re.compile(r"`[^\n`]{1,45}`|[《「“][^》」”]{1,45}[》」”]|[A-Za-z][\w.-]*[./_-][\w.-]+")
DISCRIMINATOR = re.compile(r"文件名|后缀|前缀|路径|版本号|项目编码|任务编号|运行编号|编号|编码|名称")
PAIR_OBJECT = re.compile(r"两(?:个|份|本|条|套|种|张|项|支)(?:同名的?)?([^，。；：:]{1,12})")

TECH_ONLY = re.compile(r"^(?:保留|显式设置|采用|使用|改用|保持|仍用)?\s*(?:旧版的?)?(?:十|10)\s*次初始化[。！]?$|^(?:采用|使用|改用)?(?:新版本?的?)?默认(?:设置|行为|配置)?$")
ACTION_PREFIX = re.compile(r"^(?:另一个|另一份|一个|一份|也可能|既可能|可能|还是|或是|或者|也用于|既用于)")
OWNER = re.compile(r"^(.{1,20}?)(?:坚持|让我|要求|想让我|主张|建议|却要|要(?:下次|采用|保留|固定|直接)|希望)")


def branches(items):
    output=[]
    for s in items:
        last_end = 0
        separators = list(CUT.finditer(s.quote))
        for stop in [*separators, None]:
            end = stop.start() if stop else len(s.quote)
            raw = s.quote[last_end:end]
            last_end = stop.end() if stop else end

            words=raw.strip()
            if not words or len(words)>100 or DENIED.search(words) or legacy.DISTINCT.search(words):
                continue
            old=bool(OLD.search(words) or legacy.policies(words)[0])
            new=bool(NEW.search(words))
            if old==new:
                continue
            clean=ACTION_PREFIX.sub("",words).strip()
            clean=re.sub(r"^[^，,；;：:]{1,12}既用于","",clean).strip()
            if not clean or len(clean)>70:
                continue
            left = s.quote[:end-len(raw)]
            key = re.search(r"(`[^`]{1,40}`|[《「“][^》」”]{1,40}[》」”]|[\w.-]{1,30}\.(?:py|md|zip|ipynb))[：:]\s*$",left)
            if key:
                clean=s.quote[key.start(1):end].strip()
            elif left.endswith(("，",",")):
                preceding = re.split(r"[，,：:；;]",left[:-1])[-1]
                names = list(IDENTIFIER.finditer(preceding))
                if len(names)==1 and (re.search(r"名为|叫|文件名|路径|后缀|包名|另一(?:个|份|支)(?:是)?",preceding) or preceding.strip()==names[0][0]):
                    start=end-len(raw)-1-len(preceding)+names[0].start()
                    clean=s.quote[start:end].strip()
            who=OWNER.match(words)
            owner=who[1] if who and not re.search(r"可能|过去|上次|代码|参数",who[1]) else ""
            descriptor = None
            if s.sentence > 1 and not owner:
                prior = items[s.sentence-2]
                if (s.line == prior.line+1 and prior.quote.endswith(("：",":"))
                        and len(prior.quote)<=32):
                    subject=prior.quote[:-1].strip()
                    if IDENTIFIER.search(subject) or re.search(r"组|部|方|团队|老师|负责人|编辑|主管|员",subject):
                        descriptor = prior
                        if not IDENTIFIER.search(subject):
                            owner = subject
            output.append(Branch("old" if old else "default",clean,s,owner,descriptor))
    return output


def examine(prose, previous=None):
    """Return a grounded clarification, a prior decision, or no extra finding."""
    items=model_intent.sentences(prose)
    if not items or len(items)>40 or any(model_intent.CONTROL.search(s.quote.lower()) for s in items):
        return previous
    text=" ".join(s.quote for s in items)
    candidates=branches(items)
    if previous and "resolved" in previous:
        return previous
    pending=[s for s in items if CHOOSE.search(s.quote) or MISSING_ID.search(s.quote)]
    together=[s for s in items if SCOPE.search(s.quote) and not legacy.DISTINCT.search(s.quote)]
    sections={}
    section=0
    for n,line in enumerate(prose.splitlines(),1):
        if legacy.SEPARATE_LINE.match(line):
            section+=1
        sections[n]=section
    options=ALTERNATE.search(text)
    pairs=[(a,b) for a in candidates if a.side=="old" for b in candidates if b.side=="default"
           and sections[a.source.line]==sections[b.source.line] and a.text!=b.text and abs(a.source.sentence-b.source.sentence)<=4]
    conflict=next(((a,b) for a,b in pairs if a.owner and b.owner and a.owner!=b.owner),None)
    if conflict and together and (not previous or previous.get("decisionGap")=="requirement_owner"):
        pair=conflict
        target="authority"
        witnesses=together+[s for s in pending if CHOOSE.search(s.quote)]
    elif pairs and (pending or (CLOSED.search(text) and all(IDENTIFIER.search(c.label) for c in pairs[0]))) and (options or previous or any(IDENTIFIER.search(c.label) for c in candidates)):
        pair=min(pairs,key=lambda p:abs(p[0].source.sentence-p[1].source.sentence))
        artifact=next((s for s in items if ARTIFACT.search(s.quote) and (
            MISSING_ID.search(s.quote) or re.search(r"(?:两个|两份|两套|两个同名|两条).{0,8}"+ARTIFACT.pattern,s.quote))),None)
        if not artifact and all(IDENTIFIER.search(c.label) for c in pair):
            artifact = next((s for s in items if ARTIFACT.search(s.quote)),None)
        target="artifact" if artifact and (not previous or previous.get("decisionGap")!="requirement_owner") else "deliverable"
        witnesses=[s for s in pending if CHOOSE.search(s.quote) or MISSING_ID.search(s.quote)]
        if artifact:
            witnesses.append(artifact)
    else:
        # A truncated pointer to multiple artifacts is not permission to adopt
        # the sole migration policy documented for one of them.
        if (not pairs and options and pending and ARTIFACT.search(text)
                and DISCRIMINATOR.search(text) and any(CHOOSE.search(s.quote) for s in pending)
                and not any(CLOSED.search(s.quote) for s in items)):
            return {"incomplete":True,"reason":"笔记提到多个候选对象，但缺少至少一个对象与初始化行为的对应引文。请补全标识或该对象的要求。",
                    "citations":[vars(s) for s in items if s in pending or any(c.source==s for c in candidates)]}
        return previous
    a,b=pair
    # A later statement assigning the task is stronger than a former ambiguity.
    last_requirement=max(a.source.sentence,b.source.sentence)
    decision=legacy.resolution(items,last_requirement+1,{"old":a.owner,"default":b.owner})
    if decision:
        return decision
    for s in reversed(items):
        if s.sentence<=last_requirement or not CLOSED.search(s.quote) or CHOOSE.search(s.quote):
            continue
        selected=[c for c in pair if any(m[0].strip("`《》「」“”") in s.quote for m in IDENTIFIER.finditer(c.label))]
        if len(selected)==1 and not DENIED.search(s.quote):
            return {"resolved":selected[0].side,"citation":s}
    for clause in items:
        if clause.sentence <= last_requirement or not DENIED.search(clause.quote):
            continue
        retired = [c for c in pair if (c.owner and c.owner in clause.quote)
                   or any(m[0].strip("`《》「」“”") in clause.quote for m in IDENTIFIER.finditer(c.label))]
        if retired:
            # One veto does not establish that the remaining candidate was commissioned.
            return {"incomplete":True,"reason":"正文撤回了一个候选要求，尚缺本次采用另一项要求的决定。请补充当前授权。",
                    "citations":[vars(s) for s in sorted({a.source,b.source,clause},key=lambda x:x.sentence)]}
    if any(CLOSED.search(s.quote) and not (CHOOSE.search(s.quote) or legacy.MISSING.search(s.quote))
           for s in items if s.sentence >= last_requirement):
        return previous
    if target!="authority" and any(TECH_ONLY.fullmatch(c.text) and not c.descriptor for c in pair):
        return previous
    if any(legacy.DISTINCT.search(s.quote) and re.search(r"各自|互不影响|分别用于",s.quote) for s in items):
        return previous
    witnesses.extend(c.descriptor for c in pair if c.descriptor)
    citations=sorted(set([a.source,b.source,*witnesses]),key=lambda s:s.sentence)
    choices={side.side:side.label for side in pair}
    if target=="authority":
        question=f"同一运行以哪一方的要求为准，是「{a.label}」还是「{b.label}」？"
    else:
        thing="这次需要交付哪项成果"
        if target=="artifact":
            object_match = PAIR_OBJECT.search(artifact.quote)
            noun = "文件或包"
            if object_match:
                category = ARTIFACT.search(object_match[1])
                if category:
                    noun = category[0]
            if noun!="文件或包":
                choices={side.side:(side.label if noun in side.label or IDENTIFIER.search(side.label)
                                    else noun+" · "+side.label) for side in pair}
            thing=f"本次指的是哪个{noun}"
        key=next((DISCRIMINATOR.search(s.quote)[0] for s in witnesses if DISCRIMINATOR.search(s.quote)),None)
        if key:
            thing=f"目前的{key}无法区分两个候选。"+thing
        question=f"{thing}，是「{a.label}」还是「{b.label}」？"
    return {"decisionGap":"requirement_owner" if target=="authority" else "migration_purpose",
            "decisionTarget":target,"questionChoices":choices,"question":question,
            "choiceEvidence":{side.side:side.citation() for side in pair},
            "citations":[vars(s) for s in citations]}
