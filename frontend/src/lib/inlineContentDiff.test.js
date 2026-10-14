import { describe, expect, it } from "vitest";
import {
  applyHunks,
  reverseHunks,
  buildInlineDiffBlocks,
  buildStackedInlineDiffBlocks,
  contentAfterDecisions,
  contentAfterBatches,
  setHunkStatus,
  setAllHunkStatus,
  pendingHunks,
  pendingHunksFromBatches,
  accumulateNodeContentDiff,
  hydrateDiffBatches,
  setHunkStatusInBatches,
  setAllHunkStatusInBatches,
  buildContentDiffFromContents,
  commitUserParagraphEdit,
  commitUserTextEdit,
} from "./inlineContentDiff";

const ORIGINAL = "第一段。\n\n第二段。\n\n第三段。";

describe("inlineContentDiff", () => {
  it("returns immediately when the two complete contents are identical", () => {
    const content = Array.from({ length: 300 }, (_, index) => `第${index + 1}段内容。`).join("\n\n");
    expect(buildContentDiffFromContents(content, content)).toEqual([]);
  });

  it("commits a user paragraph edit into both content and baseline without disturbing agent diffs", () => {
    expect(commitUserParagraphEdit(
      "Agent旧段。\n\n用户原文。",
      "Agent新段。\n\n用户原文。",
      2,
      "用户手改。",
    )).toEqual({
      baselineContent: "Agent旧段。\n\n用户手改。",
      currentContent: "Agent新段。\n\n用户手改。",
    });
  });

  it("keeps user insertions inside an agent replacement out of the remaining diff", () => {
    expect(commitUserTextEdit("他走进废墟。", "他走进雨中。", "他缓缓走进细雨中。")).toEqual({
      baselineText: "他缓缓走进细废墟。",
      currentText: "他缓缓走进细雨中。",
    });
  });
  it("restores the net unreviewed diff from a server baseline", () => {
    const restored = accumulateNodeContentDiff(null, {
      original_content: "旧段落",
      current_content: "新段落",
      hunks: buildContentDiffFromContents("旧段落", "新段落"),
    });
    expect(pendingHunksFromBatches(restored.batches)).toEqual([
      { type: "replace", paragraph_index: 1, old_text: "旧段落", new_text: "新段落" },
    ]);
  });
  it("applies replace/insert/delete like the backend paragraph editor", () => {
    const hunks = [
      { type: "replace", paragraph_index: 2, old_text: "第二段。", new_text: "第二段改。" },
      { type: "insert_after", paragraph_index: 1, new_text: "插入段。" },
      { type: "delete", paragraph_index: 3, old_text: "第三段。" },
    ];

    expect(applyHunks(ORIGINAL, hunks)).toBe("第一段。\n\n插入段。\n\n第二段改。");
  });

  it("preserves leading and trailing whitespace when rebuilding exact content", () => {
    const original = "\n第一段旧。\n\n第二段。\n";
    const current = "\n第一段新。\n\n第二段。\n";
    const hunks = buildContentDiffFromContents(original, current);

    expect(applyHunks(original, hunks)).toBe(current);
    expect(reverseHunks(current, hunks)).toBe(original);
  });

  it("reverses applied hunks back to the original content", () => {
    const hunks = [
      { type: "replace", paragraph_index: 2, old_text: "第二段。", new_text: "第二段改。" },
      { type: "insert_after", paragraph_index: 0, new_text: "文首段。" },
      { type: "delete", paragraph_index: 3, old_text: "第三段。" },
    ];
    const next = applyHunks(ORIGINAL, hunks);
    expect(reverseHunks(next, hunks)).toBe(ORIGINAL);
  });

  it("builds inline blocks with pending hunks in body order", () => {
    const hunks = [
      { type: "replace", paragraph_index: 1, old_text: "第一段。", new_text: "开场改。" },
      { type: "insert_after", paragraph_index: 2, new_text: "新段。" },
    ];
    const blocks = buildInlineDiffBlocks(ORIGINAL, hunks);

    expect(blocks.map((block) => block.kind)).toEqual(["hunk", "paragraph", "hunk", "paragraph"]);
    expect(blocks[0].hunk.new_text).toBe("开场改。");
    expect(blocks[1].text).toBe("第二段。");
    expect(blocks[2].hunk.type).toBe("insert_after");
    expect(blocks[3].text).toBe("第三段。");
  });

  it("keeps accepted hunks as ordinary paragraphs and rejected hunks as original text", () => {
    const hunks = [
      { type: "replace", paragraph_index: 1, old_text: "第一段。", new_text: "开场改。", status: "accepted" },
      { type: "replace", paragraph_index: 2, old_text: "第二段。", new_text: "中段改。", status: "rejected" },
      { type: "delete", paragraph_index: 3, old_text: "第三段。" },
    ];
    const blocks = buildInlineDiffBlocks(ORIGINAL, hunks);

    expect(blocks).toEqual([
      { kind: "paragraph", text: "开场改。", paragraphIndex: 1 },
      { kind: "paragraph", text: "第二段。", paragraphIndex: 2 },
      { kind: "hunk", hunk: hunks[2], hunkIndex: 2, paragraph: "第三段。" },
    ]);
  });

  it("computes saved content from accept/reject decisions", () => {
    const hunks = [
      { type: "replace", paragraph_index: 1, old_text: "第一段。", new_text: "开场改。" },
      { type: "replace", paragraph_index: 2, old_text: "第二段。", new_text: "中段改。" },
    ];
    const afterAcceptFirst = setHunkStatus(hunks, 0, "accepted");
    expect(contentAfterDecisions(ORIGINAL, afterAcceptFirst)).toBe("开场改。\n\n中段改。\n\n第三段。");

    const afterRejectSecond = setHunkStatus(afterAcceptFirst, 1, "rejected");
    expect(contentAfterDecisions(ORIGINAL, afterRejectSecond)).toBe("开场改。\n\n第二段。\n\n第三段。");
    expect(pendingHunks(afterRejectSecond)).toEqual([]);

    expect(contentAfterDecisions(ORIGINAL, setAllHunkStatus(hunks, "rejected"))).toBe(ORIGINAL);
  });

  it("stores the first node diff without current content so the drawer can hydrate later", () => {
    const hunks = [{
      type: "replace",
      paragraph_index: 1,
      old_text: "第一段。",
      new_text: "开场改。",
    }];
    const stored = accumulateNodeContentDiff(null, { hunks });
    expect(stored.batches).toHaveLength(1);
    expect(() => reverseHunks("", hunks)).not.toThrow();

    const hydrated = hydrateDiffBatches("开场改。\n\n第二段。\n\n第三段。", stored);
    expect(hydrated.original_content).toBe(ORIGINAL);
    expect(buildStackedInlineDiffBlocks(hydrated.batches).some((block) => block.kind === "hunk")).toBe(true);
  });

  it("collapses consecutive changes into the net diff from the original baseline", () => {
    const first = accumulateNodeContentDiff(null, {
      original_content: "第一段。\n\n第二段。",
      current_content: "第一段改。\n\n第二段。",
      hunks: [{ type: "replace", paragraph_index: 1, old_text: "第一段。", new_text: "第一段改。" }],
    });
    const second = accumulateNodeContentDiff(first, {
      original_content: "第一段改。\n\n第二段。",
      current_content: "第一段再改。\n\n第二段。",
      hunks: [{ type: "replace", paragraph_index: 1, old_text: "第一段改。", new_text: "第一段再改。" }],
    });

    expect(second.original_content).toBe("第一段。\n\n第二段。");
    expect(second.current_content).toBe("第一段再改。\n\n第二段。");
    expect(second.batches).toHaveLength(1);
    expect(second.hunks).toEqual([{
      type: "replace",
      paragraph_index: 1,
      old_text: "第一段。",
      new_text: "第一段再改。",
    }]);
  });

  it("builds a net paragraph diff for replacements, insertions, and deletions", () => {
    expect(buildContentDiffFromContents(
      "第一段。\n\n第二段。\n\n第三段。",
      "第一段改。\n\n新增段。\n\n第三段。",
    )).toEqual([
      { type: "replace", paragraph_index: 1, old_text: "第一段。", new_text: "第一段改。" },
      { type: "delete", paragraph_index: 2, old_text: "第二段。", new_text: "" },
      { type: "insert_after", paragraph_index: 2, old_text: "", new_text: "新增段。" },
    ]);
  });

  it("keeps the original paragraph index when only a small middle range changes", () => {
    const paragraphs = Array.from({ length: 300 }, (_, index) => `第${index + 1}段。`);
    const changed = [...paragraphs];
    changed[199] = "第200段改。";

    expect(buildContentDiffFromContents(
      paragraphs.join("\n\n"),
      changed.join("\n\n"),
    )).toEqual([{
      type: "replace",
      paragraph_index: 200,
      old_text: "第200段。",
      new_text: "第200段改。",
    }]);
  });

  it("globally aligns a deleted reaction, an edited paragraph, and a new reaction", () => {
    const oldLong = "灰白晶核死死咬在掌心皮肉上。没等陆沉扣紧手指，一股冰冷的阴煞顺着皮下毛孔蛮横地扎了进去。";
    const newLong = "灰白晶核死死吸附在掌心皮肉上。没等陆沉扣紧手指，一股冰冷的阴煞顺着皮下毛孔蛮横地扎了进去。";
    const original = `前文。\n\n“啪！”\n\n${oldLong}\n\n后文。`;
    const current = `前文。\n\n${newLong}\n\n“操。”\n\n后文。`;

    const hunks = buildContentDiffFromContents(original, current);

    expect(hunks).toEqual([
      { type: "delete", paragraph_index: 2, old_text: "“啪！”", new_text: "" },
      { type: "replace", paragraph_index: 3, old_text: oldLong, new_text: newLong },
      { type: "insert_after", paragraph_index: 3, old_text: "", new_text: "“操。”" },
    ]);
    expect(applyHunks(original, hunks)).toBe(current);
    expect(reverseHunks(current, hunks)).toBe(original);
  });

  it("does not pair unrelated short quoted reactions by shared punctuation", () => {
    expect(buildContentDiffFromContents("“啪！”", "“操。”")).toEqual([
      { type: "delete", paragraph_index: 1, old_text: "“啪！”", new_text: "" },
      { type: "insert_after", paragraph_index: 1, old_text: "", new_text: "“操。”" },
    ]);
  });

  it("keeps accepted paragraphs in the next baseline when the agent edits again", () => {
    const first = accumulateNodeContentDiff(null, {
      original_content: "第一段。\n\n第二段。",
      current_content: "第一段改。\n\n第二段改。",
      hunks: [
        { type: "replace", paragraph_index: 1, old_text: "第一段。", new_text: "第一段改。" },
        { type: "replace", paragraph_index: 2, old_text: "第二段。", new_text: "第二段改。" },
      ],
    });
    first.batches[0].hunks[0].status = "accepted";

    const second = accumulateNodeContentDiff(first, {
      original_content: "第一段改。\n\n第二段改。",
      current_content: "第一段改。\n\n第二段再改。",
      hunks: [{ type: "replace", paragraph_index: 2, old_text: "第二段改。", new_text: "第二段再改。" }],
    });

    expect(second.original_content).toBe("第一段改。\n\n第二段。");
    expect(second.hunks).toEqual([{
      type: "replace",
      paragraph_index: 2,
      old_text: "第二段。",
      new_text: "第二段再改。",
    }]);
  });

  it("accumulates later node updates as additional applied batches", () => {
    const first = accumulateNodeContentDiff(null, {
      hunks: [{ type: "replace", paragraph_index: 2, old_text: "第二段。", new_text: "第二段改。" }],
    }, ORIGINAL.replace("第二段。", "第二段改。"));

    const second = accumulateNodeContentDiff(first, {
      hunks: [{ type: "replace", paragraph_index: 3, old_text: "第三段。", new_text: "第三段改。" }],
    });

    expect(second.batches).toHaveLength(2);
    expect(pendingHunksFromBatches(second.batches)).toHaveLength(2);
    expect(contentAfterBatches(second.batches)).toBe("第一段。\n\n第二段改。\n\n第三段改。");

    const blocks = buildStackedInlineDiffBlocks(second.batches);
    expect(blocks.filter((block) => block.kind === "hunk")).toHaveLength(2);
    expect(blocks.filter((block) => block.kind === "paragraph").map((block) => block.text)).toEqual(["第一段。"]);
  });

  it("keeps stacked diffs on the same paragraph and leaves them applied until decided", () => {
    const first = accumulateNodeContentDiff(null, {
      hunks: [{ type: "replace", paragraph_index: 2, old_text: "第二段。", new_text: "第二段改。" }],
    }, "第一段。\n\n第二段改。\n\n第三段。");
    const second = accumulateNodeContentDiff(first, {
      hunks: [{ type: "replace", paragraph_index: 2, old_text: "第二段改。", new_text: "第二段再改。" }],
    });

    const hunkBlocks = buildStackedInlineDiffBlocks(second.batches).filter((block) => block.kind === "hunk");
    expect(hunkBlocks.map((block) => block.hunk.new_text)).toEqual(["第二段改。", "第二段再改。"]);

    const afterRejectLatest = setHunkStatusInBatches(second.batches, 1, 0, "rejected");
    expect(contentAfterBatches(afterRejectLatest)).toBe("第一段。\n\n第二段改。\n\n第三段。");
  });

  it("hydrates batch originals from the currently applied node content", () => {
    const diff = {
      hunks: [{ type: "replace", paragraph_index: 1, old_text: "第一段。", new_text: "开场改。" }],
    };
    const hydrated = hydrateDiffBatches("开场改。\n\n第二段。\n\n第三段。", diff);
    expect(hydrated.original_content).toBe(ORIGINAL);
    expect(hydrated.batches[0].original_content).toBe(ORIGINAL);
  });

  it("keeps an empty original when hydrating a full-chapter insert already on the node", () => {
    const chapter = "第一段。\n\n第二段。\n\n第三段。";
    const hunks = buildContentDiffFromContents("", chapter);
    const hydrated = hydrateDiffBatches(chapter, {
      original_content: "",
      current_content: chapter,
      hunks,
    });

    expect(hydrated.original_content).toBe("");
    expect(contentAfterBatches(hydrated.batches)).toBe(chapter);
    expect(contentAfterBatches(setAllHunkStatusInBatches(hydrated.batches, "accepted"))).toBe(chapter);
  });

  it("reverses a multi-paragraph insert_after without leaving leftover paragraphs", () => {
    const inserted = "文首一。\n\n文首二。";
    const hunks = [{ type: "insert_after", paragraph_index: 0, new_text: inserted }];
    const next = applyHunks(ORIGINAL, hunks);
    expect(next).toBe(`${inserted}\n\n${ORIGINAL}`);
    expect(reverseHunks(next, hunks)).toBe(ORIGINAL);
  });

  it("replaces a streaming preview baseline with the authoritative persisted baseline", () => {
    const preview = accumulateNodeContentDiff(null, {
      preview: true,
      original_content: "第二稿",
      current_content: "第三稿预览",
      hunks: [{ type: "replace", paragraph_index: 1, old_text: "第二稿", new_text: "第三稿预览" }],
    });

    const finalized = accumulateNodeContentDiff(preview, {
      baseline_content: "第一稿",
      original_content: "第二稿",
      current_content: "第三稿",
      hunks: [{ type: "replace", paragraph_index: 1, old_text: "第二稿", new_text: "第三稿" }],
    });

    expect(finalized.original_content).toBe("第一稿");
    expect(finalized.current_content).toBe("第三稿");
    expect(finalized.hunks).toEqual([
      expect.objectContaining({ old_text: "第一稿", new_text: "第三稿" }),
    ]);
  });
});
