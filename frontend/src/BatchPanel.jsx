import React, {useEffect, useMemo, useRef, useState} from "react";
import {api, libraryResponse} from "./library.mjs";
import {batchPair, changedLines} from "./library-batch.mjs";

const groupNames = {edit:"建议修改", keep:"保留原文", ask:"需要确认", irrelevant:"无关笔记"};
const statusNames = {running:"正在分析", complete:"分析完成", failed:"分析失败"};
const pathFor = id => "/batches/" + encodeURIComponent(id);

function SelectField({label, options, value, onChange}) {
  return <label className="field">{label}
    <select value={value} onChange={e => onChange(e.target.value)}>
      <option value="">请选择</option>
      {options.map(option => <option key={option}>{option}</option>)}
    </select>
  </label>;
}

function NoteDiff({original, proposed}) {
  const changes = useMemo(() => changedLines(original, proposed), [original, proposed]);
  if (!changes) return <div className="clause-diff">
    <div><span>原文</span><pre>{original}</pre></div><div><span>建议稿</span><pre>{proposed}</pre></div>
  </div>;
  if (!changes.length) return <p className="lib-hint">正文没有差异。</p>;
  return <div className="diff batch-diff" aria-label="修改前后差异">{changes.map(row =>
    <div className={row.kind} key={row.kind+row.line}>
      <span aria-label={row.kind==="minus"?"原文行":"建议稿行"}>{row.kind==="minus"?"−":"+"} L{row.line}</span>
      <code>{row.text || " "}</code>
    </div>
  )}</div>;
}

function NoteResult({item, onAccept, onClarify, busy, complete}) {
  const [draft, setDraft] = useState(null);
  return <section className="hit batch-note">
    <div className="hit-title"><strong>{item.filename}</strong>
      {item.accepted && <span className="saved">已接受</span>}
    </div>
    {item.reason && <p>{item.reason}</p>}
    {item.question && <p className="batch-question">待确认问题　{item.question}</p>}
    {item.status==="ask" && complete && <div className="batch-answer">
      {draft === null ? <button className="btn secondary" disabled={busy}
        onClick={()=>setDraft(item.clarificationDraft ?? item.original)}>补充依据</button> : <>
        <label className="field">补全配置或用途后的 Markdown
          <textarea rows={9} value={draft} disabled={busy} onChange={e=>setDraft(e.target.value)}/>
        </label>
        <div className="buttons"><button className="btn primary" disabled={busy || !draft.trim()}
          onClick={async()=>{if(await onClarify(item,draft)) setDraft(null);}}>重新调查本篇</button>
          <button className="btn secondary" disabled={busy} onClick={()=>setDraft(null)}>取消</button></div>
      </>}
    </div>}
    {item.status==="edit" && <NoteDiff original={item.original} proposed={item.proposed}/>}
    <details><summary>来源证据 · {item.evidence.length}</summary>
      {item.evidence.length ? <ul>{item.evidence.map((v,i) => <li key={i}>{v}</li>)}</ul> : <p>该笔记没有引用资料。</p>}
    </details>
    <details><summary>调查轨迹 · {item.trace.length}</summary>
      {item.trace.length ? <ol>{item.trace.map((v,i) => <li key={i}>{v}</li>)}</ol> : <p>暂无调查记录。</p>}
    </details>
    {item.status==="edit" && !item.accepted &&
      <button type="button" className="btn secondary" disabled={busy} onClick={() => onAccept(item.id)}>接受此修改</button>}
  </section>;
}

function BatchResults({batch, busy, onAccept, onExport, onClarify}) {
  const {status, items} = batch;
  return <div className="batch-results">
    <div className="lib-heading"><h3>批量审阅结果</h3><span role="status">{statusNames[status]} · {batch.done} / {batch.total} 篇</span></div>
    {batch.instruction && <p className="batch-intent">{batch.instruction}</p>}
    <div className="batch-context">
      {batch.name && <span>{batch.name} · {batch.fromVersion} → {batch.toVersion}</span>}
      {batch.generation != null && <span>任务快照 G{batch.generation}</span>}
    </div>
    <progress aria-label="批量分析进度" max={batch.total || 1} value={batch.done}/>
    {batch.error && <p className="lib-error" role="alert">{batch.error}</p>}
    {Object.entries(groupNames).map(([statusKey,label]) => {
      const group = items.filter(item => item.status === statusKey);
      return <div key={statusKey} className="batch-group">
        <h4>{label} <small>{group.length} 篇</small></h4>
        {group.map(item => <NoteResult key={item.id} item={item} onAccept={onAccept} onClarify={onClarify} busy={busy} complete={status==="complete"}/>)}
      </div>;
    })}
    {status==="complete" && <div className="batch-export">
      <button type="button" className="btn dark" disabled={busy} onClick={onExport}>导出 Markdown ZIP</button>
      <span>共 {batch.total} 篇，已接受 {items.filter(item => item.accepted).length} 篇修改。其余笔记保留原文。</span>
    </div>}
  </div>;
}

