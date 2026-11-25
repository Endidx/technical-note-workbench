import {test} from "node:test";
import assert from "node:assert/strict";
import {sendApprovalBatch} from "../src/approval.mjs";

const receipt = {key:"note:r8",fromRevision:8,toRevision:9};
const response = (replayed) => Response.json({approvalReceipt:{...receipt,replayed}});

test("two independent requests carry the same source revision",async()=>{
  const sent=[], saved=[];
  const receipts=await sendApprovalBatch({
    revision:8, target:2, endpoint:"/harness",save:r=>saved.push(r),
    request:async(url,req)=>{sent.push([url,JSON.parse(req.body)]);return response(sent.length===2);}
  });
  assert.deepEqual(sent,[["/harness/apply",{revision:8}],["/harness/apply",{revision:8}]]);
  assert.deepEqual(receipts.map(r=>r.replayed),[false,true]);
  assert.deepEqual(saved.map(s=>s.pending),[true,true,false]);
});

test("lost first response is retried with the persisted revision",async()=>{
  let stored;
  await assert.rejects(sendApprovalBatch({
    revision:8,target:1,endpoint:"/n",save:s=>{stored=s;},
    request:async()=>{throw Error("network error");}
  }),/network error/);
  assert.equal(stored.pending,true);
  const receipts=await sendApprovalBatch({...stored,endpoint:"/n",save:s=>{stored=s;},
    request:async(_,req)=>{assert.equal(JSON.parse(req.body).revision,8);return response(true);}
  });
  assert.equal(receipts[0].replayed,true);
  assert.equal(stored.pending,false);
});

test("resume after a lost second response keeps the first receipt",async()=>{
  let stored, calls=0;
  await assert.rejects(sendApprovalBatch({
    revision:8,target:2,endpoint:"/n",save:s=>{stored=s;},
    request:async()=>{if(++calls===2) throw Error("connection closed");return response(false);}
  }),/connection closed/);
  assert.deepEqual(stored.receipts,[{...receipt,replayed:false}]);
  const receipts=await sendApprovalBatch({...stored,endpoint:"/n",save:s=>{stored=s;},
    request:async()=>{calls++;return response(true);}
  });
  assert.equal(calls,3);
  assert.deepEqual(receipts.map(r=>r.replayed),[false,true]);
});

test("model approval refuses a receipt from the legacy rule workflow", async()=>{
  await assert.rejects(sendApprovalBatch({
    revision:8, intentMode:"model", target:1, endpoint:"/harness", save:()=>{},
    request:async(url,req)=>{
      assert.deepEqual(JSON.parse(req.body),{revision:8,intentMode:"model"});
      return response(false);
    }
  }), /回执/);
});

test("a lost approval retries the policy that was on screen",async()=>{
  let record;
  await assert.rejects(sendApprovalBatch({
    endpoint:"/harness",revision:8,target:1,decisionPolicy:"context-decisions-v1",
    save:value=>{record=value;}, request:async()=>{throw Error("offline");}
  }),/offline/);
  assert.equal(record.decisionPolicy,"context-decisions-v1");
  await sendApprovalBatch({...record,endpoint:"/harness",save:()=>{},request:async(_,req)=>{
    assert.equal(JSON.parse(req.body).decisionPolicy,"context-decisions-v1");
    return response(true);
  }});
});
