export function parsePositiveChapterInt(value) {
  const n = parseInt(String(value ?? "").trim(), 10);
  if (!Number.isFinite(n) || n <= 0) return null;
  return n;
}

