import { describe, expect, it } from "vitest";

import { normalizeTodoItem } from "./sseEventHandlers";


describe("normalizeTodoItem", () => {
  it("normalizes defaults and legacy id", () => {
    expect(normalizeTodoItem({ id: "T1", task: "写大纲" })).toMatchObject({
      task_id: "T1",
      task: "写大纲",
      owner: "supervisor",
      status: "pending",
      depth: 0,
      depends_on: [],
    });
  });

  it("preserves current todo fields", () => {
    const item = {
      db_id: "db-1",
      task_id: "T1",
      task: "写章节",
      owner: "supervisor",
      status: "completed",
      result_summary: "完成",
    };
    expect(normalizeTodoItem(item)).toMatchObject(item);
  });
});
