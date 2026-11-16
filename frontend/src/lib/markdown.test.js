import { describe, expect, it } from "vitest";
import { remarkHtmlBreaks, renderLiteralNewlines } from "./markdown";

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

describe("renderLiteralNewlines", () => {
  it("turns literal newline escapes into markdown paragraph and hard breaks", () => {
    expect(renderLiteralNewlines("接成：\\n\\n“老头揉左膝。”\\n→“砸膝。”")).toBe(
      "接成：\n\n“老头揉左膝。”  \n→“砸膝。”",
    );
  });

  it("leaves real newlines and code spans unchanged", () => {
    expect(renderLiteralNewlines("甲\n乙")).toBe("甲\n乙");
    expect(renderLiteralNewlines("代码里的 `\\n` 保持原样")).toBe("代码里的 `\\n` 保持原样");
    expect(renderLiteralNewlines("```js\nconst gap = \"\\n\";\n```")).toBe("```js\nconst gap = \"\\n\";\n```");
  });
});
