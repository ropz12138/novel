import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import InlineTextDiff from "./InlineTextDiff";

afterEach(cleanup);

it("highlights only changed characters and reveals their original text above", async () => {
  const user = userEvent.setup();
  render(<InlineTextDiff oldText="鲜血渗出，体内的始祖血脉与晶核共鸣。" newText="鲜血渗出，体内刚苏醒的霸道血气与晶核共鸣。" />);
  const result = screen.getByTestId("inline-diff-new");
  expect(result.textContent).toBe("鲜血渗出，体内刚苏醒的霸道血气与晶核共鸣。");
  expect(result.querySelector('[data-diff-kind="equal"]')).toBeNull();
  expect(result.querySelectorAll('[data-diff-kind="replace"]').length).toBeGreaterThan(0);
  for (const changed of result.querySelectorAll("[data-diff-kind]")) {
    expect(changed.textContent).not.toContain("鲜血渗出，体内");
    expect(changed.textContent).not.toContain("与晶核共鸣。");
    expect(changed.className).toContain(changed.dataset.diffKind === "insert" ? "bg-emerald-100" : changed.dataset.diffKind === "delete" ? "bg-red-100" : "bg-amber-100");
  }
  await user.click(screen.getAllByRole("button", { name: "查看修改原文" })[0]);
  expect(screen.getByRole("tooltip").getAttribute("data-popover-placement")).toBe("above-anchor");
  expect(screen.getByRole("tooltip").textContent).toContain("原文");
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("tooltip")).toBeNull();
});

it("leaves identical text unhighlighted", () => {
  render(<InlineTextDiff oldText="相同正文。" newText="相同正文。" />);
  expect(screen.getByTestId("inline-diff-new").querySelectorAll("[data-diff-kind]")).toHaveLength(0);
});

it("keeps a deleted fragment accessible at its original position", async () => {
  const user = userEvent.setup();
  render(<InlineTextDiff oldText="甲删除乙" newText="甲乙" />);
  await user.click(screen.getByRole("button", { name: "查看已删除文本" }));
  expect(screen.getByRole("tooltip").textContent).toContain("删除");
  await user.click(document.body);
  expect(screen.queryByRole("tooltip")).toBeNull();
});

it("preserves all multiline text", () => {
  const newText = "前文新的第一行。\n\n新的第二行。结尾。";
  render(<InlineTextDiff oldText="前文旧段落结尾。" newText={newText} />);
  expect(screen.getByTestId("inline-diff-new").textContent).toBe(newText);
});

it("renders a full chapter insertion without exposing intra-group controls", () => {
  const newText = "新章。\n\n".repeat(4000);
  render(<InlineTextDiff oldText="" newText={newText} showOld={false} />);
  expect(screen.getByTestId("inline-diff-new").textContent).toBe(newText);
  expect(screen.getByTestId("inline-diff-new").querySelectorAll("[data-diff-kind=insert]")).toHaveLength(1);
  expect(screen.queryByRole("button", { name: "删除新增文本" })).toBeNull();
});


it("shows a bloodline replacement as one highlight with the complete original phrase", async () => {
  const user = userEvent.setup();
  render(<InlineTextDiff oldText="体内始祖血脉共鸣。" newText="体内霸道血气共鸣。" />);
  const highlights = screen.getAllByRole("button", { name: "查看修改原文" });
  expect(highlights).toHaveLength(1);
  expect(highlights[0].textContent).toBe("霸道血气");
  await user.click(highlights[0]);
  expect(screen.getByRole("tooltip").textContent).toBe("原文始祖血脉");
});


it.each([
  ["恢复", "始祖血脉在体内涌动，旧光。", "始祖血脉在体内涌动，新光。"],
  ["删除", "霸道血气在体内涌动，旧光。", "霸道血气在体内涌动，新光。"],
])("%s resolves only the clicked original fragment", async (label, oldText, newText) => {
  const user = userEvent.setup();
  const onResolveChange = vi.fn().mockResolvedValue(true);
  render(<InlineTextDiff oldText="始祖血脉在体内涌动，旧光。" newText="霸道血气在体内涌动，新光。" onResolveChange={onResolveChange} />);
  await user.click(screen.getByText("霸道血气"));
  await user.click(screen.getByRole("button", { name: label }));
  expect(onResolveChange).toHaveBeenCalledWith({ oldText, newText });
  expect(screen.queryByRole("tooltip")).toBeNull();
});

it("keeps the original popover open when saving fails", async () => {
  const user = userEvent.setup();
  render(<InlineTextDiff oldText="旧文" newText="新文" onResolveChange={vi.fn().mockResolvedValue(false)} />);
  await user.click(screen.getByRole("button", { name: "查看修改原文" }));
  await user.click(screen.getByRole("button", { name: "恢复" }));
  expect(screen.getByRole("tooltip")).toBeDefined();
});

it("does not offer original-text actions in read-only comparisons", async () => {
  const user = userEvent.setup();
  render(<InlineTextDiff oldText="旧" newText="新" />);
  await user.click(screen.getByRole("button", { name: "查看修改原文" }));
  expect(screen.queryByRole("button", { name: "恢复" })).toBeNull();
  expect(screen.queryByRole("button", { name: "删除" })).toBeNull();
});


