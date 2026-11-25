import {test} from "node:test";
import assert from "node:assert/strict";
import * as batch from "../src/library-batch.mjs";

test("defaults to the only comparable source and orders numeric versions", () => {
  const sources = [
    {name:"guide", version:"1.10"}, {name:"guide", version:"1.2"},
    {name:"other", version:"next"}
  ];
  const {name, fromVersion, toVersion} = batch.batchPair(sources);
  assert.deepEqual([name, fromVersion, toVersion], ["guide", "1.2", "1.10"]);
});

test("multiple candidate pairs require selection and preserve an explicit reversal", () => {
  const sources = ["1","2","3"].map(version => ({name:"guide", version}));
  assert.equal(batch.batchPair(sources).toVersion, "");
  assert.equal(batch.batchPair([...sources, {name:"x",version:"a"},{name:"x",version:"b"}]).name, "");
  const pair = batch.batchPair(sources, {name:"guide", fromVersion:"3", toVersion:"1"});
  assert.deepEqual([pair.fromVersion,pair.toVersion], ["3","1"]);
});

test("preserves matching lines between separate edits in the note diff", () => {
  const before = "# Guide\nold\nunchanged\nold again\n";
  const after = "# Guide\nnew\nunchanged\nnew again\n";
  const changes = batch.changedLines(before, after);
  assert.deepEqual(changes, [
    {kind:"minus",line:2,text:"old"}, {kind:"plus",line:2,text:"new"},
    {kind:"minus",line:4,text:"old again"}, {kind:"plus",line:4,text:"new again"}
  ]);
  assert.deepEqual(batch.changedLines(before, before), []);
});
