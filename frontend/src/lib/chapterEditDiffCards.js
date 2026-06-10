/** 同章节已有只读（自动应用）卡片时，隐藏待确认的非只读卡片。 */
export function suppressSupersededChapterEditCards(items) {
  if (!Array.isArray(items) || items.length === 0) return items;

  const autoAppliedChapters = new Set(
    items
      .filter(
        (m) =>
          m?.kind === "message"
          && m.type === "edit_diff_card"
          && m.diffCard?.readonly
          && m.diffCard.chapter_number != null
      )
      .map((m) => m.diffCard.chapter_number)
  );

  if (autoAppliedChapters.size === 0) return items;

  return items.filter((m) => {
    if (m?.kind !== "message" || m.type !== "edit_diff_card") return true;
    if (m.diffCard?.readonly) return true;
    if (m.diffCard?.chapter_number == null) return true;
    return !autoAppliedChapters.has(m.diffCard.chapter_number);
  });
}
