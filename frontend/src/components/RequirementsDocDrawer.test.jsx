import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RequirementsDocDrawer } from "./RequirementsDocDrawer";

function getEditorInput() {
  return screen.getByLabelText("requirements-codemirror");
}

describe("RequirementsDocDrawer", () => {
  beforeEach(() => {
    vi.stubGlobal("confirm", vi.fn(() => true));
  });

  it("renders markdown editor when open", () => {
    render(
      <RequirementsDocDrawer
        open
        content="# 需求"
        onSave={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByTestId("requirements-doc-editor")).toBeDefined();
    expect(
      within(screen.getByTestId("requirements-doc-preview")).getByRole("heading", {
        level: 1,
      }).textContent,
    ).toBe("需求");
  });

  it("does not render when closed", () => {
    render(
      <RequirementsDocDrawer open={false} content="" onSave={vi.fn()} />,
    );
    expect(screen.queryByTestId("requirements-doc-editor")).toBeNull();
  });

  it("calls onSave with edited draft when save is clicked", async () => {
    const onSave = vi.fn();
    const user = userEvent.setup();
    render(
      <RequirementsDocDrawer open content="旧内容" onSave={onSave} />,
    );
    await user.click(screen.getByRole("button", { name: /编辑/ }));
    await user.type(getEditorInput(), "追加");
    const saveBtn = screen.getByRole("button", { name: /保存/ });
    expect(saveBtn.disabled).toBe(false);
    await user.click(saveBtn);
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave.mock.calls[0][0]).toContain("旧内容");
    expect(onSave.mock.calls[0][0]).toContain("追加");
  });

  it("disables save when content matches saved", () => {
    render(
      <RequirementsDocDrawer open content="无改动" onSave={vi.fn()} />,
    );
    const saveBtn = screen.getByRole("button", { name: /保存/ });
    expect(saveBtn.disabled).toBe(true);
  });

  it("resets draft when reopened after content prop changes", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <RequirementsDocDrawer open content="版本一" onSave={vi.fn()} />,
    );
    await user.click(screen.getByRole("button", { name: /编辑/ }));
    expect(getEditorInput().value).toBe("版本一");
    rerender(
      <RequirementsDocDrawer open={false} content="版本二" onSave={vi.fn()} />,
    );
    rerender(
      <RequirementsDocDrawer open content="版本二" onSave={vi.fn()} />,
    );
    await user.click(screen.getByRole("button", { name: /编辑/ }));
    expect(getEditorInput().value).toBe("版本二");
  });
});
