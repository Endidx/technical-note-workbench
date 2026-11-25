import React, {useEffect, useState} from "react";
import {createRoot} from "react-dom/client";
import {zipSync, strToU8} from "fflate";
import "./style.css";
import HarnessPane from "./HarnessPane.jsx";
import LibraryPane from "./LibraryPane.jsx";

const kindName = {imported:"导入笔记",change:"建议修改", explicit:"已显式设置", history:"历史记录", confirm:"需要确认", unsupported:"固定流程未覆盖"};
const resultName = {accept:"已接受", keep:"已保留", pending:"待审阅"};
const sources = [
  ["1.1", "10", "旧版默认值", "https://scikit-learn.org/1.1/modules/generated/sklearn.cluster.KMeans.html"],
  ["1.4", "'auto'", "新版默认值", "https://scikit-learn.org/1.4/modules/generated/sklearn.cluster.KMeans.html"]
];
function download(name, data, type) {
  const url = URL.createObjectURL(new Blob([data], {type}));
  const a = document.createElement("a");
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}
async function readNotes() {
  const response = await fetch("/api/notes", {cache:"no-store"});
  if (!response.ok) throw Error("读取笔记失败，请检查本地服务后重试。");
  return response.json();
}
function Icon({name, size=18}) {
  const paths = {
    book:<><path d="M3 4.5c3-1 6-.5 9 1.5 3-2 6-2.5 9-1.5v14c-3-1-6-.5-9 1.5-3-2-6-2.5-9-1.5z"/><path d="M12 6v14"/></>,
    file:<><path d="M6 3h8l4 4v14H6z"/><path d="M14 3v5h4M9 13h6M9 16h5"/></>,
    export:<><path d="M12 3v12m-4-4 4 4 4-4M4 15v5h16v-5"/></>,
    external:<><path d="M13 4h7v7m0-7L10 14M10 5H5v15h15v-5"/></>,
    check:<path d="m4 12 5 5L20 6"/>,
    arrow:<path d="M4 12h16m-6-6 6 6-6 6"/>,
    layers:<><path d="m12 3 9 5-9 5-9-5zM3 12l9 5 9-5M3 16l9 5 9-5"/></>,
    undo:<><path d="m9 4-5 5 5 5M4 9h9a6 6 0 0 1 0 12"/></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}
function Diff({original, proposed}) {
  let a=original.split("\n"), b=proposed.split("\n"), start=0, endA=a.length, endB=b.length;
  while(start<endA && start<endB && a[start]===b[start]) start++;
  while(endA>start && endB>start && a[endA-1]===b[endB-1]) {endA--;endB--;}
  return <div className="diff" aria-label="修改前后差异">
    {[[a.slice(start,endA),"−","minus"],[b.slice(start,endB),"+","plus"]].flatMap(([lines,sign,cls]) => lines.map((v,i)=><div className={cls} key={cls+i}><span aria-hidden="true">{sign}</span><code>{v || " "}</code></div>))}
  </div>;
}
function Workbench() {
  const params = new URLSearchParams(location.search);
  const [library,setLibrary]=useState(()=>params.get("view")==="library");
  const [notes,setNotes]=useState([]);
  const [selected,setSelected]=useState(()=>new URLSearchParams(location.search).get("note"));
  const [tab,setTab]=useState(()=>[params.get("view"),params.get("review")].includes("harness")?"harness":"review");
  const [busy,setBusy]=useState(false), [error,setError]=useState(""), [loading,setLoading]=useState(true);
  const [notice,setNotice]=useState(""), [draft,setDraft]=useState(null);
  async function refresh(){setNotes(await readNotes());}
  async function load(){
    setLoading(true);setError("");
    try { setNotes(await readNotes()); } catch(e){setError(e.message);}
    finally {setLoading(false);}
  }
  useEffect(()=>{load();},[]);
  const note=notes.find(n=>n.id===selected) || notes[0], reviewed=notes.filter(n=>n.decision!=="pending").length;
  useEffect(()=>{
    const url=new URL(location.href);
    if(note) url.searchParams.set("note",note.id);
    if(library) url.searchParams.set("view","library");
    else if(tab==="harness") url.searchParams.set("view","harness");
    else url.searchParams.delete("view");
    if(library && tab==="harness") url.searchParams.set("review","harness");
    else url.searchParams.delete("review");
    history.replaceState(null,"",url);
  },[note?.id,tab,library]);
  function pick(id){setDraft(null);setSelected(id);setTab("review");setNotice("");setError("");}
  async function decide(decision) {
    if(busy || !note) return;
    setBusy(true);setError("");setNotice("");
    try {
      const r=await fetch("/api/notes/"+encodeURIComponent(note.id),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({decision,revision:note.revision})});
      if(r.status===409){setNotes(await readNotes());setError("工作区版本或建议对应的段落已变化。请核对当前 Markdown，再决定是否保留原文。");return;}
      if(!r.ok) throw Error("保存失败。请重新读取工作区，核对状态后再试。");
      setNotes(await readNotes());setNotice(decision==="pending"?"已撤销审阅，可重新选择。":"审阅决定已保存。");
    } catch(e){setError(e.message);} finally{setBusy(false);}
  }
  async function saveDraft() {
    if (busy || !draft) return;
    setBusy(true);setError("");
    try {
      const r=await fetch("/api/notes/"+encodeURIComponent(note.id)+"/edit",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({current:draft.text,revision:draft.revision})});
      if(r.status===409){setNotes(await readNotes());setError("此笔记已更新，草稿仍在编辑器中。请复制需保留的内容，取消后重新编辑最新版本。");return;}
      if(!r.ok) throw Error("保存失败，请核对内容后重试。");
      setNotes(await readNotes());setDraft(null);setNotice("手动编辑已保存，请重新核对修改建议。");
    } catch(e){setError(e.message);} finally{setBusy(false);}
  }
  async function exportNotes(all){
    setBusy(true);setError("");
    try {
      const latest=await readNotes();setNotes(latest);
      if(all){
        const files=Object.fromEntries(latest.map(n=>[n.librarySources ? n.id+"/"+n.filename : n.filename,strToU8(n.current)]));
        download("技术笔记-Markdown.zip",zipSync(files),"application/zip");
      } else {
        const item=latest.find(n=>n.id===note.id);
        download(item.filename,item.current,"text/markdown;charset=utf-8");
      }
      setNotice("已导出当前保存的 Markdown。");
    } catch(e){setError(e.message);} finally{setBusy(false);}
  }
  return <>
    <header className="top"><div className="topinner"><div className="identity"><span className="mark"><Icon name="book" size={22}/></span><b>技术笔记工作台</b></div><span className="headerline"></span><span className="workspace">本地工作空间</span>
      <nav className="app-navigation" aria-label="工作空间导航">
        <button aria-current={!library?"page":undefined} disabled={busy||draft!==null} onClick={()=>setLibrary(false)}>示例审阅</button>
        <button aria-current={library?"page":undefined} disabled={busy||draft!==null} onClick={()=>setLibrary(true)}>资料库</button>
      </nav></div></header>
    {library?<LibraryPane onReview={async id=>{await refresh();pick(id);setTab("harness");setLibrary(false);}}/>:<main>
      <div className="intro"><div><div className="crumb">工作空间 <span>/</span> 变更审阅</div><h1>笔记更新审阅</h1></div>
      <button className="btn dark" disabled={busy||draft!==null||!notes.length} onClick={()=>exportNotes(true)}><Icon name="export"/>导出全部 Markdown</button></div>
      <section className="source"><div className="source-main"><div className="source-name"><Icon name="layers"/><span>上游变更</span><b>scikit-learn</b></div><h2>KMeans <small>/</small> n_init</h2><p>默认初始化次数在 1.4 版改为 <code>'auto'</code>。使用默认的 k-means++ 初始化时，仅运行一次。</p></div>
        <div className="version-pair">{sources.map(([version,value,label,href],i)=><React.Fragment key={version}>{i===1&&<span className="arrow"><Icon name="arrow" size={16}/></span>}<a href={href} target="_blank" rel="noreferrer" title={"打开 scikit-learn "+version+" 官方文档"}><small>{label} · {version}</small><strong>{value}</strong><span>官方文档 <Icon name="external" size={12}/></span></a></React.Fragment>)}</div>
      </section>
      {error&&<div className="error" role="alert">{error} <button onClick={load} disabled={busy}>重新读取</button></div>}
      {!note ? <section className="empty">{loading?"正在读取工作区…":error?"工作区暂时不可用":"当前没有可审阅的笔记。"}</section> :
      <div className="grid"><aside><div className="queuehead"><h2>笔记队列</h2><span>{reviewed} / {notes.length} 已审</span></div><progress aria-label="审阅进度" max={notes.length} value={reviewed}/>
        <nav aria-label="选择笔记">{notes.map(n=><button key={n.id} className={"item "+(n.id===note.id?"selected":"")} aria-current={n.id===note.id?"true":undefined} disabled={busy||draft!==null} onClick={()=>pick(n.id)}><span className="fileicon"><Icon name={n.decision==="pending"?"file":"check"}/></span><span className="itemtext"><strong>{n.title}</strong><small><i className={"dot "+(n.decision==="pending"?n.kind:"done")}/>{n.decision==="pending"?kindName[n.kind]:resultName[n.decision]}</small></span></button>)}</nav>
      </aside><article><div className="article-top"><div className="filename"><Icon name="file" size={15}/>{note.filename}</div><h2>{note.title}</h2>
        {note.provenance && <div className="trace-sources">
          <span>{note.provenance.repo} · {note.provenance.inputMode==="parent_only"?"仅使用修改前资料":"重演已公开决定"}</span>
          <a href={note.provenance.parentPermalink} target="_blank" rel="noreferrer">修改前源码</a>
          <a href={note.provenance.commitUrl} target="_blank" rel="noreferrer">迁移提交</a>
        </div>}</div>
      <div className="tabs" aria-label="笔记视图">{[["review","审阅建议"],["harness","Agent 调查"],["current","当前 Markdown"],["original","原始版本"]].map(([v,label])=><button key={v} aria-pressed={tab===v} disabled={busy || (draft!==null && v!=="current")} onClick={()=>{setTab(v);setNotice("");setError("");}}>{label}</button>)}</div>
      {tab==="review"?<div className="body">
        <div className="sectitle"><h3>影响判断</h3><span className={"pill "+note.kind}>{kindName[note.kind]}</span></div><p className="reason">{note.reason}</p>
        <h3>笔记依据</h3><blockquote>{note.evidence}</blockquote>
        {note.proposed&&<><h3>{note.kind==="confirm"?"沿用旧行为时的修改":"建议差异"}</h3><Diff original={note.original} proposed={note.proposed}/></>}
        {note.kind==="confirm"&&<p className="question">这份示例要固定运行 10 次，还是跟随库的默认行为？</p>}
      </div>:tab==="harness"?<HarnessPane key={note.id+":"+note.revision} note={note} baseline={kindName[note.kind]} Diff={Diff} busy={busy} setBusy={setBusy} refresh={refresh} notify={setNotice} editNewVersion={()=>{setTab("current");setDraft({text:note.current,revision:note.revision});setNotice("");setError("");}}/>:<div className="body">
        {tab==="current" && <div className="editor-tools"><span>当前保存版本 · r{note.revision}</span>{draft?<div><button className="btn secondary" disabled={busy} onClick={()=>{setDraft(null);setError("");}}>取消</button><button className="btn primary" disabled={busy} onClick={saveDraft}>保存编辑</button></div>:<button className="btn secondary" disabled={busy} onClick={()=>{setError("");setNotice("");setDraft({text:note.current,revision:note.revision});}}>编辑 Markdown</button>}</div>}
        {draft&&tab==="current"?<textarea aria-label="编辑 Markdown" disabled={busy} className="editor" value={draft.text} onChange={e=>setDraft({...draft,text:e.target.value})}/>:<pre className="markdown">{tab==="original"?note.original:note.current}</pre>}</div>}
      <div className="actions">{tab!=="harness" && <div className="buttons">{note.decision==="pending"?<>
          {note.proposed&&<button className="btn primary" disabled={busy||draft!==null} onClick={()=>decide("accept")}><Icon name="check" size={16}/>{note.kind==="confirm"?"固定运行 10 次":"接受修改"}</button>}
          <button className={"btn "+(note.proposed?"secondary":"primary")} disabled={busy||draft!==null} onClick={()=>decide("keep")}>{note.kind==="confirm"?"跟随默认值，保留原文":"保留原文"}</button>
        </>:<><span className="saved"><Icon name="check" size={16}/>{resultName[note.decision]}</span><button className="btn secondary" disabled={busy||draft!==null} onClick={()=>decide("pending")}><Icon name="undo" size={14}/>撤销审阅</button></>}</div>}
        <button className="plain" disabled={busy||draft!==null} onClick={()=>exportNotes(false)}><Icon name="export" size={16}/>导出本篇</button></div>
      </article></div>}
      <div role="status" aria-live="polite" className="notice">{notice}</div>
    </main>}
  </>;
}
createRoot(document.getElementById("root")).render(<Workbench/>);
