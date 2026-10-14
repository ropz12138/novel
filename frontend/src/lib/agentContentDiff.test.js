import { describe, expect, it } from "vitest";
import { agentDiffBlocks, decideAgentGroup, applyAgentGroups } from "./agentContentDiff";

const baseline = "😀前文。\n\nA\n\nB\n\n后文。";
const hunk = { start_offset: Array.from("😀前文。\n\n").length, old_text: "A\n\nB", new_text: "X\n\nA′\n\nB′", type: "replace" };
const diff = { grouping: "agent_replacements", original_content: baseline, hunks: [hunk] };

describe("agent replacement groups", () => {
  it("renders one agent group intact among unmodified text", () => {
    const blocks = agentDiffBlocks(diff);
    expect(blocks.map(b => b.kind)).toEqual(["text", "hunk", "text"]);
    expect(blocks[1].hunk).toEqual(hunk);
    expect(applyAgentGroups(baseline, diff.hunks)).toBe("😀前文。\n\nX\n\nA′\n\nB′\n\n后文。");
  });
  it("accepts a group without changing current content", () => {
    const next = decideAgentGroup(diff, 0, "accept");
    expect(next.original_content).toBe(applyAgentGroups(baseline, diff.hunks));
    expect(next.current_content).toBe(next.original_content);
    expect(next.hunks).toEqual([]);
  });
  it("rejects a complete multiline group without paragraph alignment", () => {
    const next = decideAgentGroup(diff, 0, "reject");
    expect(next.current_content).toBe(baseline);
    expect(next.hunks).toEqual([]);
  });
  it("rebases the remaining group after accepting an earlier expansion", () => {
    const other = { start_offset: Array.from("😀前文。\n\nA\n\nB\n\n").length, old_text: "后文", new_text: "后文改", type: "replace" };
    const next = decideAgentGroup({ ...diff, hunks: [hunk, other] }, 0, "accept");
    expect(next.hunks).toHaveLength(1);
    expect(next.hunks[0].start_offset).toBe(other.start_offset + Array.from(hunk.new_text).length - Array.from(hunk.old_text).length);
    expect(applyAgentGroups(next.original_content, next.hunks)).toBe(next.current_content);
  });
  it("keeps partial rejection within its original agent group", () => {
    const next = decideAgentGroup(diff, 0, "update", { oldText: hunk.old_text, newText: "X\n\nA\n\nB′" });
    expect(next.hunks).toHaveLength(1);
    expect(next.hunks[0].old_text).toBe(hunk.old_text);
    expect(next.hunks[0].new_text).toBe("X\n\nA\n\nB′");
  });
});
