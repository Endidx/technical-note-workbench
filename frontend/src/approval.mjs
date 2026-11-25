export function approvalStorageKey(id, mode="rule") {
  return (mode==="model"?"note-review:model-approval:v1:":"note-review:approval:v1:") + id;
}

// Record the exact source revision before sending. A retry after a lost response
// must address the same approval, even if the note has already advanced.
export async function sendApprovalBatch({endpoint, revision, intentMode, decisionPolicy, target, receipts=[], save, request=fetch}) {
  const body = JSON.stringify({revision,intentMode,decisionPolicy});
  const history = [...receipts];
  save({revision, ...(decisionPolicy ? {decisionPolicy} : {}), target, receipts:[...history], pending:true});
  while (history.length < target) {
    const response = await request(endpoint+"/apply", {
      method:"POST", headers:{"Content-Type":"application/json"}, body
    });
    if (!response.ok) {
      const error = Error(response.status===409 ? "该调查版本无法确认，请重新核对当前笔记。" : "未能确认请求结果。");
      error.status = response.status;
      throw error;
    }
    const {approvalReceipt:receipt} = await response.json();
    if (!receipt || (intentMode && (receipt.intentMode ?? "rule") !== intentMode) || receipt.fromRevision !== revision || receipt.toRevision !== revision+1 ||
        !receipt.key || typeof receipt.replayed !== "boolean") {
      throw Error("未收到可核对的确认回执。");
    }
    history.push(receipt);
    save({revision, ...(decisionPolicy ? {decisionPolicy} : {}), target, receipts:[...history], pending:history.length < target});
  }
  return history;
}
