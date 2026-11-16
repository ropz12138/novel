export function splitAgentParagraphs(content) {
  const text = content || "";
  const paragraphs = [];
  let start = null;
  let end = null;
  let index = 0;
  while (index < text.length) {
    const lineStart = index;
    while (index < text.length && text[index] !== "\n") index += 1;
    let textEnd = index;
    if (textEnd > lineStart && text[textEnd - 1] === "\r") textEnd -= 1;
    if (index < text.length) index += 1;
    if (text.slice(lineStart, textEnd).replace(/[ \t]/g, "") === "") {
      if (start !== null) {
        paragraphs.push({ number: paragraphs.length + 1, start, end });
        start = null;
      }
      continue;
    }
    if (start === null) start = lineStart;
    end = textEnd;
  }
  if (start !== null) paragraphs.push({ number: paragraphs.length + 1, start, end });
  return paragraphs;
}

export function paragraphSpan(content, startParagraph, endParagraph) {
  if (!Number.isInteger(startParagraph) || !Number.isInteger(endParagraph) || startParagraph < 1 || endParagraph < startParagraph) {
    return null;
  }
  const paragraphs = splitAgentParagraphs(content);
  const selected = paragraphs.filter((paragraph) => paragraph.number >= startParagraph && paragraph.number <= endParagraph);
  if (!selected.length || selected[0].number !== startParagraph || selected[selected.length - 1].number !== endParagraph) {
    return null;
  }
  if (selected.length !== endParagraph - startParagraph + 1) return null;
  return { start: selected[0].start, end: selected[selected.length - 1].end };
}
