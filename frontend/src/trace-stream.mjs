// Consume complete SSE records even when a UTF-8 character or newline straddles chunks.
export async function consumeTrace(stream, onStep) {
  if (!stream) throw Error("无法读取调查数据流。");
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "", eventData = [], result;
  function dispatch() {
    if (!eventData.length) return;
    const event = JSON.parse(eventData.join("\n"));
    eventData = [];
    if (result) throw Error("调查结束后收到额外事件。");
    if (event.type === "error") {
      const error = Error(event.message || "调查失败。");
      error.status = event.status;
      throw error;
    }
    if (event.type === "step") onStep(event.step);
    if (event.type === "result") result = event.result;
  }
  try {
    while (true) {
      const {value, done} = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value,{stream:true});
      let cut;
      while ((cut = buffer.indexOf("\n")) !== -1) {
        const line = buffer.slice(0,cut).replace(/\r$/, "");
        buffer = buffer.slice(cut + 1);
        if (line === "") dispatch();
        else if (line.startsWith("data:")) eventData.push(line.slice(5).replace(/^ /,""));
      }
      if (done) break;
    }
    if (!result || buffer.trim() || eventData.length) throw Error("调查连接中断。请重新读取已保存的调查记录后再继续。");
    return result;
  } finally {
    await reader.cancel().catch(()=>{});
    reader.releaseLock();
  }
}
