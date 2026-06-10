/**
 * Derive sequential chapter numbers (1..max) from outline tree nodes.
 */
export function extractChapterNumbers(outlineTree) {
  if (!outlineTree) return [];
  const macroPhases = outlineTree.outline?.macro_phases || [];
  const mesoStages = outlineTree.meso?.meso_stages || [];
  const allNodes = [...macroPhases, ...mesoStages];

  if (allNodes.length === 0) return [];

  let maxChapter = 0;
  for (const node of allNodes) {
    const range = node.chapter_range || [0, 0];
    const end = range[1] || 0;
    if (end > maxChapter) maxChapter = end;
  }

  return Array.from({ length: maxChapter }, (_, i) => i + 1);
}
