import React, {useEffect, useRef, useState} from "react";
import ApprovalPanel from "./ApprovalPanel.jsx";
import MappingQuestion from "./MappingQuestion.jsx";
import {getChoiceCitations} from "./choice-citations.mjs";
import {consumeTrace} from "./trace-stream.mjs";

const statusLabels = {
  complete: "调查完成",
  question: "等待回答",
  blocked: "调查受阻",
  paused: "检查点已保存"
};

async function requestError(response, fallback) {
  const body = await response.json().catch(() => null);
  const detail = body?.detail || body?.message || body?.error;
  return typeof detail === "string" ? fallback + " · " + detail : fallback;
}

function citationKey(line,sentence,quote,index) {
  return JSON.stringify([line,sentence,quote,index]);
}

function Citations({items, evidenceRoles}) {
  return items?.map(({line,sentence,quote},index)=>{
    const roles = [];
    if (evidenceRoles?.practice === sentence) roles.push("采用的做法");
    if (evidenceRoles?.commitment === sentence) roles.push("本次适用要求");
    return <blockquote key={citationKey(line,sentence,quote,index)}>
      <small>正文第 {line} 行 · 第 {sentence} 句{roles.length>0 && " · "+roles.join("、")}</small><p>{quote}</p>
    </blockquote>;
  });
}

const routeLabels = {
  user_answer:"用户确认",existing_decision:"此前的判读结论",single_goal:"单一适用目标",
  reference:"参照值核验",candidate_claims:"候选对象与各自要求",model_review:"模型核查",not_edit:"无需生成修改"
};
const outcomeLabels = {allow:"可以继续",ask:"需要你确认",blocked:"暂停调查",skip:"无需核查"};

function Applicability({check, evidenceRoles}) {
  if (!check) return null;
  return <section className="applicability" aria-label="适用对象核查">
    <strong>适用对象核查 · {outcomeLabels[check.outcome] || check.outcome}</strong>
    <p className="route">{routeLabels[check.route] || check.route}
      {typeof check.modelCalled==="boolean" && (check.modelCalled?" · 核查时调用了模型":" · 此项核查未调用模型")}</p>
    <p>{check.reason}</p>
    <Citations items={check.citations} evidenceRoles={evidenceRoles}/>
  </section>;
}

const intentOptions = [["old","保持旧版 10 次"],["default","采用新版默认"]];

function ReferenceEvidence({evidence}) {
  if (!evidence) return null;
  return <section className="applicability" aria-label="参照次数核对">
    <h4>参照次数核对</h4>
    <p>参照对象 · {evidence.reference || "待补充"}</p>
    <p>当前调用 · {evidence.currentCount ?? "待核实"}　参照次数 · {evidence.targetCount ?? "待核实"}</p>
    {evidence.source && <a href={evidence.source} target="_blank" rel="noreferrer">核对版本源码</a>}
    <Citations items={evidence.citations}/>
  </section>;
}

function IntentQuestion({question, disabled, answer}) {
  const evidence = getChoiceCitations(question);
  const choiceSources = Object.values(evidence).flat();
  const selected = question.answer;
  const shared = question.citations?.filter(citation =>
    !choiceSources.some(choice => choice.line === citation.line && choice.sentence === citation.sentence && choice.quote === citation.quote)
  );
  return <>
    <Citations items={shared}/>
    <div className="decision-options">{intentOptions.map(([id,fallback])=>{
      const label = question.questionChoices?.[id] || (selected===id && question.selectedChoice) || fallback;
      return <div className="decision-option" key={id}>
        {answer ? <button className={"btn "+(id==="old"?"primary":"secondary")} disabled={disabled} onClick={()=>answer(id)}>{label}</button> :
          <strong>{selected===id ? "你的选择 · "+label : label}</strong>}
        {question.decisionTarget==="artifact" && <p>{id==="old"
          ? "此选项会生成显式设置 n_init=10 的建议，供你核对后应用。"
          : "此选项会保留当前代码，继续使用该环境的默认初始化次数。"}</p>}
        <Citations items={evidence[id]}/>
      </div>;
    })}</div>
  </>;
}

