import { describe, expect, it } from "vitest";
import {
  applyHunks,
  reverseHunks,
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
  inlineTextSegments,
  resolveLocalHunkInBatches,
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


describe("inlineTextSegments", () => {
  it.each(["血", "血脉"])("merges edits separated by one or two Han characters: %s", (bridge) => {
    expect(inlineTextSegments(`前，始祖${bridge}脉。后`, `前，霸道${bridge}气。后`)).toEqual([
      { kind: "equal", oldText: "前，", newText: "前，" },
      { kind: "change", oldText: `始祖${bridge}脉`, newText: `霸道${bridge}气` },
      { kind: "equal", oldText: "。后", newText: "。后" },
    ]);
  });

  it("merges consecutive short bridges without absorbing outer context", () => {
    expect(inlineTextSegments("前旧甲旧乙旧后", "前新甲改乙异后")).toEqual([
      { kind: "equal", oldText: "前", newText: "前" },
      { kind: "change", oldText: "旧甲旧乙旧", newText: "新甲改乙异" },
      { kind: "equal", oldText: "后", newText: "后" },
    ]);
  });

  it.each(["甲乙丙", "，", "。", " ", "\n", "\n\n", "甲，", "a", "1", "😀"])("keeps edits separated across %j", (bridge) => {
    expect(inlineTextSegments(`旧${bridge}旧`, `新${bridge}改`)).toEqual([
      { kind: "change", oldText: "旧", newText: "新" },
      { kind: "equal", oldText: bridge, newText: bridge },
      { kind: "change", oldText: "旧", newText: "改" },
    ]);
  });

  it("aligns a later unique phrase instead of an earlier shared word", () => {
    const oldText = "五指发力收拢。\n\n咔嚓一声，变异体坚硬的喉骨被生生捏得碎裂塌陷，整具沉重畸变的肉山，竟被陆沉单臂从地面硬生生凌空拎起。手臂猛然下掼，变异体的头颅被狠砸在水泥地面上，砸出一个脸盆大的碎石坑。\n\n陆沉弯腰抓起那柄四斤半重的生铁管钳。\n\n生铁入手轻若无物，手臂轮圆，管钳带着恶风呼啸砸落。\n\n当的一声爆响，变异体右侧颅骨当场塌陷变形。\n\n";
    const newText = "沉重的铸铁锯齿撕裂恶风，当的一声暴响，结结实实砸在变异体右侧颅骨。\n\n骨头凹陷碎裂，腥黑脓汁伴着碎骨激射上墙。\n\n不等怪物神经抽搐，手臂肌肉暴缩，借着反震回弹再次轮圆，管钳如重锤连环轰击！\n\n";
    const segments = inlineTextSegments(oldText, newText);
    expect(segments.map((segment) => segment.oldText).join("")).toBe(oldText);
    expect(segments.map((segment) => segment.newText).join("")).toBe(newText);
    const skull = segments.find((segment) => segment.newText.includes("右侧颅骨"));
    expect(skull).toMatchObject({ kind: "equal" });
    expect(skull.oldText).toBe(skull.newText);
    expect(skull.newText).not.toContain("骨头凹陷");
    const dent = segments.find((segment) => segment.newText.includes("骨头凹陷"));
    expect(dent.kind).toBe("change");
    expect(dent.oldText).toContain("当场塌陷");
    expect(dent.oldText).not.toContain("喉骨");
    expect(dent.newText).not.toContain("右侧颅骨");
  });

  it.each([
    ["甲删除乙", "甲乙"],
    ["甲乙", "甲新增乙"],
    ["😀旧\n\n结尾", "😀新\n\n结尾"],
    ["", "新章。\n\n".repeat(4000)],
    ["整段删除", ""],
    ["相同", "相同"],
  ])("preserves complete old and new text: %s", (oldText, newText) => {
    const segments = inlineTextSegments(oldText, newText);
    expect(segments.map((segment) => segment.oldText).join("")).toBe(oldText);
    expect(segments.map((segment) => segment.newText).join("")).toBe(newText);
  });
});


describe("resolveLocalHunkInBatches", () => {
  const original = "前段。\n\n始祖血脉在体内涌动，旧光。\n\n末段。";
  const batches = [{ original_content: original, hunks: [
    { type: "replace", paragraph_index: 2, old_text: "始祖血脉在体内涌动，旧光。", new_text: "霸道血气在体内涌动，新光。" },
    { type: "replace", paragraph_index: 3, old_text: "末段。", new_text: "尾声。" },
  ] }];
  it("restores a local original and leaves unrelated edits pending", () => {
    expect(resolveLocalHunkInBatches(batches, 0, 0, {
      oldText: "始祖血脉在体内涌动，旧光。", newText: "始祖血脉在体内涌动，新光。",
    })).toEqual({ baselineContent: original, currentContent: "前段。\n\n始祖血脉在体内涌动，新光。\n\n尾声。" });
  });
  it("deletes only the selected pending original", () => {
    expect(resolveLocalHunkInBatches(batches, 0, 0, {
      oldText: "霸道血气在体内涌动，旧光。", newText: "霸道血气在体内涌动，新光。",
    })).toEqual({ baselineContent: "前段。\n\n霸道血气在体内涌动，旧光。\n\n末段。", currentContent: "前段。\n\n霸道血气在体内涌动，新光。\n\n尾声。" });
  });
  it("restores a deleted paragraph", () => {
    expect(resolveLocalHunkInBatches([{ original_content: "前段。\n\n删除段。", hunks: [
      { type: "delete", paragraph_index: 2, old_text: "删除段。", new_text: "" },
    ] }], 0, 0, { oldText: "删除段。", newText: "删除段。" })).toEqual({
      baselineContent: "前段。\n\n删除段。", currentContent: "前段。\n\n删除段。",
    });
  });
});

describe("paragraph review of agent changes", () => {
  it.each([
    ["A\n\nB", "X\n\nA′\n\nB′", 3],
    ["", "新增甲。\n\n新增乙。", 2],
    ["删除甲。\n\n删除乙。", "", 2],
    ["😀甲的旧正文。\n\n乙的旧正文。", "😀甲的新正文。\n\n乙的新正文。", 2],
  ])("reviews each changed paragraph independently: %s", async (old, current, count) => {
    const { hydrateParagraphReview } = await import("./inlineContentDiff");
    const diff = { grouping: "agent_replacements", original_content: old,
      hunks: [{ start_offset: 0, old_text: old, new_text: current }] };
    const restored = hydrateParagraphReview(current, diff);
    expect(restored.batches[0].hunks).toHaveLength(count);
    expect(contentAfterBatches(restored.batches)).toBe(current);
    expect(contentAfterBatches(setAllHunkStatusInBatches(restored.batches, "rejected"))).toBe(old);
    for (const hunk of restored.batches[0].hunks) {
      expect(hunk.new_text || "").not.toContain("\n\n");
      expect(hunk.old_text || "").not.toContain("\n\n");
    }
  });
});

it("preserves exact Unicode offsets when transporting paragraph decisions", async () => {
  const { agentReviewSnapshot } = await import("./inlineContentDiff");
  const { applyAgentGroups } = await import("./agentContentDiff");
  for (const [old, current] of [
    ["😀甲旧。\n\n乙旧。", "😀甲新。\n\n新增。\n\n乙新。"],
    ["", "新甲。\n\n新乙。"], ["旧甲。\n\n旧乙。", ""],
  ]) {
    const saved = agentReviewSnapshot(old, current);
    expect(applyAgentGroups(old, saved.hunks)).toBe(current);
    let end = 0;
    for (const hunk of saved.hunks) {
      expect(hunk.start_offset).toBeGreaterThanOrEqual(end);
      expect(Array.from(old).slice(hunk.start_offset, hunk.start_offset + Array.from(hunk.old_text).length).join("")).toBe(hunk.old_text);
      end = hunk.start_offset + Array.from(hunk.old_text).length;
    }
  }
});

describe("unrelated paragraph review", () => {
  const old = "梁超背着鼓鼓囊囊的战术包跑在最前头，两只脚倒腾得飞快。他一边跑一边揪住身旁一个学生的肩膀往后一推，自己借力窜出两步。被推倒的学生膝盖还没撑起来，一头四肢着地的丧尸已经扑上去，惨叫只响了半截。";
  const next = "他没回头，肩膀一沉把包带顶回去，管钳从腰后抽出来，锯齿从下往上撩，砸在那东西后颈。头骨塌进去一块，黑血顺着脊梁淌下来。";
  it.each([false, true])("separates unrelated paragraphs from a whole-text submission (grouped=%s)", async (grouped) => {
    const { hydrateParagraphReview } = await import("./inlineContentDiff");
    const baseline = `开头。\n\n${old}\n\n结尾。`;
    const current = `开头。\n\n${next}\n\n结尾。`;
    const restored = hydrateParagraphReview(current, {
      ...(grouped ? { grouping: "agent_replacements" } : {}),
      original_content: baseline,
      hunks: [{ type: "replace", start_offset: 0, paragraph_index: 1, old_text: baseline, new_text: current }],
    });
    const hunks = restored.batches[0].hunks;
    expect(hunks.map((hunk) => hunk.type)).not.toContain("replace");
    expect(hunks).toEqual(expect.arrayContaining([
      expect.objectContaining({ type: "delete", old_text: old }),
      expect.objectContaining({ type: "insert_after", new_text: next }),
    ]));
    expect(contentAfterBatches(restored.batches)).toBe(current);
    expect(contentAfterBatches(setAllHunkStatusInBatches(restored.batches, "rejected"))).toBe(baseline);
  });
});
