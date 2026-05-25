import { describe, expect, it } from "vitest";
import {
  handleOutlineEditDiff,
  handleCharacterEditDiff,
  handleTodolistGenerated,
  handleTaskStatusUpdated,
  handleTodolistReadinessUpdated,
  createTimelineActions,
} from "./sseEventHandlers.js";

describe("handleOutlineEditDiff", () => {
  it("returns an addMessage action with outline_diff_card type", () => {
    const data = {
      message: "大纲已更新",
      operations: [{ op: "add" }],
      diff: { added: ["章节1"] },
      summary: { total_added: 1, total_modified: 0, total_removed: 0 },
    };

    const result = handleOutlineEditDiff(data);

    expect(result).toEqual({
      finalizeStep: true,
      setOutlineDiff: {
        diff: data.diff,
        summary: data.summary,
        message: data.message,
        operations: data.operations,
        readonly: false,
      },
      addMessage: {
        role: "assistant",
        content: "",
        meta: {
          type: "outline_diff_card",
          outlineDiffCard: {
            diff: data.diff,
            summary: data.summary,
            message: data.message,
            operations: data.operations,
            readonly: false,
          },
        },
      },
    });
  });

  it("handles empty data gracefully", () => {
    const result = handleOutlineEditDiff({});

    expect(result.finalizeStep).toBe(true);
    expect(result.addMessage.meta.type).toBe("outline_diff_card");
    expect(result.addMessage.meta.outlineDiffCard.diff).toBeUndefined();
    expect(result.addMessage.meta.outlineDiffCard.summary).toBeUndefined();
  });
});

describe("handleCharacterEditDiff", () => {
  it("returns an addMessage action with character_diff_card type", () => {
    const data = {
      diff: { added: ["角色A"] },
      summary: { total_added: 1, total_modified: 2, total_removed: 0 },
    };

    const result = handleCharacterEditDiff(data);

    expect(result).toEqual({
      addMessage: {
        role: "assistant",
        content: "",
        meta: {
          type: "character_diff_card",
          characterDiffCard: {
            diff: data.diff,
            summary: data.summary,
            readonly: false,
          },
        },
      },
    });
  });

  it("handles empty data gracefully", () => {
    const result = handleCharacterEditDiff({});

    expect(result.addMessage.meta.type).toBe("character_diff_card");
    expect(result.addMessage.meta.characterDiffCard.diff).toBeUndefined();
    expect(result.addMessage.meta.characterDiffCard.summary).toBeUndefined();
  });
});

describe("handleTodolistGenerated", () => {
  it("returns an addMessage action with requirements_todolist type", () => {
    const data = {
      intent_summary: "修改大纲和角色卡",
      todolist: [
        { db_id: "ti-1", task_id: "T1", task: "编辑大纲", owner: "supervisor", status: "pending" },
        { db_id: "ti-2", task_id: "T2", task: "编辑角色", owner: "supervisor", status: "pending" },
      ],
      ready_to_execute: true,
    };

    const result = handleTodolistGenerated(data);

    expect(result).toEqual({
      finalizeStep: true,
      addMessage: {
        role: "assistant",
        content: "",
        meta: {
          type: "requirements_todolist",
          todoCard: {
            intent_summary: "修改大纲和角色卡",
            todolist: [
              {
                db_id: "ti-1",
                task_id: "T1",
                task: "编辑大纲",
                owner: "supervisor",
                status: "pending",
                depends_on: [],
                done_criteria: "",
              },
              {
                db_id: "ti-2",
                task_id: "T2",
                task: "编辑角色",
                owner: "supervisor",
                status: "pending",
                depends_on: [],
                done_criteria: "",
              },
            ],
            ready_to_execute: true,
          },
        },
      },
    });
  });

  it("handles empty data gracefully", () => {
    const result = handleTodolistGenerated({});

    expect(result.finalizeStep).toBe(true);
    expect(result.addMessage.meta.type).toBe("requirements_todolist");
    expect(result.addMessage.meta.todoCard.intent_summary).toBe("");
    expect(result.addMessage.meta.todoCard.todolist).toEqual([]);
    expect(result.addMessage.meta.todoCard.ready_to_execute).toBe(false);
  });

  it("defaults ready_to_execute to false when missing", () => {
    const result = handleTodolistGenerated({ intent_summary: "测试" });

    expect(result.addMessage.meta.todoCard.ready_to_execute).toBe(false);
  });

  it("normalizes legacy todolist items without db_id", () => {
    const data = {
      todolist: [
        { id: "T1", task: "旧格式任务", owner: "outline_agent" },
      ],
    };

    const result = handleTodolistGenerated(data);
    const item = result.addMessage.meta.todoCard.todolist[0];

    expect(item.db_id).toBe("");
    expect(item.task_id).toBe("T1");
    expect(item.task).toBe("旧格式任务");
    expect(item.status).toBe("pending");
  });
});

describe("handleTaskStatusUpdated", () => {
  it("returns a task_status_update action", () => {
    const result = handleTaskStatusUpdated({
      task_item_id: "ti-1",
      task_id: "T1",
      old_status: "pending",
      new_status: "completed",
      result_summary: "大纲已创建",
    });

    expect(result).toEqual({
      type: "task_status_update",
      task_item_id: "ti-1",
      task_id: "T1",
      old_status: "pending",
      new_status: "completed",
      result_summary: "大纲已创建",
    });
  });

  it("handles empty data gracefully", () => {
    const result = handleTaskStatusUpdated({});

    expect(result.type).toBe("task_status_update");
    expect(result.task_item_id).toBe("");
    expect(result.new_status).toBe("");
  });
});

describe("handleTodolistReadinessUpdated", () => {
  it("returns a todolist_readiness_update action", () => {
    const result = handleTodolistReadinessUpdated({
      session_id: "sess-1",
      ready_to_execute: true,
    });

    expect(result).toEqual({
      type: "todolist_readiness_update",
      session_id: "sess-1",
      ready_to_execute: true,
    });
  });

  it("defaults ready_to_execute to false when missing", () => {
    const result = handleTodolistReadinessUpdated({ session_id: "sess-1" });

    expect(result.ready_to_execute).toBe(false);
  });

  it("handles empty data gracefully", () => {
    const result = handleTodolistReadinessUpdated({});

    expect(result.type).toBe("todolist_readiness_update");
    expect(result.session_id).toBe("");
    expect(result.ready_to_execute).toBe(false);
  });
});

describe("createTimelineActions", () => {
  it("exposes all handler functions", () => {
    const actions = createTimelineActions();
    expect(typeof actions.handleOutlineEditDiff).toBe("function");
    expect(typeof actions.handleCharacterEditDiff).toBe("function");
    expect(typeof actions.handleTodolistGenerated).toBe("function");
    expect(typeof actions.handleTaskStatusUpdated).toBe("function");
    expect(typeof actions.handleTodolistReadinessUpdated).toBe("function");
  });
});
