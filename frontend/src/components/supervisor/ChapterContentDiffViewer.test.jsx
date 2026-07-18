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

  it("expands hunk to show old and new text", async () => {
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
    expect(screen.getByText("旧段落")).toBeDefined();
    expect(screen.getByText("新段落")).toBeDefined();
  });

  it("renders delete hunk", async () => {
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
    expect(screen.getByText("待删段落")).toBeDefined();
  });

  it("returns null when hunks empty", () => {
    const { container } = render(<ChapterContentDiffViewer hunks={[]} summary={{}} />);
    expect(container.firstChild).toBeNull();
  });
});
