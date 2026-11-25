export function getChoiceCitations(question) {
  const result = {};
  for (const id of ["old","default"]) {
    const citations = question.choiceCitations?.[id];
    const single = question.choiceEvidence?.[id];
    result[id] = Array.isArray(citations) ? citations : single ? [single] : [];
  }
  return result;
}
