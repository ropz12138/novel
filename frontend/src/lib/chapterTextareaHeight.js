export const CHAPTER_TEXTAREA_MIN_HEIGHT_PX = 120;

export function resolveChapterTextareaHeightPx(
  scrollHeight,
  minHeight = CHAPTER_TEXTAREA_MIN_HEIGHT_PX,
) {
  return Math.max(scrollHeight, minHeight);
}

/**
 * 按内容自适应 textarea 高度。须先将 height 置为 auto，否则 scrollHeight 会沿用上一章的撑高值。
 */
export function applyChapterTextareaAutoHeight(textarea, { content } = {}) {
  if (!textarea) return;
  if (!content) {
    textarea.style.height = "";
    return;
  }
  textarea.style.height = "auto";
  textarea.style.height = `${resolveChapterTextareaHeightPx(textarea.scrollHeight)}px`;
}

/** 容器宽度变化（侧栏/聊天窗开合）时须重新测量 scrollHeight，否则 overflow-hidden 会裁切正文 */
export function bindChapterTextareaResizeObserver(textarea, onResize) {
  if (!textarea || typeof onResize !== "function") {
    return () => {};
  }
  if (typeof ResizeObserver === "undefined") {
    return () => {};
  }
  const observer = new ResizeObserver(() => onResize());
  observer.observe(textarea);
  return () => observer.disconnect();
}
