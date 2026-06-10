import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RequirementsDocEditor } from "./RequirementsDocEditor";

function getEditorInput() {
  return screen.getByLabelText("requirements-codemirror");
}

describe("RequirementsDocEditor", () => {
  it("renders preview only by default", () => {
    render(<RequirementsDocEditor value="# 标题" onChange={vi.fn()} />);
    expect(screen.getByTestId("requirements-doc-editor")).toBeDefined();
    expect(screen.getByTestId("requirements-doc-preview")).toBeDefined();
    expect(
      within(screen.getByTestId("requirements-doc-preview")).getByRole("heading", {
        level: 1,
      }).textContent,
    ).toBe("标题");
    expect(screen.queryByLabelText("requirements-codemirror")).toBeNull();
  });

  it("calls onChange when user edits", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<RequirementsDocEditor value="" onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: /编辑/ }));
    fireEvent.change(getEditorInput(), { target: { value: "新需求" } });
    expect(onChange).toHaveBeenCalledWith("新需求");
  });

  it("reflects updated value in preview", () => {
    const { rerender } = render(
      <RequirementsDocEditor value="第一版" onChange={vi.fn()} />,
    );
    expect(screen.getByTestId("requirements-doc-preview").textContent).toContain("第一版");
    rerender(<RequirementsDocEditor value="第二版" onChange={vi.fn()} />);
    expect(screen.getByTestId("requirements-doc-preview").textContent).toContain("第二版");
  });

  it("can switch to edit-only mode", async () => {
    const user = userEvent.setup();
    render(<RequirementsDocEditor value="仅编辑" onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: /编辑/ }));
    expect(screen.queryByTestId("requirements-doc-preview")).toBeNull();
    expect(getEditorInput().value).toBe("仅编辑");
  });
});
