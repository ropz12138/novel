export function sortTimelineNodes(nodes = []) {
  return [...nodes].sort((a, b) => {
    const oa = Number(a?.order ?? 0);
    const ob = Number(b?.order ?? 0);
    if (oa !== ob) return oa - ob;
    // 兼容旧字段 chapter_start 和新字段 chapter_range
    const sa = Number(a?.chapter_start ?? a?.chapter_range?.[0] ?? 0);
    const sb = Number(b?.chapter_start ?? b?.chapter_range?.[0] ?? 0);
    return sa - sb;
  });
}

