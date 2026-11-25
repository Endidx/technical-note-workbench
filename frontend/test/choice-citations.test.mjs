import {test} from "node:test";
import assert from "node:assert/strict";
import {getChoiceCitations} from "../src/choice-citations.mjs";

const title = {line:3,sentence:1,quote:"报告题名是《隧道复核图》。"};
const policy = {line:6,sentence:4,quote:"这份报告保留十次启动。"};
const other = {line:7,sentence:5,quote:"另一份报告采用新版默认。"};

test("each choice keeps its own original evidence chain in order",()=>{
  const evidence = getChoiceCitations({
    choiceCitations:{old:[title,policy]},choiceEvidence:{old:policy,default:other}
  });
  assert.deepEqual(evidence,{old:[title,policy],default:[other]});
});

test("a missing citation stays missing",()=>{
  assert.deepEqual(getChoiceCitations({}),{old:[],default:[]});
});
