import { describe, expect, it } from "vitest";
import { getCharacterLinks } from "./CharacterDetailDrawer";

const MOCK_CHARACTER_LINKS = [
  {
    character_name: "嬴萧",
    timeline_id: "N1",
    link_type: "appear",
    summary: "首次登场",
    weight: 3,
  },
  {
    character_name: "嬴萧",
    timeline_id: "N2",
    link_type: "lead",
    summary: "主导冲突",
    weight: 5,
  },
  {
    character_name: "苏婉",
    timeline_id: "N1",
    link_type: "ally",
    summary: "与嬴萧并肩",
    weight: 2,
  },
];

const MOCK_TIMELINE = [
  { id: "N1", development_node: "序幕", summary: "故事开始" },
  { id: "N2", development_node: "冲突爆发", summary: "矛盾激化" },
];

describe("getCharacterLinks", () => {
  it("returns links matching the character name with timeline titles", () => {
    const result = getCharacterLinks("嬴萧", MOCK_CHARACTER_LINKS, MOCK_TIMELINE);
    expect(result).toHaveLength(2);
    expect(result[0].timeline_id).toBe("N1");
    expect(result[0].timeline_title).toBe("N1 序幕");
    expect(result[0].link_type).toBe("appear");
    expect(result[1].timeline_id).toBe("N2");
    expect(result[1].timeline_title).toBe("N2 冲突爆发");
    expect(result[1].link_type).toBe("lead");
  });

  it("returns empty array when no links match the character name", () => {
    const result = getCharacterLinks("路人甲", MOCK_CHARACTER_LINKS, MOCK_TIMELINE);
    expect(result).toEqual([]);
  });

  it("handles null characterName", () => {
    expect(getCharacterLinks(null, MOCK_CHARACTER_LINKS, MOCK_TIMELINE)).toEqual([]);
  });

  it("handles undefined characterName", () => {
    expect(getCharacterLinks(undefined, MOCK_CHARACTER_LINKS, MOCK_TIMELINE)).toEqual([]);
  });

  it("handles empty string characterName", () => {
    expect(getCharacterLinks("", MOCK_CHARACTER_LINKS, MOCK_TIMELINE)).toEqual([]);
  });

  it("falls back to timeline_id when timeline has no matching node", () => {
    const result = getCharacterLinks(
      "嬴萧",
      [{ character_name: "嬴萧", timeline_id: "X99", link_type: "appear" }],
      []
    );
    expect(result).toHaveLength(1);
    expect(result[0].timeline_title).toBe("X99");
  });

  it("falls back to timeline_id when timeline is null", () => {
    const result = getCharacterLinks(
      "嬴萧",
      [{ character_name: "嬴萧", timeline_id: "X99", link_type: "lead" }],
      null
    );
    expect(result).toHaveLength(1);
    expect(result[0].timeline_title).toBe("X99");
  });

  it("handles non-array characterLinks gracefully", () => {
    expect(getCharacterLinks("嬴萧", null, MOCK_TIMELINE)).toEqual([]);
    expect(getCharacterLinks("嬴萧", undefined, MOCK_TIMELINE)).toEqual([]);
    expect(getCharacterLinks("嬴萧", "not an array", MOCK_TIMELINE)).toEqual([]);
  });

  it("preserves all link fields in result", () => {
    const result = getCharacterLinks("嬴萧", MOCK_CHARACTER_LINKS, MOCK_TIMELINE);
    expect(result[0]).toEqual({
      character_name: "嬴萧",
      timeline_id: "N1",
      link_type: "appear",
      summary: "首次登场",
      weight: 3,
      timeline_title: "N1 序幕",
    });
  });

  it("skips non-object entries in characterLinks", () => {
    const mixed = [null, "string", 42, { character_name: "嬴萧", timeline_id: "N1", link_type: "appear" }];
    const result = getCharacterLinks("嬴萧", mixed, MOCK_TIMELINE);
    expect(result).toHaveLength(1);
    expect(result[0].timeline_id).toBe("N1");
  });
});
