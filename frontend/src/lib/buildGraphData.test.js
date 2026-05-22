import { describe, expect, it } from "vitest";

// We'll import from the new module once created
// For now, inline the function for testing during refactor
import { buildGraphData } from "./buildGraphData.js";

describe("buildGraphData", () => {
  it("returns empty nodes and edges for empty input", () => {
    const result = buildGraphData({}, []);
    expect(result.nodes).toEqual([]);
    expect(result.edges).toEqual([]);
  });

  it("creates nodes for timeline entries", () => {
    const tree = {
      timeline: [
        { id: "T1", development_node: "开端", order: 1, chapter_start: 1, chapter_end: 3 },
        { id: "T2", development_node: "发展", order: 2, chapter_start: 4, chapter_end: 6 },
      ],
    };
    const result = buildGraphData(tree, []);
    const timelineLabels = result.nodes
      .filter((n) => n.group === "mainStory")
      .map((n) => n.label);
    expect(timelineLabels).toHaveLength(2);
  });

  it("creates edges between consecutive timeline nodes", () => {
    const tree = {
      timeline: [
        { id: "T1", development_node: "开端", order: 1, chapter_start: 1, chapter_end: 3 },
        { id: "T2", development_node: "发展", order: 2, chapter_start: 4, chapter_end: 6 },
      ],
    };
    const result = buildGraphData(tree, []);
    const seqEdges = result.edges.filter((e) => e.id.startsWith("seq:"));
    expect(seqEdges).toHaveLength(1);
  });

  it("creates branch nodes attached to timeline", () => {
    const tree = {
      timeline: [
        { id: "T1", development_node: "开端", order: 1, chapter_start: 1, chapter_end: 3 },
      ],
      branches: [
        { id: "B1", name: "支线A", attach_to: "T1", side: "right", chapter_start: 1, chapter_end: 3 },
      ],
    };
    const result = buildGraphData(tree, []);
    const branchNodes = result.nodes.filter((n) => n.group === "branchStory");
    expect(branchNodes).toHaveLength(1);
    const attachEdges = result.edges.filter((e) => e.id.startsWith("attach:"));
    expect(attachEdges).toHaveLength(1);
  });

  // ── Key tests: foreshadowing with branch references ──

  it("connects foreshadowing to timeline nodes via plant/payoff", () => {
    const tree = {
      timeline: [
        { id: "T1", development_node: "开端", order: 1, chapter_start: 1, chapter_end: 3 },
        { id: "T2", development_node: "发展", order: 2, chapter_start: 4, chapter_end: 6 },
      ],
      foreshadowing: [
        { id: "F1", content: "伏笔A", plant_node: "T1", payoff_node: "T2" },
      ],
    };
    const result = buildGraphData(tree, []);
    const fNodes = result.nodes.filter((n) => n.group === "foreshadow");
    expect(fNodes).toHaveLength(1);

    // plant edge: T1 -> F1
    const plantEdges = result.edges.filter((e) => e.id.startsWith("plant:"));
    expect(plantEdges).toHaveLength(1);
    expect(plantEdges[0].from).toBeTruthy();
    expect(plantEdges[0].to).toBeTruthy();

    // payoff edge: F1 -> T2
    const payoffEdges = result.edges.filter((e) => e.id.startsWith("payoff:"));
    expect(payoffEdges).toHaveLength(1);
    expect(payoffEdges[0].from).toBeTruthy();
    expect(payoffEdges[0].to).toBeTruthy();
  });

  it("connects foreshadowing plant_node to a branch node", () => {
    const tree = {
      timeline: [
        { id: "T1", development_node: "开端", order: 1, chapter_start: 1, chapter_end: 3 },
      ],
      branches: [
        { id: "B1", name: "支线A", attach_to: "T1", side: "right", chapter_start: 1, chapter_end: 3 },
      ],
      foreshadowing: [
        { id: "F1", content: "伏笔A", plant_node: "B1", payoff_node: "T1" },
      ],
    };
    const result = buildGraphData(tree, []);
    const fNodes = result.nodes.filter((n) => n.group === "foreshadow");
    expect(fNodes).toHaveLength(1);

    // plant edge: B1 -> F1 (should be connected, not null)
    const plantEdges = result.edges.filter((e) => e.id.startsWith("plant:"));
    expect(plantEdges).toHaveLength(1);
    expect(plantEdges[0].from).toBeTruthy();
    // The 'from' should be a branch node id (starts with 'b:')
    expect(plantEdges[0].from).toMatch(/^b:/);
  });

  it("connects foreshadowing payoff_node to a branch node", () => {
    const tree = {
      timeline: [
        { id: "T1", development_node: "开端", order: 1, chapter_start: 1, chapter_end: 3 },
      ],
      branches: [
        { id: "B1", name: "支线A", attach_to: "T1", side: "right", chapter_start: 1, chapter_end: 3 },
      ],
      foreshadowing: [
        { id: "F1", content: "伏笔A", plant_node: "T1", payoff_node: "B1" },
      ],
    };
    const result = buildGraphData(tree, []);
    const payoffEdges = result.edges.filter((e) => e.id.startsWith("payoff:"));
    expect(payoffEdges).toHaveLength(1);
    expect(payoffEdges[0].to).toBeTruthy();
    // The 'to' should be a branch node id (starts with 'b:')
    expect(payoffEdges[0].to).toMatch(/^b:/);
  });

  it("connects foreshadowing where both plant and payoff reference branches", () => {
    const tree = {
      timeline: [
        { id: "T1", development_node: "开端", order: 1, chapter_start: 1, chapter_end: 3 },
      ],
      branches: [
        { id: "B1", name: "支线A", attach_to: "T1", side: "right", chapter_start: 1, chapter_end: 2 },
        { id: "B2", name: "支线B", attach_to: "T1", side: "left", chapter_start: 2, chapter_end: 3 },
      ],
      foreshadowing: [
        { id: "F1", content: "伏笔A", plant_node: "B1", payoff_node: "B2" },
      ],
    };
    const result = buildGraphData(tree, []);
    const fNodes = result.nodes.filter((n) => n.group === "foreshadow");
    expect(fNodes).toHaveLength(1);

    const plantEdges = result.edges.filter((e) => e.id.startsWith("plant:"));
    expect(plantEdges).toHaveLength(1);
    expect(plantEdges[0].from).toMatch(/^b:/);

    const payoffEdges = result.edges.filter((e) => e.id.startsWith("payoff:"));
    expect(payoffEdges).toHaveLength(1);
    expect(payoffEdges[0].to).toMatch(/^b:/);
  });

  // ── Real-world scenario: the 14-foreshadowing dataset ──

  it("handles the real 14-foreshadowing dataset without dangling nodes", () => {
    const tree = {
      timeline: [
        { id: "T1", development_node: "末日爆发", order: 1, chapter_start: 1, chapter_end: 5 },
        { id: "T2", development_node: "求生探索", order: 2, chapter_start: 6, chapter_end: 12 },
        { id: "T3", development_node: "初入避难所", order: 3, chapter_start: 13, chapter_end: 20 },
        { id: "T4", development_node: "异能觉醒", order: 4, chapter_start: 21, chapter_end: 30 },
        { id: "T5", development_node: "秦陵探秘", order: 5, chapter_start: 31, chapter_end: 42 },
        { id: "T6", development_node: "真相揭露", order: 6, chapter_start: 43, chapter_end: 52 },
        { id: "T7", development_node: "终局之战", order: 7, chapter_start: 53, chapter_end: 60 },
      ],
      branches: [
        { id: "B1", name: "嬴姓异变", attach_to: "T1", side: "right" },
        { id: "B2", name: "陈伯身份", attach_to: "T2", side: "left" },
        { id: "B3", name: "秦军虎符", attach_to: "T3", side: "right" },
        { id: "B4", name: "黑袍使者", attach_to: "T4", side: "left" },
        { id: "B5", name: "守陵盟约", attach_to: "T5", side: "right" },
        { id: "B6", name: "血尸驯服", attach_to: "T6", side: "left" },
      ],
      foreshadowing: [
        { id: "F1", content: "嬴姓被咬后伤口快速愈合", plant_node: "T1", payoff_node: "T2" },
        { id: "F2", content: "嬴姓体内血液异常", plant_node: "T1", payoff_node: "T4" },
        { id: "F3", content: "王胖子目睹嬴姓异常", plant_node: "B1", payoff_node: "B3" },
        { id: "F4", content: "陈伯用秦代古语暗号试探", plant_node: "B2", payoff_node: "B3" },
        { id: "F5", content: "林若溪发现血液变异", plant_node: "B2", payoff_node: "T5" },
        { id: "F6", content: "赵戈暗中试探嬴姓", plant_node: "T3", payoff_node: "T4" },
        { id: "F7", content: "陈伯竹杖中藏有古秦信物", plant_node: "B2", payoff_node: "B3" },
        { id: "F8", content: "嬴姓展现龙威能力", plant_node: "T4", payoff_node: "T5" },
        { id: "F9", content: "苏晚晴家族守陵盟约", plant_node: "B3", payoff_node: "B5" },
        { id: "F10", content: "丧尸病毒是秦帝失败副产物", plant_node: "T5", payoff_node: "T6" },
        { id: "F11", content: "境外幽冥族即将入侵", plant_node: "T5", payoff_node: "T7" },
        { id: "F12", content: "黑袍使者暗中窥探", plant_node: "B4", payoff_node: "B5" },
        { id: "F13", content: "陈伯临终交出虎符", plant_node: "B5", payoff_node: "T7" },
        { id: "F14", content: "血尸残存秦军军魂", plant_node: "B6", payoff_node: "T7" },
      ],
    };

    const result = buildGraphData(tree, []);

    // All 14 foreshadowing nodes should exist
    const fNodes = result.nodes.filter((n) => n.group === "foreshadow");
    expect(fNodes).toHaveLength(14);

    // Every foreshadowing should have a plant edge AND a payoff edge (no dangling)
    const plantEdges = result.edges.filter((e) => e.id.startsWith("plant:"));
    const payoffEdges = result.edges.filter((e) => e.id.startsWith("payoff:"));
    expect(plantEdges).toHaveLength(14);
    expect(payoffEdges).toHaveLength(14);

    // No null from/to on any plant/payoff edge
    for (const e of plantEdges) {
      expect(e.from).toBeTruthy();
      expect(e.to).toBeTruthy();
    }
    for (const e of payoffEdges) {
      expect(e.from).toBeTruthy();
      expect(e.to).toBeTruthy();
    }
  });

  it("still handles foreshadowing with unknown node IDs gracefully (no crash)", () => {
    const tree = {
      timeline: [
        { id: "T1", development_node: "开端", order: 1, chapter_start: 1, chapter_end: 3 },
      ],
      foreshadowing: [
        { id: "F1", content: "伏笔A", plant_node: "Z99", payoff_node: "T1" },
      ],
    };
    // Should not throw
    const result = buildGraphData(tree, []);
    expect(result.nodes.filter((n) => n.group === "foreshadow")).toHaveLength(1);
  });
});