export default function BatchPanel({db, task, onOpen, demoLoading}) {
  const [instruction, setInstruction] = useState("帮我更新到目标版本");
  const [choice, setChoice] = useState({});
  const id = task.id;
  const resultAnchor = useRef(null);
  const scrolledTask = useRef(null);
  const [batch, setBatch] = useState(null), [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState(false), [loadError, setLoadError] = useState(""), [error, setError] = useState("");
  const {name, fromVersion, toVersion, names, versions} = batchPair(db.sources, choice);
  const canStart = Boolean(instruction.trim() && db.activeGeneration && db.notes.length && name && fromVersion && toVersion && fromVersion !== toVersion);
  useEffect(() => {
    if (!id) return;
    const controller = new AbortController();
    let timer;
    async function poll() {
      try {
        const result = await api(pathFor(id), undefined, controller.signal);
        if (controller.signal.aborted) return;
        setBatch(result); setLoadError("");
        if (result.status === "running") timer = setTimeout(poll, 800);
      } catch (err) {
        if (controller.signal.aborted) return;
        setLoadError(err.message);
        if (err.status !== 404) timer = setTimeout(poll, 4500);
      }
    }
    poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [task, refresh]);
  useEffect(() => {
    if (task.scroll && batch?.done && scrolledTask.current !== task) {
      resultAnchor.current?.scrollIntoView({block:"start"});
      scrolledTask.current = task;
    }
  }, [task, batch?.done]);

  async function start(e) {
    e.preventDefault();
    if (busy || !canStart) return;
    setBusy(true); setError("");
    try {
      const request = {instruction:instruction.trim(), name, fromVersion, toVersion, generation:db.activeGeneration};
      const created = await api("/batches", request);
      onOpen(created.id);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  async function accept(itemId) {
    if (busy) return;
    setBusy(true); setError("");
    try {
      await libraryResponse(pathFor(id) + "/items/" + encodeURIComponent(itemId) + "/accept", null);
      setBatch(current => ({...current, items:current.items.map(item =>
        item.id === itemId ? {...item, accepted:true} : item)}));
    } catch (err) { setError(err.message); }
    finally { setRefresh(n => n+1); setBusy(false); }
  }

  async function clarify(item, draft) {
    if (busy) return false;
    setBusy(true); setError("");
    try {
      await api(pathFor(id) + "/items/" + encodeURIComponent(item.id) + "/clarify",
        {draft, revision:item.clarificationRevision ?? 0});
      return true;
    } catch(err) {setError(err.message); return false;}
    finally {setRefresh(n=>n+1); setBusy(false);}
  }

  async function exportNotes() {
    if (busy) return;
    setBusy(true); setError("");
    try {
      const response = await libraryResponse(pathFor(id) + "/export");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url; link.download = "笔记更新-" + id + ".zip";
      document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  const running = batch?.status === "running" || Boolean(id && !batch && !loadError);
  return <section className="lib-card batch-workspace">
    <div className="lib-heading"><h2>批量更新笔记</h2><span>{db.activeGeneration ? "已发布索引 G"+db.activeGeneration : "等待索引发布"}</span></div>
    <form onSubmit={start}><fieldset disabled={busy || running || demoLoading}>
      <label className="field">更新指令<input value={instruction} onChange={e => setInstruction(e.target.value)} required/></label>
      <div className="compare-selects">
        <SelectField label="更新所用资料" value={name} options={names} onChange={name => setChoice({name})}/>
        <SelectField label="原版本" value={fromVersion} options={versions} onChange={v => setChoice({name, fromVersion:v, toVersion})}/>
        <SelectField label="目标版本" value={toVersion} options={versions} onChange={v => setChoice({name, fromVersion, toVersion:v})}/>
      </div>
      {!names.length || !db.notes.length ? <p className="lib-hint">导入笔记和同一份资料的两个版本，索引发布后即可开始。</p>
        : fromVersion && fromVersion===toVersion && <p className="lib-hint">请选择两个不同版本。</p>}
      <button className="btn primary" disabled={!canStart || busy || running}>开始批量更新</button>
    </fieldset></form>
    {error && <div className="lib-error" role="alert">{error}</div>}
    {loadError && <div className="lib-error" role="alert">{loadError} <button className="plain" onClick={() => setRefresh(n => n+1)}>重新读取任务</button></div>}
    {id && !batch && !loadError && <p className="lib-hint" role="status">正在读取批量任务…</p>}
    {batch && <div ref={resultAnchor}><BatchResults batch={batch} busy={busy} onAccept={accept} onExport={exportNotes} onClarify={clarify}/></div>}
  </section>;
}