function Trace({steps, live=false}) {
  return <>
    <h3 className="trace-title">{live?"调查进行中":"工具调用记录"} <small>{steps.length}</small></h3>
    <ol className="trace" aria-live={live?"polite":"off"}>{steps.map((step,i)=><li key={i}>
      <code className="tool">{step.tool}</code><p>{step.summary}</p>
      {step.tool==="read_intent" && step.method && <p>判读依据 · {({user_answer:"用户确认的选择",model:"模型判读",rule:"规则判读",guard:"正文安全检查",decision_gate:"需确认的使用条件",applicability:"适用范围核查",fit_budget:"单次拟合的初始化预算",candidate_bindings:"候选对象与要求核对",reference:"已查证的参照次数"})[step.method] || step.method}</p>}
      <Applicability check={step.applicability} evidenceRoles={step.evidenceRoles}/>
      <Citations items={step.citations?.filter(citation =>
        !step.applicability?.citations?.some(copy => copy.line===citation.line && copy.sentence===citation.sentence && copy.quote===citation.quote)
      )} evidenceRoles={step.evidenceRoles}/>
      {step.evidence && !step.citations?.length && <pre>{step.evidence}</pre>}
      {step.tool==="read_sources" && <div className="trace-sources">
        <a href="https://scikit-learn.org/1.1/modules/generated/sklearn.cluster.KMeans.html" target="_blank" rel="noreferrer">1.1 官方原文 ↗</a>
        <a href="https://scikit-learn.org/1.4/modules/generated/sklearn.cluster.KMeans.html" target="_blank" rel="noreferrer">1.4 官方原文 ↗</a>
      </div>}
    </li>)}</ol>
  </>;
}
export default function HarnessPane(props) {
  const key = "note-review:intent-mode:" + props.note.id;
  const [intentMode, setMode] = useState(()=>sessionStorage.getItem(key)==="model"?"model":"rule");
  return <>
    <div className="body"><label>意图判读方式 <select value={intentMode} disabled={props.busy} onChange={e=>{
      sessionStorage.setItem(key,e.target.value);
      setMode(e.target.value);
    }}>
      <option value="rule">规则判读</option>
      <option value="model">模型辅助判读</option>
    </select></label>
    {intentMode==="model" && <p className="hint">规则无法确定意图时，模型会从笔记正文寻找依据。本机服务可在项目目录运行 <code>./scripts/start-eval-model.sh 3b</code> 启动，默认端口 18087。</p>}
    </div>
    <Investigation key={intentMode} {...props} intentMode={intentMode}/>
  </>;
}

