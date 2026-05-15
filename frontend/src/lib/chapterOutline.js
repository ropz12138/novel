/**
 * Derive sequential chapter numbers (1..max) from outline tree nodes.
 */
export function extractChapterNumbers(outlineTree) {
  if (!outlineTree) return [];
  const timeline = outlineTree.timeline || [];
  const branches = outlineTree.branches || [];
  const allNodes = [...timeline, ...branches];

  if (allNodes.length === 0) return [];

  let maxChapter = 0;
  for (const node of allNodes) {
    const end = node.chapter_end || 0;
    if (end > maxChapter) maxChapter = end;
  }

  return Array.from({ length: maxChapter }, (_, i) => i + 1);
}