it("resolves the clicked occurrence when identical changes appear twice", async () => {
  const user = userEvent.setup();
  const onResolveChange = vi.fn().mockResolvedValue(true);
  render(<InlineTextDiff oldText="旧文，中间相同，旧文。" newText="新文，中间相同，新文。" onResolveChange={onResolveChange} />);
  await user.click(screen.getAllByRole("button", { name: "查看修改原文" })[1]);
  await user.click(screen.getByRole("button", { name: "恢复" }));
  expect(onResolveChange).toHaveBeenCalledWith({ oldText: "旧文，中间相同，旧文。", newText: "新文，中间相同，旧文。" });
});

it.each([
  ["恢复", "删除段。"],
  ["删除", ""],
])("%s also resolves an original-only deletion", async (label, text) => {
  const user = userEvent.setup();
  const onResolveChange = vi.fn().mockResolvedValue(true);
  render(<InlineTextDiff oldText="删除段。" newText="" showNew={false} onResolveChange={onResolveChange} />);
  await user.click(screen.getByRole("button", { name: "查看已删除段落" }));
  await user.click(screen.getByRole("button", { name: label }));
  expect(onResolveChange).toHaveBeenCalledWith({ oldText: text, newText: text });
});


it("renders green insertions without an original-text popup and offers a hover-only delete cross", async () => {
  const user = userEvent.setup();
  const onResolveChange = vi.fn().mockResolvedValue(true);
  render(<InlineTextDiff oldText="甲乙旧丙" newText="甲新增乙新丙" onResolveChange={onResolveChange} />);
  const insertion = screen.getByText("新增");
  expect(insertion.closest('[data-diff-kind="insert"]').className).toContain("bg-emerald-100");
  expect(screen.getByRole("button", { name: "查看修改原文" }).className).toContain("bg-amber-100");
  await user.click(screen.getByRole("button", { name: "查看修改原文" }));
  expect(screen.getByRole("tooltip")).toBeDefined();
  await user.click(insertion);
  expect(screen.queryByRole("tooltip")).toBeNull();
  const remove = screen.getByRole("button", { name: "删除新增文本" });
  expect(remove.className).toContain("opacity-0");
  expect(remove.className).toContain("group-hover/inline-insert:opacity-100");
  expect(remove.className).toContain("right-0");
  expect(remove.className).toContain("top-0");
  await user.hover(insertion);
  await user.click(remove);
  expect(onResolveChange).toHaveBeenCalledWith({ oldText: "甲乙旧丙", newText: "甲乙新丙" });
  expect(screen.queryByRole("tooltip")).toBeNull();
});

it("removes only the selected occurrence of an insertion", async () => {
  const user = userEvent.setup();
  const onResolveChange = vi.fn().mockResolvedValue(true);
  render(<InlineTextDiff oldText="甲，中间相同，乙。" newText="甲新增，中间相同，乙新增。" onResolveChange={onResolveChange} />);
  await user.click(screen.getAllByRole("button", { name: "删除新增文本" })[1]);
  expect(onResolveChange).toHaveBeenCalledWith({ oldText: "甲，中间相同，乙。", newText: "甲新增，中间相同，乙。" });
});

it("can remove a whole inserted paragraph", async () => {
  const user = userEvent.setup();
  const onResolveChange = vi.fn().mockResolvedValue(true);
  render(<InlineTextDiff oldText="" newText="新增一段。\n\n另一行。" showOld={false} onResolveChange={onResolveChange} />);
  await user.click(screen.getByRole("button", { name: "删除新增文本" }));
  expect(onResolveChange).toHaveBeenCalledWith({ oldText: "", newText: "" });
});

it("retains inserted content when deleting it fails", async () => {
  const user = userEvent.setup();
  render(<InlineTextDiff oldText="甲乙" newText="甲新增乙" onResolveChange={vi.fn().mockResolvedValue(false)} />);
  await user.click(screen.getByRole("button", { name: "删除新增文本" }));
  expect(screen.getByTestId("inline-diff-new").textContent).toBe("甲新增乙");
  expect(screen.getByRole("button", { name: "删除新增文本" }).disabled).toBe(false);
  expect(screen.queryByRole("tooltip")).toBeNull();
});

it("keeps multiline replacements in normal text flow and keyboard accessible", async () => {
  const user = userEvent.setup();
  const oldText = "前文。ABC结尾。";
  const newText = "前文。跨步，拧腰轮圆！\n\n起身，沉重的铸铁锯齿撕裂恶风。结尾。";
  render(<InlineTextDiff oldText={oldText} newText={newText} />);
  const highlights = screen.getAllByRole("button", { name: "查看修改原文" });
  expect(highlights.some((element) => element.textContent.includes("\n"))).toBe(true);
  for (const element of highlights) {
    expect(element.tagName).toBe("SPAN");
    expect(element.tabIndex).toBe(0);
    expect(element.className).toContain("box-decoration-clone");
  }
  expect(screen.getByTestId("inline-diff-new").textContent).toBe(newText);
  highlights[0].focus();
  await user.keyboard("{Enter}");
  expect(screen.getByRole("tooltip")).toBeDefined();
  await user.keyboard("{Escape}");
  await user.keyboard(" ");
  expect(screen.getByRole("tooltip")).toBeDefined();
});
