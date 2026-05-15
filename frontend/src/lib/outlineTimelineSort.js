export function sortTimelineNodes(timeline = []) {
  return [...timeline].sort((a, b) => {
    const oa = Number(a?.order ?? 0);
    const ob = Number(b?.order ?? 0);
    if (oa !== ob) return oa - ob;
    const sa = Number(a?.chapter_start ?? 0);
    const sb = Number(b?.chapter_start ?? 0);
    return sa - sb;
  });
}

