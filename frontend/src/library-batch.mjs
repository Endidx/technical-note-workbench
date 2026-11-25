export function batchPair(sources, choice={}) {
  const byName = new Map();
  for (const {name, version} of sources) {
    if (!byName.has(name)) byName.set(name, new Set());
    byName.get(name).add(version);
  }
  const names = [...byName.keys()].filter(name => byName.get(name).size >= 2);
  const name = names.includes(choice.name) ? choice.name : names.length === 1 ? names[0] : "";
  const versions = [...(byName.get(name) || [])];
  // Numeric version labels have an intrinsic ordering. Other labels follow the published source order.
  if (versions.every(v => /^v?\d+(\.\d+)*$/i.test(v))) {
    versions.sort((a,b) => a.replace(/^v/i,"").localeCompare(b.replace(/^v/i,""), "en", {numeric:true}));
  }
  const fromVersion = versions.includes(choice.fromVersion) ? choice.fromVersion : versions.length === 2 ? versions[0] : "";
  const toVersion = versions.includes(choice.toVersion) ? choice.toVersion : versions.length === 2 ? versions[1] : "";
  return {names, name, versions, fromVersion, toVersion};
}

export function changedLines(original, proposed) {
  const a = original ? original.split("\n") : [];
  const b = proposed ? proposed.split("\n") : [];
  let start = 0, endA = a.length, endB = b.length;
  while (start < endA && start < endB && a[start] === b[start]) start++;
  while (endA > start && endB > start && a[endA-1] === b[endB-1]) { endA--; endB--; }
  const rows = endA - start, cols = endB - start, stride = cols + 1;
  // For very large rewrites the view falls back to the two complete source texts.
  if ((rows + 1) * stride > 1000000) return null;
  const lengths = new Uint32Array((rows + 1) * stride);
  for (let i = rows - 1; i >= 0; i--) {
    for (let j = cols - 1; j >= 0; j--) {
      const offset = i * stride + j;
      lengths[offset] = a[start+i] === b[start+j]
        ? 1 + lengths[offset+stride+1]
        : Math.max(lengths[offset+stride], lengths[offset+1]);
    }
  }
  const changes = [];
  let i = 0, j = 0;
  while (i < rows || j < cols) {
    if (i < rows && j < cols && a[start+i] === b[start+j]) { i++; j++; continue; }
    const offset = i * stride + j;
    if (i < rows && (j === cols || lengths[offset+stride] >= lengths[offset+1])) {
      changes.push({kind:"minus", line:start+i+1, text:a[start+i]});
      i++;
    } else {
      changes.push({kind:"plus", line:start+j+1, text:b[start+j]});
      j++;
    }
  }
  return changes;
}