function Investigation({note, baseline, Diff, busy, setBusy, refresh, notify, editNewVersion, intentMode}) {
  const endpoint = "/api/notes/" + encodeURIComponent(note.id) + "/harness";
  const [run, setRun] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [live, setLive] = useState(null);
  const active = useRef(null);
  useEffect(() => () => active.current?.abort(), []);

  useEffect(() => {
    const controller = new AbortController();
    async function restore() {
      try {
        setLoading(true);
        setLoadError(false);
        setError("");
        const response = await fetch(endpoint+"?intentMode="+intentMode, {cache:"no-store", signal:controller.signal});
        if (!response.ok) throw Error(await requestError(response, "读取调查记录失败"));
        const result = response.status === 204 ? null : await response.json();
        if (controller.signal.aborted) return;
        if (result && (result.revision !== note.revision || (result.intentMode ?? "rule") !== intentMode)) {
          throw Error("笔记版本已经变化，请重新读取工作区。");
        }
        setRun(result);
      } catch(e) {
        if (!controller.signal.aborted) {
          setLoadError(true);
          setError(e.message);
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    restore();
    return () => controller.abort();
  }, [endpoint, note.revision, reload, intentMode]);

  async function submit(answer, pauseAfter, configFacts) {
    if (busy || loading) return;
    setBusy(true);
    setError("");
    notify("");
    const controller = new AbortController();
    active.current = controller;
    setLive(run?.status==="paused" ? run.trace : []);
    try {
      const data = {revision:note.revision,intentMode,decisionPolicy:run?.decisionPolicy};
      if (answer) data.answer = answer;
      if (configFacts) data.configFacts = configFacts;
      if (pauseAfter) data.pauseAfter=pauseAfter;
      const response = await fetch(endpoint + "/stream", {
        method:"POST",
        headers:{"Content-Type":"application/json",Accept:"text/event-stream"},
        signal:controller.signal,
        body:JSON.stringify(data)
      });
      if (response.status === 409) {
        await refresh();
        setReload(i=>i+1);
        notify("笔记版本或调查状态已变化，已重新读取。请核对最新结果。");
        return;
      }
      if (!response.ok) throw Error(await requestError(response, "调查未完成"));
      const result = await consumeTrace(response.body, step => {
        if (!controller.signal.aborted) setLive(steps => [...steps,step]);
      });
      if (result.revision !== note.revision || (result.intentMode ?? "rule") !== intentMode) {
        await refresh();
        throw Error("响应属于其他版本，请重新核对当前笔记。");
      }
      setRun(result);
    } catch(e) {
      if (!controller.signal.aborted && e.status === 409) {
        try {
          await refresh();
          setReload(i=>i+1);
          notify("调查期间版本已变化。请核对当前 Markdown 后继续。");
        } catch(refreshError) {setError(refreshError.message);}
      } else if (!controller.signal.aborted) setError(e.message);
    } finally {
      active.current = null;
      if (!controller.signal.aborted) setLive(null);
      setBusy(false);
    }
  }
  return <section className="body harness" aria-label="Agent 调查记录">
    <div className="harness-baseline"><span>{note.librarySources ? "导入笔记 · 索引 G"+note.generation : "固定流程 · 原始笔记"}</span><strong>{baseline}</strong><p>{note.reason}</p>{note.librarySources && <details><summary>核对导入的版本资料</summary>{Object.entries(note.librarySources).map(([side,source])=><section key={side}><strong>{source.filename} · {source.version}</strong><pre>{source.content}</pre></section>)}</details>}</div>
    <div className="harness-top"><h3>当前笔记调查 <code>r{note.revision}</code></h3>
      {run && <span className={"pill "+(run.status==="question"?"confirm":run.status==="blocked"?"change":"explicit")}>{statusLabels[run.status] || run.status}</span>}
    </div>
    {loading ? <p className="reason" role="status">正在读取调查记录…</p> : loadError ? <button className="btn secondary" disabled={busy} onClick={async()=>{
      try{await refresh();setReload(i=>i+1);}catch(e){setError(e.message);}
    }}>重新读取调查</button> : live!==null ? <Trace steps={live} live/> : !run ? <>
      <p className="reason">检查当前保存的 Markdown、参数调用和版本依据。调查完成后可审阅候选修改。</p>
      <div className="buttons start"><button className="btn primary" disabled={busy} onClick={()=>submit()}>开始调查</button>
      <button className="btn secondary" disabled={busy} onClick={()=>submit(null,2)}>运行两步后暂停</button></div>
    </> : <>
      {run.planner && <div className="planner">规划器 <code>{run.planner==="offline"?"本地规则":run.planner==="remote"?"模型工具调用":run.planner}</code></div>}
      <p className="reason">{run.reason}</p>
      <ReferenceEvidence evidence={run.referenceEvidence}/>
      {run.status==="paused" && <div className="checkpoint"><h4>检查点已保存</h4>
        <p>已保存 {run.checkpointSteps} 步。可关闭页面或重启本地服务（<code>./run.sh</code>），再回到这篇笔记。从下一步开始继续调查。</p>
        <button className="btn primary" disabled={busy} onClick={()=>submit()}>继续调查</button>
      </div>}
      {(run.resumedSteps>0 || run.clarification?.resumedSteps>0) && <p className="resumed">本次调查沿用了检查点中的 {run.resumedSteps || run.clarification.resumedSteps} 步。</p>}
      {run.status==="question" && <div className="clarify">
        <h4>需要你确认</h4><p>{run.question}</p>
        {run.questionType==="external_config" ? <MappingQuestion key={note.id+"-"+note.revision+"-"+run.mapping}
          mapping={run.mapping} fields={run.requiredFields} previous={run.configFacts} disabled={busy} submit={facts=>submit(null,null,facts)}/> :
        run.questionType==="reference_evidence" ?
        <button className="btn primary" disabled={busy} onClick={editNewVersion}>补充笔记中的参照依据</button> :
        <IntentQuestion question={run} disabled={busy} answer={submit}/>}
      </div>}
      {run.configFacts && <details className="clarify"><summary>查看已提交的外部配置</summary>
        <p><code>**{run.configFacts.mapping}</code></p>
        <p>init = <code>{run.configFacts.init}</code> · n_init = <code>{run.configFacts.n_init}</code></p>
      </details>}
      {run.clarification && <details className="clarify"><summary>查看本轮追问与回答</summary>
        <p>{run.clarification.reason}</p><p>{run.clarification.question}</p>
        <Applicability check={run.clarification.applicability}/>
        <IntentQuestion question={run.clarification}/>
      </details>}
      {run.status==="complete" && run.proposed && <><h3>当前版本的建议差异</h3><Diff original={note.current} proposed={run.proposed}/></>}
      {run.status==="blocked" && <button className="btn secondary" disabled={busy} onClick={()=>submit()}>重新调查</button>}
      <Trace steps={run.trace || []}/>
      {run.status==="complete" && <details className="next-version"><summary>如何再次演示断点恢复？</summary>
        <p>此版本已完成调查。可在另一篇笔记运行两步后暂停，也可编辑本篇并保存新版本后再调查。</p>
        <button className="btn secondary" disabled={busy} onClick={editNewVersion}>编辑当前笔记</button>
      </details>}
    </>}
    <ApprovalPanel intentMode={intentMode} note={note} run={loading||live!==null?null:run} endpoint={endpoint} busy={busy} setBusy={setBusy} refresh={refresh} notify={notify}/>
    {error && <div className="error" role="alert">{error} <button disabled={busy} onClick={()=>setReload(i=>i+1)}>刷新调查记录</button></div>}
  </section>;
}
