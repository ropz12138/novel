import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it } from "vitest";
import InlineTextDiff from "./InlineTextDiff";

afterEach(cleanup);

it("renders a multiline replacement as one submitted group", async () => {
  const user = userEvent.setup();
  const newText = "前文新的第一行。\n\n新的第二行。结尾。";
  render(<InlineTextDiff oldText="前文旧段落结尾。" newText={newText} />);
  expect(screen.getByTestId("inline-diff-new").textContent).toBe(newText);
  expect(screen.getByTestId("inline-diff-new").querySelectorAll("[data-diff-kind]")).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "对照" }));
  expect(screen.getByTestId("inline-diff-old").textContent).toBe("前文旧段落结尾。");
  expect(screen.getByTestId("inline-diff-new").textContent).toBe(newText);
});

it("renders a full chapter insertion without exposing intra-group controls", () => {
  const newText = "新章。\n\n".repeat(4000);
  render(<InlineTextDiff oldText="" newText={newText} showOld={false} />);
  expect(screen.getByTestId("inline-diff-new").textContent).toBe(newText);
  expect(screen.getByTestId("inline-diff-new").querySelectorAll("[data-diff-kind=insert]")).toHaveLength(1);
  expect(screen.queryByRole("button", { name: "删除新增文本" })).toBeNull();
});
