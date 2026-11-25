import React, {useState} from "react";
import {approvalStorageKey, sendApprovalBatch} from "./approval.mjs";

function readRecord(key) {
  try { return JSON.parse(sessionStorage.getItem(key)) || null; }
  catch { return null; }
}

export default function ApprovalPanel({note, run, endpoint, intentMode, busy, setBusy, refresh, notify}) {
  const key = approvalStorageKey(note.id,intentMode);
  const [record,setRecord] = useState(() => readRecord(key));
  const [failure,setFailure] = useState("");
  function persist(value) {
    sessionStorage.setItem(key, JSON.stringify(value));
    setRecord(value);
  }
  async function confirm(revision, target, receipts=[], decisionPolicy) {
    if(busy) return;
    setBusy(true);setFailure("");notify("");
    try {
      await sendApprovalBatch({endpoint, revision, intentMode, decisionPolicy, target, receipts, save:persist});
      await refresh();
      notify("已保存调查决定，可在当前 Markdown 中核对。");
    } catch(e) {
      if(e.status>=400 && e.status<500 && e.status!==408 && e.status!==429) {
        const latest = readRecord(key);
        if (latest) persist({...latest, pending:false});
        try {await refresh();} catch { /* Keep the original failure visible. */ }
      }
      setFailure(e.message);
    } finally {setBusy(false);}
  }
  const visible = record && (record.pending || record.receipts.length>0 && record.revision <= note.revision);
  const canApprove = run?.status==="complete" && !record?.pending;
  if (!visible && !canApprove && !failure) return null;
  const receipts = visible ? record.receipts : [];
  const verified = receipts.length>=2 && receipts.at(-1).replayed && receipts.every(r=>r.key===receipts[0].key && r.toRevision===receipts[0].toRevision);
  return <section className="approval" aria-label="调查确认与回执">
    {canApprove && <div className="buttons">
      <button className="btn primary" disabled={busy} onClick={()=>confirm(note.revision,1,[],run.decisionPolicy)}>{run.proposed?"应用调查建议":"确认保留当前内容"}</button>
      <button className="btn secondary" disabled={busy} onClick={()=>confirm(note.revision,2,[],run.decisionPolicy)}>验证重复确认</button>
    </div>}
    {canApprove && <p className="hint">验证重复确认会提交本次决定两次，可对照两次服务端回执。</p>}
    {visible && <div className="receipt"><h4>确认回执</h4>
      {receipts.map((r,i)=><p key={i}>请求 {i+1} <code>r{r.fromRevision} → r{r.toRevision}</code> · {r.replayed?"重复请求，复用回执":"首次写入"}</p>)}
      {receipts.length>0 && <p>确认键 <code>{receipts[0].key}</code></p>}
      {verified && <strong>两次回执指向同一次版本变更，只写入一次。</strong>}
      {record.pending && <><p>确认请求尚未收齐回执，重试会沿用 r{record.revision}。</p><button className="btn secondary" disabled={busy} onClick={()=>confirm(record.revision,record.target,receipts,record.decisionPolicy)}>重试同一确认</button></>}
      {!canApprove && !record.pending && receipts.length===1 && <button className="btn secondary" disabled={busy} onClick={()=>confirm(record.revision,2,receipts,record.decisionPolicy)}>验证重复确认</button>}
    </div>}
    {failure && <p role="alert" className="error">{failure}</p>}
  </section>;
}
