import React, {useEffect, useRef, useState} from "react";
import {api, importPayload, pendingJob} from "./library.mjs";
import BatchPanel from "./BatchPanel.jsx";
import "./library.css";

const jobsText={queued:"排队中",running:"正在构建",published:"已发布",failed:"构建失败",superseded:"已被新批次取代"};
const channelNames={bm25:"BM25",lexical:"词项匹配",dense:"向量召回",vector:"向量召回",semantic:"语义召回",ast:"代码调用",identifier:"标识符"};
function numberText(value){return typeof value==="number"?value.toFixed(4):"—";}
function ErrorLine({error}){return error ? <div className="lib-error" role="alert">{error}</div>:null;}

function ImportPanel({onChange}) {
  const [files,setFiles]=useState([]), [source,setSource]=useState(null);
  const [name,setName]=useState(""), [version,setVersion]=useState("");
  const [error,setError]=useState(""), [busy,setBusy]=useState(false), [message,setMessage]=useState("");
  const form=useRef(null);
  async function submit(e) {
    e.preventDefault();if(busy)return;
    setBusy(true);setError("");setMessage("");
    try {
      const data=await importPayload(files,source,name,version);
      const result=await api("/import",data);
      form.current?.reset();setFiles([]);setSource(null);setVersion("");setName("");
      setMessage("已提交索引任务 #"+result.id+"，目标为 G"+result.generation+"。");
      onChange();
    } catch(err) {setError(err.message);}
    finally {setBusy(false);}
  }
  return <section className="lib-card"><h2>导入 Markdown</h2>
    <form ref={form} onSubmit={submit}><fieldset disabled={busy}>
      <label className="field">笔记文件<input type="file" accept=".md,.markdown" multiple onChange={e=>setFiles([...e.target.files])}/></label>
      {files.length>0 && <p className="file-list">{files.map(f=>f.name).join(" · ")}</p>}
      <div className="lib-rule"></div><div className="field-pair">
        <label className="field">资料名称<input placeholder="例如 scikit-learn" value={name} onChange={e=>setName(e.target.value)}/></label>
        <label className="field">资料版本<input placeholder="例如 1.4" value={version} onChange={e=>setVersion(e.target.value)}/></label>
      </div>
      <label className="field">资料文件<input type="file" accept=".md,.markdown" onChange={e=>setSource(e.target.files[0]||null)}/></label>
      <p className="lib-hint">笔记和资料可分开导入。同一份资料沿用名称，分别填写版本号。支持 UTF-8 Markdown，单文件最多 100 KB。</p>
      <button className="btn primary">{busy?"正在导入…":"导入到资料库"}</button></fieldset>
    </form><ErrorLine error={error}/>{message&&<p className="lib-feedback" role="status">{message}</p>}
  </section>;
}

function JobPanel({db,onChange}) {
  const [busy,setBusy]=useState(null),[error,setError]=useState("");
  async function retry(id) {
    setBusy(id);setError("");
    try {await api("/jobs/"+encodeURIComponent(id)+"/retry",null);onChange();}
    catch(err){setError(err.message);} finally{setBusy(null);}
  }
  async function rebuild() {
    setBusy("all");setError("");
    try {await api("/reindex",null);onChange();}
    catch(err){setError(err.message);} finally{setBusy(null);}
  }
  return <section className="lib-card"><div className="lib-heading"><h2>索引任务</h2>
    {Boolean(db.activeGeneration) && <button className="btn secondary" disabled={busy!==null||db.jobs.some(pendingJob)} onClick={rebuild}>重建索引</button>}</div>
    {db.jobs.length ? <ul className="job-list">{db.jobs.map(j=><li key={j.id}><div className="job-info">
      <strong>G{j.generation} <span>任务 #{j.id}</span></strong><span className={"job-status "+j.status}>{jobsText[j.status]||j.status}</span>
      </div><small>{j.done} / {j.total} 篇笔记</small>
      {pendingJob(j)&&j.total>0&&<progress max={j.total} value={j.done} aria-label={"任务 "+j.id+" 的索引进度"}/>}
      {j.error&&<p className="job-error">{j.error}</p>}
      {j.status==="failed"&&<button className="btn secondary" disabled={busy!==null} onClick={()=>retry(j.id)}>{busy===j.id?"提交中…":"重试任务"}</button>}
    </li>)}</ul>:<p className="lib-hint">尚未提交索引任务。</p>}
    <ErrorLine error={error}/>
  </section>;
}

