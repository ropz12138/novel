import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CurrentTaskPanel } from "./CurrentTaskPanel";
const item = { id: "plan", type: "requirements_todolist", todoCard: { intent_summary: "第三章设计", ready_to_execute: true, todolist: [{ task_id: "T1", task: "调研参考", status: "completed" }, { task_id: "T2", task: "设计场景", status: "in_progress" }] } };
describe("CurrentTaskPanel", () => {
  it("shows the latest plan after later messages and follows live updates", () => {
    const { rerender } = render(<CurrentTaskPanel timeline={[item, { id: "reply", content: "后续消息" }]} />);
    expect(screen.getByRole("button", { name: /第三章设计.*已完成 1\/2.*进行中/ }).getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("调研参考")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /第三章设计/ }));
    expect(screen.getByText("调研参考")).toBeDefined();
    rerender(<CurrentTaskPanel timeline={[{ ...item, todoCard: { ...item.todoCard, todolist: item.todoCard.todolist.map(t => ({ ...t, status: "completed" })) } }]} />);
    expect(screen.getByRole("button", { name: /已完成 2\/2.*全部完成/ })).toBeDefined();
  });
  it("resets for a new plan and clears with the session", () => {
    const { rerender } = render(<CurrentTaskPanel timeline={[item]} />);
    fireEvent.click(screen.getByRole("button", { name: /第三章设计/ }));
    expect(screen.queryByRole("button", { name: "定位任务消息" })).toBeNull();
    rerender(<CurrentTaskPanel timeline={[item, { ...item, id: "new", todoCard: { ...item.todoCard, intent_summary: "第四章", ready_to_execute: false } }]} />);
    expect(screen.getByRole("button", { name: /第四章.*等待你确认/ }).getAttribute("aria-expanded")).toBe("false");
    rerender(<CurrentTaskPanel timeline={[]} />);
    expect(screen.queryByRole("region", { name: "当前任务" })).toBeNull();
  });
  it("shows waiting from the turn delivery status and clears it when execution resumes", () => {
    const pending = { ...item, todoCard: { intent_summary: "出发时间", ready_to_execute: true, delivery_status: "needs_user", todolist: [{ task_id: "T1", task: "确认出发时间", status: "pending" }] } };
    const { rerender } = render(<CurrentTaskPanel timeline={[pending]} />);
    expect(screen.getByRole("button", { name: /出发时间.*等待你确认/ })).toBeDefined();
    rerender(<CurrentTaskPanel timeline={[{ ...pending, todoCard: { ...pending.todoCard, delivery_status: undefined } }]} />);
    expect(screen.getByRole("button", { name: /出发时间.*待处理/ })).toBeDefined();
    rerender(<CurrentTaskPanel timeline={[{ ...pending, todoCard: { ...pending.todoCard, delivery_status: "needs_revision" } }]} />);
    expect(screen.getByRole("button", { name: /出发时间.*需要处理/ })).toBeDefined();
  });
});
