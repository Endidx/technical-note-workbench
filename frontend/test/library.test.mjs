import {test} from "node:test";
import assert from "node:assert/strict";
import {readMarkdown,importPayload,pendingJob} from "../src/library.mjs";

test("notes-only and version-only imports produce independent payloads",async()=>{
  const note=new File(["# 记录\n默认值"],"run.md");
  const ref=new File(["# API\n参数定义"],"guide.markdown");
  const notesOnly=await importPayload([note],null,"","");
  assert.equal(notesOnly.source,null);
  assert.equal(notesOnly.notes[0].content,"# 记录\n默认值");
  const versionOnly=await importPayload([],ref," Guide "," v2 ");
  assert.deepEqual(versionOnly.notes,[]);
  assert.deepEqual(versionOnly.source,{name:"Guide",version:"v2",filename:"guide.markdown",content:"# API\n参数定义"});
});

test("catches malformed files before import",async()=>{
  await assert.rejects(readMarkdown(new File([new Uint8Array([255])],"bad.md")),/UTF-8/);
  await assert.rejects(readMarkdown(new File(["  \n"],"empty.md")),/没有正文/);
  await assert.rejects(readMarkdown(new File(["x".repeat(100001)],"big.md")),/100,000/);
  await assert.rejects(readMarkdown(new File(["x"],"run.py")),/请选择/);
});

test("requires an actual Markdown version document and rejects duplicate note names",async()=>{
  const f=new File(["内容"],"guide.md");
  await assert.rejects(importPayload([f,f],null,"",""),/重名/);
  await assert.rejects(importPayload([],f,"指南",""),/名称和版本/);
  await assert.rejects(importPayload([],null,"",""),/请选择/);
  await assert.rejects(importPayload([f],null,"指南","v1"),/选择对应的资料/);
});

test("only queued and running generations are shown as building",()=>{
  for(const status of ["queued","running"]) assert.equal(pendingJob({status}),true);
  for(const status of ["failed","published","superseded"]) assert.equal(pendingJob({status}),false);
});
