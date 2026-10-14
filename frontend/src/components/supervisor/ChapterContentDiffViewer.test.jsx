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

  it("shows the submitted new group first and reveals the complete old group in comparison", async () => {
    const user = userEvent.setup();
    render(
      <ChapterContentDiffViewer
        hunks={[{
          type: "replace",
          paragraph_index: 1,
          old_text: "旧段落",
          new_text: "新段落",
        }]}
        summary={{}}
      />
    );

    await user.click(screen.getByRole("button"));
    expect(screen.queryByTestId("inline-diff-old")).toBeNull();
    expect(screen.getByTestId("inline-diff-new").textContent).toBe("新段落");
    await user.click(screen.getByRole("button", { name: "对照" }));
    expect(screen.getByTestId("inline-diff-old").textContent).toBe("旧段落");
    expect(screen.getByTestId("inline-diff-new").textContent).toBe("新段落");
  });

  it("keeps a replacement as one indivisible submitted group", async () => {
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
    expect(screen.queryByText("废墟")).toBeNull();
    const group = screen.getByTestId("inline-diff-new").querySelector('[data-diff-kind="replace"]');
    expect(group.textContent).toBe("林川在雨中遇见苏婉。");
    expect(screen.getByTestId("inline-diff-new").querySelectorAll("[data-diff-kind]")).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "对照" }));
    expect(screen.getByTestId("inline-diff-old").textContent).toBe("林川在废墟中遇见苏婉。");
  });

  it("does not infer a deleted subsegment inside a submitted replacement", async () => {
    const user = userEvent.setup();
    render(
      <ChapterContentDiffViewer
        hunks={[{
          type: "replace",
          paragraph_index: 1,
          old_text: "甲删除乙",
          new_text: "甲乙",
        }]}
        summary={{}}
      />
    );

    await user.click(screen.getByRole("button"));
    expect(screen.getByTestId("inline-diff-new").textContent).toBe("甲乙");
    expect(screen.queryByRole("button", { name: "查看已删除文本" })).toBeNull();
  });

  it("renders a delete hunk as a single red old-text region", async () => {
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
    expect(screen.queryByTestId("inline-diff-old")).toBeNull();
    await user.click(screen.getByRole("button", { name: "查看已删除段落" }));
    expect(screen.getByRole("tooltip").textContent).toContain("待删段落");
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

  it("returns null when hunks empty", () => {
    const { container } = render(<ChapterContentDiffViewer hunks={[]} summary={{}} />);
    expect(container.firstChild).toBeNull();
  });
});
