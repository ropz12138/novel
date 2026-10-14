// Python 的字符位置按 Unicode 码点计算；整条链路保留原始文本和换行。
const chars = (text) => Array.from(text || "");

export function applyAgentGroups(baseline, groups) {
  const result = chars(baseline);
  for (const group of [...groups].reverse()) {
    result.splice(group.start_offset, chars(group.old_text).length, ...chars(group.new_text));
  }
  return result.join("");
}

export function agentDiffBlocks(diff) {
  const baseline = chars(diff.original_content);
  const blocks = [];
  let cursor = 0;
  let currentCursor = 0;
  diff.hunks.forEach((hunk, index) => {
    if (hunk.start_offset > cursor) {
      blocks.push({ kind: "text", text: baseline.slice(cursor, hunk.start_offset).join(""), currentStart: currentCursor });
      currentCursor += hunk.start_offset - cursor;
    }
    blocks.push({ kind: "hunk", hunk, index, currentStart: currentCursor });
    currentCursor += chars(hunk.new_text).length;
    cursor = hunk.start_offset + chars(hunk.old_text).length;
  });
  if (cursor < baseline.length) blocks.push({ kind: "text", text: baseline.slice(cursor).join(""), currentStart: currentCursor });
  return blocks;
}

export function decideAgentGroup(diff, index, action, resolved) {
  const baseline = chars(diff.original_content);
  const hunks = [];
  const pieces = [];
  let cursor = 0;
  let shift = 0;
  diff.hunks.forEach((group, groupIndex) => {
    const selected = index === "all" || groupIndex === index;
    const oldText = selected && action === "accept" ? group.new_text
      : selected && action === "update" ? resolved.oldText : group.old_text;
    const newText = selected && action === "reject" ? group.old_text
      : selected && action === "update" ? resolved.newText : group.new_text;
    pieces.push(baseline.slice(cursor, group.start_offset).join(""), oldText);
    if (oldText !== newText) {
      hunks.push({ ...group, start_offset: group.start_offset + shift, old_text: oldText, new_text: newText,
        type: oldText && newText ? "replace" : oldText ? "delete" : "insert_after" });
    }
    shift += chars(oldText).length - chars(group.old_text).length;
    cursor = group.start_offset + chars(group.old_text).length;
  });
  pieces.push(baseline.slice(cursor).join(""));
  const originalContent = pieces.join("");
  return { grouping: "agent_replacements", original_content: originalContent,
    current_content: applyAgentGroups(originalContent, hunks), hunks };
}
