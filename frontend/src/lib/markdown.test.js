import { describe, expect, it } from "vitest";
import { remarkHtmlBreaks } from "./markdown";

describe("remarkHtmlBreaks", () => {
  it("converts only br html nodes into markdown break nodes", () => {
    const tree = {
      type: "root",
      children: [{
        type: "paragraph",
        children: [
          { type: "text", value: "甲" },
          { type: "html", value: "<br />" },
          { type: "html", value: "<strong>乙</strong>" },
        ],
      }],
    };
    remarkHtmlBreaks()(tree);
    expect(tree.children[0].children).toEqual([
      { type: "text", value: "甲" },
      { type: "break" },
      { type: "html", value: "<strong>乙</strong>" },
    ]);
  });
});
