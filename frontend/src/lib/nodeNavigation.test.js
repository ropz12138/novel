import { describe, expect, it } from "vitest";
import { firstChapterNode, orderedNavigationNodes } from "./nodeNavigation";

const node = (id, type, sort_order = 1) => ({ id, data: { type, sort_order } });
describe("章节导航", () => {
  it("章节按顺序排列，再列出角色与设定", () => {
    expect(orderedNavigationNodes([node("c2", "chapter", 2), node("n", "note"), node("c1", "chapter"),
      node("r", "reviewer_note"), node("w", "worldbuilding"), node("hero", "character")]).map(n => n.id))
      .toEqual(["c1", "c2", "hero", "w", "n", "r"]);
  });
  it("定位首章，空作品返回 null", () => {
    expect(firstChapterNode([node("c2", "chapter", 2), node("c1", "chapter")]).id).toBe("c1");
    expect(firstChapterNode([node("n", "note")])).toBeNull();
  });
});
