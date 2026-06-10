/** 根据文本偏移计算 1-based 行号。 */
export function getLineNumberAtPosition(text, position) {
  if (position <= 0) return 1;
  const before = text.slice(0, position);
  return before.split("\n").length;
}

/** 从 textarea 当前选区解析行号范围与正文。无有效选区时返回 null。 */
export function getSelectionLineRange(textarea) {
  if (!textarea) return null;
  const { value, selectionStart, selectionEnd } = textarea;
  if (selectionStart == null || selectionEnd == null || selectionStart === selectionEnd) {
    return null;
  }
  const text = value.slice(selectionStart, selectionEnd);
  if (!text.trim()) return null;
  return {
    startLine: getLineNumberAtPosition(value, selectionStart),
    endLine: getLineNumberAtPosition(value, selectionEnd),
    text,
  };
}

/** 格式：第n章的n行到n行，```xxx``` */
export function formatChapterSelectionQuote({ chapterNumber, startLine, endLine, text }) {
  const ch = Number(chapterNumber);
  const start = Number(startLine);
  const end = Number(endLine);
  return `第${ch}章的${start}行到${end}行，\n\`\`\`${text}\`\`\``;
}

/** Ctrl+L：将章节正文选区格式化为引用并写入 Agent 输入框。 */
export function applyChapterSelectionToChatInput({
  textarea,
  chapterNumber,
  appendToInput,
  focusInput,
}) {
  const selection = getSelectionLineRange(textarea);
  if (!selection || chapterNumber == null) return false;
  const quote = formatChapterSelectionQuote({
    chapterNumber,
    startLine: selection.startLine,
    endLine: selection.endLine,
    text: selection.text,
  });
  appendToInput(quote);
  focusInput?.();
  return true;
}
