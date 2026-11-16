import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ChapterContentDiffViewer } from "./ChapterContentDiffViewer.jsx";

describe("ChapterContentDiffViewer", () => {
  it("renders summary and hunks", () => {
    render(
      <ChapterContentDiffViewer
        title="第1章"
        hunks={[{
          type: "replace",
          paragraph_index: 2,
          old_text: "旧段落",
          new_text: "新段落",
        }]}
        summary={{ paragraphs_changed: 1, chars_added: 3, chars_removed: 3 }}
        wordCount={100}
        wordCountDelta={0}
      />
    );

    expect(screen.getByText("第1章")).toBeDefined();
    expect(screen.getByText(/1 处修改/)).toBeDefined();
    expect(screen.getByText(/替换/)).toBeDefined();
  });

  it("shows old text above new text when a replacement is expanded", async () => {
    const user = userEvent.setup();
    render(
      <ChapterContentDiffViewer
        hunks={[{
          type: "replace",
          paragraph_index: 1,
          old_text: "林川在废墟中遇见苏婉。",
          new_text: "林川在雨中遇见苏婉。",
        }]}
        summary={{}}
      />
    );

    await user.click(screen.getByRole("button"));
    const oldText = screen.getByTestId("inline-diff-old");
    const newText = screen.getByTestId("inline-diff-new");
    expect(oldText.textContent).toBe("林川在废墟中遇见苏婉。");
    expect(newText.textContent).toBe("林川在雨中遇见苏婉。");
    expect(oldText.compareDocumentPosition(newText) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByRole("button", { name: "对照" })).toBeNull();
  });

  it("renders a delete hunk as the old paragraph only", async () => {
    const user = userEvent.setup();
    render(
      <ChapterContentDiffViewer
        hunks={[{
          type: "delete",
          paragraph_index: 3,
          old_text: "待删段落",
          new_text: "",
        }]}
        summary={{}}
      />
    );

    await user.click(screen.getByRole("button"));
    expect(screen.getByTestId("inline-diff-old").textContent).toBe("待删段落");
    expect(screen.queryByTestId("inline-diff-new")).toBeNull();
  });

  it("renders an insert hunk as a single green new-text region", async () => {
    const user = userEvent.setup();
    render(
      <ChapterContentDiffViewer
        hunks={[{
          type: "insert_after",
          paragraph_index: 3,
          old_text: "",
          new_text: "新增段落",
        }]}
        summary={{}}
      />
    );

    await user.click(screen.getByRole("button"));
    expect(screen.getByTestId("inline-diff-new").textContent).toBe("新增段落");
    expect(screen.getByText("新增段落").getAttribute("data-diff-kind")).toBe("insert");
    expect(screen.queryByTestId("inline-diff-old")).toBeNull();
    expect(screen.queryByTestId("inline-diff-divider")).toBeNull();
  });

  it("shows only changed paragraphs when a hunk contains the whole chapter", async () => {
    const user = userEvent.setup();
    render(
      <ChapterContentDiffViewer
        hunks={[{
          type: "replace",
          paragraph_index: 1,
          old_text: "开头未改。\n\n林川在废墟中遇见苏婉。\n\n结尾未改。",
          new_text: "开头未改。\n\n林川在雨中遇见苏婉。\n\n结尾未改。",
        }]}
        summary={{ paragraphs_changed: 1 }}
      />
    );

    await user.click(screen.getByRole("button"));
    expect(screen.getByText("段落 2")).toBeDefined();
    expect(screen.getByText(/1 处修改/)).toBeDefined();
    expect(screen.queryByText(/开头未改/)).toBeNull();
    expect(screen.queryByText(/结尾未改/)).toBeNull();
    expect(screen.getByTestId("inline-diff-old").textContent).toContain("废墟");
    expect(screen.getByTestId("inline-diff-new").textContent).toContain("雨");
  });

  it("renders markdown in a notes diff instead of the source marks", async () => {
    const user = userEvent.setup();
    render(
      <ChapterContentDiffViewer
        markdown
        hunks={[{
          type: "replace",
          paragraph_index: 1,
          old_text: "## 旧标题\n\n- 旧条目",
          new_text: "## 新标题\n\n**重点**",
        }]}
        summary={{}}
      />
    );

    for (const button of screen.getAllByRole("button", { name: /段落/ })) {
      await user.click(button);
    }
    expect(screen.getByRole("heading", { name: "旧标题" })).toBeDefined();
    expect(screen.getByRole("heading", { name: "新标题" })).toBeDefined();
    expect(screen.getByRole("listitem").textContent).toBe("旧条目");
    expect(screen.getByText("重点").tagName).toBe("STRONG");
    expect(screen.getAllByTestId("notes-diff-markdown").every((node) => node.className.includes("max-w-full") && node.className.includes("overflow-hidden"))).toBe(true);
    expect(screen.queryByText(/##/)).toBeNull();
    expect(screen.queryByText(/\*\*重点\*\*/)).toBeNull();
  });

  it("returns null when hunks empty", () => {
    const { container } = render(<ChapterContentDiffViewer hunks={[]} summary={{}} />);
    expect(container.firstChild).toBeNull();
  });
});