function Materials({db}) {
  return <details className="lib-card material-list"><summary>已发布的文件 <small>{db.notes.length} 篇笔记 · {db.sources.length} 个资料版本</small></summary>
    <h3>笔记</h3>{db.notes.length?<ul>{db.notes.map(n=><li key={n.filename}>{n.filename}</li>)}</ul>:<p>暂无笔记</p>}
    <h3>版本资料</h3>{db.sources.length?<ul>{db.sources.map(s=><li key={JSON.stringify([s.name,s.version])}>{s.name} · {s.version}<small>{s.filename}</small></li>)}</ul>:<p>暂无资料</p>}
  </details>;
}
function Hits({hits,openReview,busy}) {
  if (!hits.length) return <p className="lib-empty">已找到版本变更，当前索引中没有命中这条变更的笔记段落。</p>;
  return <><div className="results-title"><h3>候选笔记段落</h3><span>{hits.length} 段</span></div>
    <p className="lib-hint">以下段落与变更相关。请根据引用的上下文判断是否需要修改。</p>
    <div className="hit-list">{hits.map((hit,i)=><section className="hit" key={JSON.stringify([hit.filename,hit.startLine,hit.endLine,i])}>
      <div className="hit-title"><strong>{hit.filename}</strong><code>L{hit.startLine}–{hit.endLine}</code></div>
      {hit.heading&&<div className="hit-heading">{hit.heading}</div>}
      <pre>{hit.text}</pre><p>{hit.reason}</p>
      <details><summary>命中依据 · 综合得分 {numberText(hit.score)}</summary>
        <ul className="channels">{(hit.channels||[]).map((c,j)=><li key={c.name+j}>
          <strong>{channelNames[c.name.toLowerCase()]||c.name}</strong><span>排名 {c.rank} · 得分 {numberText(c.score)}</span>
          {c.terms?.length>0&&<small>{c.name==="AST"?"代码证据":"相关词项"} {c.terms.join("、")}</small>}
        </li>)}</ul>
      </details>
      <button className="btn secondary" disabled={busy} onClick={()=>openReview(hit.filename)}>审阅这篇笔记</button>
    </section>)}</div></>;
}
function ComparePanel({db,onReview}) {
  const [choice,setChoice]=useState({name:"",from:"",to:""});
  const [result,setResult]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState("");
  const flight=useRef(null);
  useEffect(()=>()=>flight.current?.abort(),[]);
  const names=[...new Set(db.sources.map(s=>s.name))];
  const name=names.includes(choice.name)?choice.name:names.find(n=>db.sources.filter(s=>s.name===n).length>1)||names[0]||"";
  const versions=db.sources.filter(s=>s.name===name).map(s=>s.version);
  const from=versions.includes(choice.from)?choice.from:versions[0]||"";
  const to=versions.includes(choice.to)?choice.to:versions.at(-1)||"";
  const change=result?.changes.find(c=>c.id===result.selectedChangeId);
  function choose(next) {flight.current?.abort();setChoice(next);setBusy(false);setError("");setResult(null);}
  async function openReview(filename) {
    setBusy(true);setError("");
    try {
      const note=await api("/reviews",{filename,search:{name,fromVersion:result.fromVersion,toVersion:result.toVersion,
        generation:result.generation,changeId:result.selectedChangeId}});
      await onReview(note.id);
    } catch(err){setError(err.message);}
    finally {setBusy(false);}
  }
  async function search(changeId) {
    if (!name || !from || !to || from===to) return;
    flight.current?.abort();
    const controller=new AbortController();flight.current=controller;
    setBusy(true);setError("");
    try {
      const body={name,fromVersion:from,toVersion:to};
      if (changeId!==undefined && result) {body.changeId=changeId;body.generation=result.generation;}
      const found=await api("/search",body,controller.signal);
      if (!controller.signal.aborted) {
        // Pin the compared pair when later imports publish additional versions.
        setChoice({name,from,to});
        setResult({...found,fromVersion:from,toVersion:to});
      }
    } catch(err){if(!controller.signal.aborted)setError(err.message);}
    finally {if(!controller.signal.aborted)setBusy(false);}
  }
  return <section className="lib-card compare"><div className="lib-heading"><h2>版本影响检索</h2><span>{db.activeGeneration ? "已发布索引 G"+db.activeGeneration : "尚无已发布索引"}</span></div>
    {db.jobs.some(pendingJob)&&<p className="lib-callout" role="status">{db.activeGeneration ? "索引正在构建，当前查询仍使用已发布的 G"+db.activeGeneration+"。" : "首个索引正在构建，发布后即可查询。"}</p>}
    <div className="compare-selects"><label className="field">选择资料<select value={name} onChange={e=>choose({name:e.target.value,from:"",to:""})}>
      {names.length?names.map(n=><option key={n}>{n}</option>):<option value="">暂无资料</option>}</select></label>
      <label className="field">旧版本<select value={from} onChange={e=>choose({name,from:e.target.value,to})}>{versions.map(v=><option key={v}>{v}</option>)}</select></label>
      <label className="field">新版本<select value={to} onChange={e=>choose({name,from,to:e.target.value})}>{versions.map(v=><option key={v}>{v}</option>)}</select></label></div>
    <button className="btn primary" disabled={busy||!name||from===to||!from||!to} onClick={()=>search()}>{busy?"正在检索…":"查找相关笔记"}</button>
    {versions.length<2&&<p className="lib-hint">导入同一份资料的两个版本，待索引发布后即可比较。</p>}
    {versions.length>=2&&from===to&&<p className="lib-hint">请选择两个不同版本。</p>}
    <ErrorLine error={error}/>
    {result&&<div className="search-results"><div className="lib-heading"><h3>变更对照</h3><span>查询快照 G{result.generation}</span></div>
      {result.generation!==db.activeGeneration&&<p className="lib-callout">新索引 G{db.activeGeneration} 已发布。再次点击「查找相关笔记」可更新下方结果。</p>}
      {result.changes.length===0?<p className="lib-empty">两个版本没有可比较的条款变更。</p>:<>
        <label className="field">变更条款<select disabled={busy} value={result.selectedChangeId??""} onChange={e=>search(result.changes.find(c=>String(c.id)===e.target.value)?.id)}>
          {result.changes.map((c,i)=><option key={c.id} value={c.id}>{i+1}. {c.heading||"未命名段落"}</option>)}</select></label>
        {change&&<div className="clause-diff"><div><span>旧版 · {result.fromVersion}</span><pre>{change.before||"此处新增条款"}</pre></div>
          <div><span>新版 · {result.toVersion}</span><pre>{change.after||"此处条款已移除"}</pre></div></div>}
        {result.encoder && <p className="lib-hint">向量编码器 · {result.encoder.startsWith("multilingual-minilm") ? "多语言 MiniLM（本地推理）" : result.encoder==="concept-hash-v1" ? "双语概念与词项向量" : result.encoder}</p>}
        <Hits hits={result.hits} openReview={openReview} busy={busy}/>
      </>}
    </div>}
  </section>;
}
const emptyDb={activeGeneration:0,notes:[],sources:[],jobs:[]};
export default function LibraryPane({onReview}) {
  const [db,setDb]=useState(emptyDb),[error,setError]=useState(""),[reload,setReload]=useState(0);
  const [task,setTask]=useState(()=>({id:new URLSearchParams(location.search).get("batch")}));
  const [demo,setDemo]=useState(null),[demoError,setDemoError]=useState("");
  const demoJob=db.jobs.find(job=>job.generation===demo);
  const indexStatus=demoJob?.status || (typeof demo==="number" && db.activeGeneration>demo ? "superseded" : "");
  function openBatch(id, scroll=false) {
    const url=new URL(location.href);
    url.searchParams.set("batch",id);
    history.replaceState(null,"",url);
    setTask({id:String(id),scroll});
  }
  useEffect(()=>{
    if (demo===null) return;
    if (indexStatus==="failed") {
      setDemoError(demoJob.error || "演示资料索引失败，请重新载入。");setDemo(null);
      return;
    }
    if (demo!=="start" && !["published","superseded"].includes(indexStatus)) return;
    const controller=new AbortController();
    async function openDemo() {
      try {
        const result=await api("/demo",null,controller.signal);
        if (controller.signal.aborted) return;
        if (result.id) {openBatch(result.id,true);setDemo(null);}
        else {
          setDb(current=>({...current,jobs:[result.job,...current.jobs.filter(job=>job.id!==result.job.id)]}));
          setDemo(result.generation);setReload(i=>i+1);
        }
      } catch(err) {
        if (!controller.signal.aborted) {setDemoError(err.message);setDemo(null);}
      }
    }
    openDemo();
    return ()=>controller.abort();
  },[demo,indexStatus,demoJob?.error]);
  useEffect(()=>{
    const controller=new AbortController();let timer;
    async function poll(){
      let delay=4500;
      try{
        const current=await api("",undefined,controller.signal);
        if (!controller.signal.aborted) {setDb(current);setError("");}
        if(current.jobs.some(pendingJob))delay=600;
      }catch(err){if(!controller.signal.aborted)setError(err.message);}
      finally{if(!controller.signal.aborted)timer=setTimeout(poll,delay);}
    }
    poll();
    return ()=>{controller.abort();clearTimeout(timer);};
  },[reload]);
  const refresh=()=>setReload(i=>i+1);
  return <main className="library"><div className="intro"><div><div className="crumb">工作空间 <span>/</span> 资料库</div><h1>资料库</h1></div>
    <div className="buttons"><button className="btn primary" disabled={demo!==null} onClick={()=>{setDemoError("");setDemo("start");}}>
      {demo===null?"载入演示数据":"正在载入演示…"}</button>
      <button className="btn secondary" onClick={refresh}>刷新资料库</button></div></div>
    {demo!==null&&<p className="lib-callout" role="status">正在准备五篇示例笔记和两个版本的资料，索引发布后将打开批量审阅。</p>}
    <ErrorLine error={demoError}/>
    <ErrorLine error={error}/>
    <div className="lib-columns"><div className="lib-side"><ImportPanel onChange={refresh}/><JobPanel db={db} onChange={refresh}/></div>
    <div className="lib-main"><BatchPanel key={task.id} db={db} task={task} onOpen={openBatch} demoLoading={demo!==null}/><ComparePanel db={db} onReview={onReview}/><Materials db={db}/></div></div>
  </main>;
}
