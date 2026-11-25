import React, {useState} from "react";

const initializers = [
  ["absent","映射中没有这个键"], ["k-means++","k-means++"], ["random","random"],
  ["callable","可调用初始化器"], ["array-like","初始中心数组"], ["unknown","尚不清楚"]
];

export default function MappingQuestion({mapping, fields=["init","n_init"], previous, disabled, submit}) {
  const [init,setInit] = useState(previous?.init || "");
  const [count,setCount] = useState(typeof previous?.n_init === "number" ? "integer" : previous?.n_init || "");
  const [value,setValue] = useState(typeof previous?.n_init === "number" ? String(previous.n_init) : "");
  const askInit = fields.includes("init");
  const askCount = fields.includes("n_init");
  const valid = !askCount || count !== "integer" || (/^[1-9]\d*$/.test(value) && Number(value) <= 2147483647);
  return <form className="mapping-form" onSubmit={e=>{
    e.preventDefault();
    if (!disabled && (!askInit || init) && (!askCount || count) && valid) {
      submit({mapping,init:askInit?init:(previous?.init || "unknown"),
        n_init:askCount?(count==="integer"?Number(value):count):(previous?.n_init || "unknown")});
    }
  }}>
    {askInit && <label>映射中的 init
      <select value={init} disabled={disabled} onChange={e=>setInit(e.target.value)} required>
        <option value="">选择实际配置</option>
        {initializers.map(([key,label])=><option key={key} value={key}>{label}</option>)}
      </select>
    </label>}
    {askCount && <label>映射中的 n_init
      <select value={count} disabled={disabled} onChange={e=>setCount(e.target.value)} required>
        <option value="">选择实际配置</option><option value="absent">映射中没有这个键</option>
        <option value="integer">显式正整数</option><option value="auto">auto</option><option value="unknown">尚不清楚</option>
      </select>
    </label>}
    {askCount && count==="integer" && <label>配置的初始化次数
      <input type="number" min="1" max="2147483647" step="1" value={value} onChange={e=>setValue(e.target.value)} required/>
    </label>}
    <button type="submit" className="btn primary" disabled={disabled || (askInit && !init) || (askCount && !count) || !valid}>提交配置并继续</button>
  </form>;
}
