import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import ModifiedNodeCapsules from "./ModifiedNodeCapsules";

it("lets the user remove a node modification before sending", () => {
  const onRemove = vi.fn();
  render(<ModifiedNodeCapsules nodes={[{ id: "n1", label: "第一章" }]} onRemove={onRemove} />);
  expect(screen.getByText("已修改：第一章")).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "移除修改记录 第一章" }));
  expect(onRemove).toHaveBeenCalledWith("n1");
});
