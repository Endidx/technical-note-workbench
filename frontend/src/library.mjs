export const pendingJob = job => job.status === "queued" || job.status === "running";

export async function readMarkdown(file) {
  if (!/\.(md|markdown)$/i.test(file.name) || /[/\\\x00-\x1f]/.test(file.name)) {
    throw Error("请选择 .md 或 .markdown 文件。");
  }
  if (file.size>100000) throw Error(file.name+" 超过单文件 100,000 字节限制。");
  let content;
  try {content=new TextDecoder("utf-8",{fatal:true}).decode(await file.arrayBuffer());}
  catch {throw Error(file.name+" 无法按 UTF-8 读取。");}
  if (!content.trim()) throw Error(file.name+" 没有正文。");
  return {filename:file.name,content};
}

export async function importPayload(files, source, name, version) {
  if (files.length>32) throw Error("每批最多可导入 32 篇笔记。");
  if (new Set(files.map(f=>f.name)).size !== files.length) throw Error("本批笔记中有重名文件，请分别导入或重命名。");
  if (!source && !files.length) throw Error("请选择笔记或资料文件。");
  if (source && (!name.trim() || !version.trim())) throw Error("请填写这份资料的名称和版本。");
  if (!source && (name.trim() || version.trim())) throw Error("请先选择对应的资料文件，或清空资料名称和版本再仅导入笔记。");
  return {
    notes:await Promise.all(files.map(readMarkdown)),
    source:source ? {...await readMarkdown(source),name:name.trim(),version:version.trim()} : null
  };
}

export async function libraryResponse(path, body, signal) {
  const options={signal,cache:"no-store"};
  if (body!==undefined) {
    options.method="POST";
    options.headers={"Content-Type":"application/json"};
    if (body!==null) options.body=JSON.stringify(body);
  }
  const response=await fetch("/api/library"+path,options);
  if (!response.ok) {
    const info=await response.json().catch(()=>({}));
    const error=Error(info.message || info.detail || info.error || ("资料库请求失败（"+response.status+"）"));
    error.status=response.status;
    throw error;
  }
  return response;
}

export async function api(path, body, signal) {
  const response=await libraryResponse(path, body, signal);
  return response.status===204 ? null : response.json();
}
