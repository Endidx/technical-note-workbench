import {test} from "node:test";
import assert from "node:assert/strict";
import {consumeTrace} from "../src/trace-stream.mjs";

function splitBytes(text) {
  const bytes = new TextEncoder().encode(text);
  return new ReadableStream({
    start(controller) {
      for(const byte of bytes) controller.enqueue(Uint8Array.of(byte));
      controller.close();
    }
  });
}

test("decodes live steps and final persisted result across byte boundaries", async () => {
  const events = [{type:"step",step:{summary:"正在核对原文"}},{type:"result",result:{revision:5,status:"complete"}}];
  const recorded=[];
  const result=await consumeTrace(splitBytes(events.map(x=>"data: "+JSON.stringify(x)+"\r\n\r\n").join("")),s=>recorded.push(s));
  assert.deepEqual(recorded,[events[0].step]);
  assert.deepEqual(result,events[1].result);
});

test("detects a truncated stream", async () => {
  await assert.rejects(consumeTrace(splitBytes('data: {"type":"result"}\n'),()=>{}),/中断/);
});

test("forwards a revision conflict before displaying a result", async () => {
  await assert.rejects(consumeTrace(splitBytes('data: {"type":"error","message":"冲突","status":409}\n\n'),()=>{}),{status:409});
});
