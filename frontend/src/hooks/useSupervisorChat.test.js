import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";


let authFetchCalls = [];

vi.mock("../lib/authFetch", () => ({
  authFetch: (url, options = {}) => {
    const { signal, ...request } = options;
    authFetchCalls.push([url, request]);
    return Promise.resolve({
      ok: true,
      status: 200,
      body: {
        getReader: () => ({ read: () => new Promise(() => {}) }),
      },
    });
  },
}));

vi.mock("../lib/runtime-config", () => ({ API_BASE: "/api" }));

vi.mock("../lib/api", () => ({
  sessionApi: {
    getSupervisorMessages: vi.fn(() => Promise.resolve([])),
  },
}));

const {
  applyFinalizeAllRunningSteps,
  buildTimelineFromHistoryMessages,
  useSupervisorChat,
} = await import("./useSupervisorChat.js");


describe("useSupervisorChat", () => {
  beforeEach(() => {
    authFetchCalls = [];
    vi.clearAllMocks();
  });

  it("starts with only the active chat state", () => {
    const { result } = renderHook(() => useSupervisorChat({ workId: "w1" }));

    expect(result.current.timeline).toEqual([]);
    expect(result.current.input).toBe("");
    expect(result.current.running).toBe(false);
    expect(result.current.sessionId).toBeNull();
    expect(result.current.assistantDraft).toBe("");
    expect(result.current.assistantReasoningDraft).toBe("");
  });

  it("sends only fields supported by the current supervisor API", () => {
    const { result } = renderHook(() => useSupervisorChat({ workId: "w1" }));

    act(() => {
      result.current.setInput("创建大纲");
    });
    act(() => {
      result.current.handleSend();
    });

    const [url, request] = authFetchCalls[0];
    expect(url).toBe("/api/supervisor/start");
    expect(JSON.parse(request.body)).toEqual({
      message: "创建大纲",
      work_id: "w1",
    });
  });

  it("inserts the stored user actions message before the optimistic user message", () => {
    const { result } = renderHook(() => useSupervisorChat({ workId: "w1" }));

    act(() => {
      result.current.setInput("继续写作");
    });
    act(() => {
      result.current.handleSend();
    });
    act(() => {
      result.current._testOnSSE("user_actions_message_stored", {
        id: "actions-1",
        content: "我执行了以下操作：\n- 我修改了「第一章」节点。",
        meta: { type: "user_canvas_actions" },
      });
      result.current._testOnSSE("user_message_stored", {
        message_id: "message-1",
      });
    });

    expect(result.current.timeline).toHaveLength(2);
    expect(result.current.timeline[0]).toMatchObject({
      role: "user",
      type: "user_canvas_actions",
      dbMessageId: "actions-1",
    });
    expect(result.current.timeline[1]).toMatchObject({
      role: "user",
      content: "继续写作",
      dbMessageId: "message-1",
    });
  });

  it("tracks registered tool execution", () => {
    const { result } = renderHook(() => useSupervisorChat({ workId: "w1" }));

    act(() => {
      result.current._testOnSSE("tool_calls", { tools: ["update_node"] });
      result.current._testOnSSE("tool_executed", {
        tool: "update_node",
        success: true,
      });
    });

    expect(result.current.timeline).toHaveLength(1);
    expect(result.current.timeline[0]).toMatchObject({
      kind: "step",
      label: "工具调用 · update_node",
      status: "done",
    });
  });

  it("does not duplicate a tool step for its stage event", () => {
    const { result } = renderHook(() => useSupervisorChat({ workId: "w1" }));

    act(() => {
      result.current._testOnSSE("tool_calls", { tools: ["update_node"] });
      result.current._testOnSSE("stage_start", {
        stage: "tool_calling",
        label: "调用工具: update_node",
      });
    });

    expect(result.current.timeline).toHaveLength(1);
    expect(result.current.timeline[0].label).toBe("工具调用 · update_node");
  });

  it("groups one model tool-call batch into a single running step", () => {
    const { result } = renderHook(() => useSupervisorChat({ workId: "w1" }));

    act(() => {
      result.current._testOnSSE("stage_start", { stage: "thinking", label: "AI 思考中" });
      result.current._testOnSSE("tool_calls", {
        tools: [
          { id: "call-1", name: "update_node" },
          { id: "call-2", name: "update_edge" },
        ],
      });
    });

    const steps = result.current.timeline.filter((item) => item.kind === "step");
    expect(steps).toHaveLength(2);
    expect(steps[0].status).toBe("done");
    expect(steps[1]).toMatchObject({
      label: "工具调用 · update_node, update_edge",
      status: "running",
    });
  });

  it("matches repeated tool names by tool-call ID", () => {
    const { result } = renderHook(() => useSupervisorChat({ workId: "w1" }));

    act(() => {
      result.current._testOnSSE("tool_calls", {
        tools: [
          { id: "call-1", name: "update_node" },
          { id: "call-2", name: "update_node" },
        ],
      });
      result.current._testOnSSE("tool_executed", {
        tool: "update_node", tool_call_id: "call-2", success: true,
      });
    });
    expect(result.current.timeline[0].status).toBe("running");

    act(() => {
      result.current._testOnSSE("tool_executed", {
        tool: "update_node", tool_call_id: "call-1", success: true,
      });
    });
    expect(result.current.timeline[0].status).toBe("done");
  });

  it("collects reasoning and content streams into the final message", () => {
    const { result } = renderHook(() => useSupervisorChat({ workId: "w1" }));

    act(() => {
      result.current._testOnSSE("supervisor_stream", {
        phase: "reasoning",
        chunk: "分析",
      });
      result.current._testOnSSE("supervisor_stream", {
        phase: "content",
        chunk: "完成",
      });
    });
    expect(result.current.assistantReasoningDraft).toBe("分析");
    expect(result.current.assistantDraft).toBe("完成");

    act(() => {
      result.current._testOnSSE("supervisor_done", {});
    });

    expect(result.current.running).toBe(false);
    expect(result.current.timeline.at(-1)).toMatchObject({
      role: "assistant",
      content: "完成",
      reasoningContent: "分析",
    });
  });

  it("handles chapter edit diffs and node refresh events", () => {
    const onChapterUpdated = vi.fn();
    const onNodesUpdate = vi.fn();
    const { result } = renderHook(() =>
      useSupervisorChat({
        workId: "w1",
        callbacks: { onChapterUpdated, onNodesUpdate },
      }),
    );

    act(() => {
      result.current._testOnSSE("chapter_edit_diff", {
        chapter_node_id: "chapter-1",
        title: "第一章",
        diff: { hunks: [{ type: "replace" }], summary: { modified: 1 } },
        word_count: 1200,
        word_count_delta: 10,
      });
      result.current._testOnSSE("nodes_updated", {});
    });

    expect(result.current.timeline.at(-1)).toMatchObject({
      type: "chapter_content_diff_card",
      chapterContentDiffCard: {
        chapter_node_id: "chapter-1",
        title: "第一章",
        word_count: 1200,
      },
    });
    expect(onChapterUpdated).toHaveBeenCalledWith("chapter-1");
    expect(onNodesUpdate).toHaveBeenCalledOnce();
  });

  it("applies current todolist events", () => {
    const { result } = renderHook(() => useSupervisorChat({ workId: "w1" }));

    act(() => {
      result.current._testOnSSE("todolist_generated", {
        todolist: [{ db_id: "db-1", task_id: "T1", task: "写大纲" }],
        ready_to_execute: true,
      });
      result.current._testOnSSE("task_status_updated", {
        task_item_id: "db-1",
        new_status: "completed",
      });
      result.current._testOnSSE("todolist_task_added", {
        db_id: "db-2",
        task_id: "T2",
        task_description: "写正文",
      });
      result.current._testOnSSE("todolist_task_edited", {
        db_id: "db-2",
        task_description: "修改正文",
      });
    });

    const card = result.current.timeline[0].todoCard;
    expect(card.todolist).toHaveLength(2);
    expect(card.todolist[0].status).toBe("completed");
    expect(card.todolist[1].task).toBe("修改正文");

    act(() => {
      result.current._testOnSSE("todolist_task_deleted", { db_id: "db-2" });
    });
    expect(result.current.timeline[0].todoCard.todolist).toHaveLength(1);
  });

  it("rebuilds tool calls and current cards from history", () => {
    const idRef = { current: 0 };
    const timeline = buildTimelineFromHistoryMessages([
      { role: "user", content: "修改第一章", id: "m1" },
      {
        role: "tool_call",
        content: "update_node",
        meta: { success: true },
      },
      {
        role: "assistant",
        content: "",
        meta: {
          type: "chapter_content_diff_card",
          chapterContentDiffCard: { chapter_node_id: "chapter-1" },
        },
      },
    ], idRef);

    expect(timeline.map((item) => item.kind)).toEqual([
      "message",
      "step",
      "message",
    ]);
    expect(timeline[1]).toMatchObject({
      label: "工具调用 · update_node",
      status: "done",
    });
    expect(timeline[2].chapterContentDiffCard.chapter_node_id).toBe("chapter-1");
  });

  it("skips assistant bubbles whose content is only ellipsis placeholder", () => {
    const idRef = { current: 0 };
    const timeline = buildTimelineFromHistoryMessages([
      { role: "user", content: "继续", id: "m1" },
      { role: "assistant", content: "...", meta: { phase: "intermediate" }, id: "m2" },
      { role: "assistant", content: " … ", meta: { phase: "intermediate" }, id: "m3" },
      {
        role: "tool_call",
        content: "delete_node",
        meta: { success: true },
      },
      { role: "assistant", content: "已完成删除", meta: { phase: "final" }, id: "m4" },
      {
        role: "assistant",
        content: "...",
        meta: {
          type: "requirements_todolist",
          todoCard: { intent_summary: "x", todolist: [], ready_to_execute: true },
        },
        id: "m5",
      },
      {
        role: "assistant",
        content: "...",
        meta: { reasoning_content: "先删节点再总结" },
        id: "m6",
      },
    ], idRef);

    const assistantTexts = timeline
      .filter((item) => item.kind === "message" && item.role === "assistant")
      .map((item) => ({
        content: item.content,
        type: item.type,
        reasoning: item.reasoningContent || "",
      }));

    expect(assistantTexts).toEqual([
      { content: "已完成删除", type: undefined, reasoning: "" },
      {
        content: "",
        type: "requirements_todolist",
        reasoning: "",
      },
      { content: "...", type: undefined, reasoning: "先删节点再总结" },
    ]);
    expect(timeline.some((item) => item.kind === "step")).toBe(true);
  });

  it("does not freeze a streaming draft that is only ellipsis", () => {
    const { result } = renderHook(() => useSupervisorChat({ workId: "w1" }));

    act(() => {
      result.current._testOnSSE("supervisor_stream", {
        chunk: "...",
        phase: "content",
      });
      result.current._testOnSSE("supervisor_done", {});
    });

    expect(result.current.assistantDraft).toBe("");
    expect(
      result.current.timeline.filter(
        (item) => item.kind === "message" && item.role === "assistant",
      ),
    ).toEqual([]);
  });
});


describe("applyFinalizeAllRunningSteps", () => {
  it("finishes all running steps", () => {
    expect(applyFinalizeAllRunningSteps([
      { kind: "step", id: 1, status: "running" },
      { kind: "message", id: 2, role: "user" },
    ])).toEqual([
      { kind: "step", id: 1, status: "done", panelOpen: false },
      { kind: "message", id: 2, role: "user" },
    ]);
  });
});
