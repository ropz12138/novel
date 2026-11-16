import { describe, expect, it } from "vitest";
import { copyDialogText, describeNodeCopy } from "./nodeCopy";

function flowNode(id, type, label, extra = {}) {
  return {
    id,
    data: { type, label, extra_data: extra, sort_order: 1 },
  };
}

const nodes = [
  flowNode("vol", "volume", "第一卷"),
  flowNode("plot", "plot", "开端"),
  flowNode("ch", "chapter", "第一章", {
    characters: [
      { id: "hero", name: "林舟" },
      { id: "hero", name: "林舟" },
      { id: "missing", name: "已删除" },
    ],
  }),
  flowNode("ch2", "chapter", "第二章", {
    characters: [{ id: "hero", name: "林舟" }],
  }),
  flowNode("hero", "character", "林舟"),
  flowNode("note", "note", "写作要求"),
];

const edges = [
  { id: "vol-plot", source: "vol", target: "plot" },
  { id: "plot-ch", source: "plot", target: "ch" },
  { id: "plot-ch2", source: "plot", target: "ch2" },
  { id: "ch-ch2", source: "ch", target: "ch2" },
];

describe("describeNodeCopy", () => {
  it("counts hierarchy descendants and distinct characters, ignoring same-level edges", () => {
    expect(describeNodeCopy(nodes, edges, "vol")).toEqual({
      rootId: "vol",
      title: "第一卷",
      descendantCount: 3,
      characterCount: 1,
      omittedCount: 1,
    });
    expect(describeNodeCopy(nodes, edges, "ch")).toMatchObject({
      descendantCount: 0,
      characterCount: 1,
      omittedCount: 1,
    });
  });

  it("returns null when the node is not on the canvas", () => {
    expect(describeNodeCopy(nodes, edges, "absent")).toBeNull();
  });
});

describe("copyDialogText", () => {
  it("describes a subtree, a single node, a missing node, and stale character refs", () => {
    expect(copyDialogText(describeNodeCopy(nodes, edges, "vol"))).toBe(
      "「第一卷」会连同下级 3 个节点、章节引用的 1 个角色，一起复制到所选作品，并作为独立结构放在那里。有 1 条已失效的角色引用不会带过去。",
    );
    expect(copyDialogText(describeNodeCopy(nodes, edges, "note"))).toBe(
      "「写作要求」会复制到所选作品，并作为独立结构放在那里。",
    );
    expect(copyDialogText(null)).toBe(
      "将此节点复制到所选作品，并作为独立结构放在那里。",
    );
  });
});
