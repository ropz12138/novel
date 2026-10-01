import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";


let authFetchCalls = [];
let streamChunks = null;
let enqueueStartsStream = false;

vi.mock("../lib/authFetch", () => ({
  authFetch: (url, options = {}) => {
    const { signal, ...request } = options;
    authFetchCalls.push([url, request]);
    const chunks = streamChunks;
    let index = 0;
    return Promise.resolve({
      ok: true,
      status: 200,
      json: async () => ({ running: true, pending_messages: [], started_new_stream: enqueueStartsStream }),
      body: {
        getReader: () => ({ read: () => chunks
          ? Promise.resolve(index < chunks.length
            ? { done: false, value: new TextEncoder().encode(chunks[index++]) }
            : { done: true })
          : new Promise(() => {}) }),
      },
    });
  },
}));

vi.mock("../lib/runtime-config", () => ({ API_BASE: "/api" }));

vi.mock("../lib/api", () => ({
    sessionApi: {
      getSupervisor: vi.fn(),
      getSupervisorMessages: vi.fn(() => Promise.resolve({ messages: [], has_more: false })),
      getSupervisorDiffDetail: vi.fn(),
      stopSupervisor: vi.fn(() => Promise.resolve({ success: true, stopped: true })),
    },
}));

const {
  applyFinalizeAllRunningSteps,
  buildTimelineFromHistoryMessages,
  useSupervisorChat,
} = await import("./useSupervisorChat.js");
const { sessionApi } = await import("../lib/api");


describe("useSupervisorChat", () => {
  it("submits while running and displays only the backend queue", async () => {
    const { result } = renderHook(() => useSupervisorChat({ workId: "w1" }));
    act(() => {
      result.current._testOnSSE("session_created", { session_id: "s1" });
      result.current.setRunning(true);
    });
    await act(async () => { result.current.handleSend("继续", "high"); });
    expect(authFetchCalls[0][0]).toBe("/api/supervisor/enqueue");
    expect(JSON.parse(authFetchCalls[0][1].body)).toMatchObject({ session_id: "s1", message: "继续" });
    expect(result.current.timeline.filter((item) => item.role === "user")).toHaveLength(0);
    act(() => result.current._testOnSSE("queue_updated", {
      running: true, pending_messages: [{ id: "q1", content: "继续" }],
    }));
    expect(result.current.pendingMessages).toEqual([{ id: "q1", content: "继续" }]);
    act(() => {
      result.current._testOnSSE("supervisor_turn_done", { message: "上一条完成" });
      result.current._testOnSSE("queued_message_started", { message_id: "m2", content: "继续" });
    });
    expect(result.current.running).toBe(true);
    expect(result.current.timeline.at(-1)).toMatchObject({ role: "user", content: "继续", dbMessageId: "m2" });
  });

  beforeEach(() => {
    enqueueStartsStream = false;
    authFetchCalls = [];
    streamChunks = null;
    vi.clearAllMocks();
    sessionApi.getSupervisorMessages.mockResolvedValue({ messages: [], has_more: false });
  });

  it("shows the fixed public copy for an LLM error without an extra prefix", () => {
    const { result } = renderHook(() => useSupervisorChat({ workId: "w1" }));
    act(() => {
      result.current._testOnSSE("error", { message: "AI额度不足，请稍后再试" });
    });
    expect(result.current.timeline.at(-1)).toMatchObject({
      role: "system",
      content: "AI额度不足，请稍后再试",
      type: "error",
    });
  });

  it("subscribes to a new backend run even if the local running state is stale", async () => {
    enqueueStartsStream = true;
    const { result } = renderHook(() => useSupervisorChat({ workId: "w1" }));
    act(() => {
      result.current._testOnSSE("session_created", { session_id: "s1" });
      result.current.setRunning(true);
    });
    await act(async () => { result.current.handleSend("继续"); });
    expect(authFetchCalls.map(([url]) => url)).toEqual([
      "/api/supervisor/enqueue", "/api/supervisor/stream",
    ]);
  });

  it("keeps the run active after SSE disconnect and reloads persisted messages when the backend completes", async () => {
    const onNodesUpdate = vi.fn();
    streamChunks = ["event: session_created\ndata: {\"session_id\":\"session-1\"}\n\n"];
    sessionApi.getSupervisor
      .mockResolvedValueOnce({ id: "session-1", status: "running" })
      .mockResolvedValueOnce({ id: "session-1", status: "completed" });
    sessionApi.getSupervisorMessages.mockResolvedValueOnce({
      messages: [
        { id: "m1", role: "user", content: "继续写", sort_order: 0 },
        { id: "m2", role: "assistant", content: "已经完成", sort_order: 1 },
      ],
      has_more: false,
    });
    const { result } = renderHook(() => useSupervisorChat({
      workId: "w1",
      disconnectPollIntervalMs: 0,
      callbacks: { onNodesUpdate },
    }));

    act(() => result.current.handleSend("继续写"));

    await waitFor(() => {
      expect(result.current.running).toBe(false);
      expect(result.current.timeline.at(-1)).toMatchObject({
        role: "assistant",
        content: "已经完成",
      });
    });
    expect(result.current.timeline.some((item) => item.type === "error")).toBe(false);
    expect(sessionApi.getSupervisor).toHaveBeenCalledTimes(2);
    expect(onNodesUpdate).toHaveBeenCalledOnce();
    const resumeRequest = authFetchCalls.find(([url]) => url === "/api/supervisor/stream");
    expect(JSON.parse(resumeRequest[1].body)).toEqual({
      session_id: "session-1",
    });
  });

  it("does not reconnect after a normal stream that already received supervisor_done", async () => {
    streamChunks = [
      "event: session_created\ndata: {\"session_id\":\"session-1\"}\n\n",
      "event: supervisor_stream\ndata: {\"phase\":\"content\",\"chunk\":\"已经完成\"}\n\n",
      "event: supervisor_done\ndata: {\"message\":\"已经完成\"}",
    ];
    const { result } = renderHook(() => useSupervisorChat({
      workId: "w1",
      disconnectPollIntervalMs: 0,
    }));

    act(() => result.current.handleSend("继续写"));

    await waitFor(() => expect(result.current.running).toBe(false));
    expect(sessionApi.getSupervisor).not.toHaveBeenCalled();
    expect(result.current.timeline.some(
      (item) => item.kind === "step" && item.label === "重连中...",
    )).toBe(false);
    expect(result.current.assistantDraft).toBe("");
    expect(result.current.timeline.filter(
      (item) => item.kind === "message" && item.role === "assistant",
    )).toHaveLength(1);
    expect(result.current.timeline.at(-1)).toMatchObject({
      role: "assistant",
      content: "已经完成",
    });
  });

  it("reloads the finished session without reconnecting copy when the stream ends before supervisor_done", async () => {
    streamChunks = [
      "event: session_created\ndata: {\"session_id\":\"session-1\"}\n\n",
      "event: supervisor_stream\ndata: {\"phase\":\"content\",\"chunk\":\"已经完成\"}\n\n",
    ];
    sessionApi.getSupervisor.mockResolvedValue({ id: "session-1", status: "completed" });
    sessionApi.getSupervisorMessages.mockResolvedValue({
      messages: [
        { id: "m1", role: "user", content: "继续写", sort_order: 0 },
        { id: "m2", role: "assistant", content: "已经完成", sort_order: 1 },
      ],
      has_more: false,
    });
    const { result } = renderHook(() => useSupervisorChat({
      workId: "w1",
      disconnectPollIntervalMs: 0,
    }));

    act(() => result.current.handleSend("继续写"));

    await waitFor(() => expect(result.current.running).toBe(false));
    expect(result.current.timeline.some(
      (item) => item.kind === "step" && item.label === "重连中...",
    )).toBe(false);
    expect(result.current.assistantDraft).toBe("");
    expect(result.current.timeline.filter(
      (item) => item.kind === "message" && item.role === "assistant" && item.content === "已经完成",
    )).toHaveLength(1);
  });

  it("shows reconnecting copy after SSE disconnect while the backend is still running", async () => {
    streamChunks = ["event: session_created\ndata: {\"session_id\":\"session-1\"}\n\n"];
    sessionApi.getSupervisor.mockResolvedValue({ id: "session-1", status: "running" });
    const { result } = renderHook(() => useSupervisorChat({
      workId: "w1",
      disconnectPollIntervalMs: 0,
    }));

    act(() => result.current.handleSend("继续写"));

    await waitFor(() => {
      expect(result.current.timeline.some(
        (item) => item.kind === "step" && item.label === "重连中...",
      )).toBe(true);
    });
    expect(result.current.timeline.some(
      (item) => item.kind === "step" && String(item.label).includes("连接已断开"),
    )).toBe(false);
  });

  it("shows an interruption bubble only when the backend marks the session interrupted", async () => {
    streamChunks = ["event: session_created\ndata: {\"session_id\":\"session-1\"}\n\n"];
    sessionApi.getSupervisor.mockResolvedValueOnce({ id: "session-1", status: "interrupted" });
    const { result } = renderHook(() => useSupervisorChat({
      workId: "w1",
      disconnectPollIntervalMs: 0,
    }));

    act(() => result.current.handleSend("继续写"));

    await waitFor(() => expect(result.current.running).toBe(false));
    expect(result.current.timeline.at(-1)).toMatchObject({
      type: "error",
      content: "Agent 执行已中断",
    });
  });

  it("discards in-progress stream text when the backend interrupts the run", async () => {
    sessionApi.getSupervisorMessages.mockResolvedValue({
      messages: [
        { id: "m1", role: "user", content: "继续写", sort_order: 0 },
      ],
      has_more: false,
    });
    const { result } = renderHook(() => useSupervisorChat({ workId: "w1" }));

    act(() => {
      result.current.handleSend("继续写");
      result.current._testOnSSE("session_created", { session_id: "session-1" });
      result.current.setAssistantDraft("正在拼很长的工具参数");
      result.current._testOnSSE("supervisor_interrupted", { reason: "cancelled" });
    });

    await waitFor(() => expect(result.current.running).toBe(false));
    expect(result.current.assistantDraft).toBe("");
    expect(result.current.timeline.some((item) => String(item.content || "").includes("正在拼很长"))).toBe(false);
    await waitFor(() => {
      expect(result.current.timeline.some((item) => item.type === "interrupted")).toBe(true);
    });
  });

  it("handleStop asks the backend to cancel the running session", async () => {
    const { result } = renderHook(() => useSupervisorChat({ workId: "w1" }));

    act(() => {
      result.current.handleSend("继续写");
      result.current._testOnSSE("session_created", { session_id: "session-1" });
    });
    await waitFor(() => expect(result.current.running).toBe(true));

    await act(async () => {
      await result.current.handleStop();
    });

    expect(sessionApi.stopSupervisor).toHaveBeenCalledWith("session-1");
  });

  it("resumes status recovery when the app reopens a session that is still running", async () => {
    const onNodesUpdate = vi.fn();
    sessionApi.getSupervisor.mockResolvedValueOnce({ id: "session-1", status: "completed" });
    sessionApi.getSupervisorMessages
      .mockResolvedValueOnce({
        messages: [{ id: "m1", role: "user", content: "继续写", sort_order: 0 }],
        has_more: false,
      })
      .mockResolvedValueOnce({
        messages: [
          { id: "m1", role: "user", content: "继续写", sort_order: 0 },
          { id: "m2", role: "assistant", content: "后台完成的回复", sort_order: 1 },
        ],
        has_more: false,
      });
    const { result } = renderHook(() => useSupervisorChat({
      workId: "w1",
      disconnectPollIntervalMs: 0,
      callbacks: { onNodesUpdate },
    }));

    await act(async () => {
      await result.current.handleSelectSession({ id: "session-1", status: "running" });
    });

    await waitFor(() => {
      expect(result.current.running).toBe(false);
      expect(result.current.timeline.at(-1)?.content).toBe("后台完成的回复");
    });
    expect(result.current.timeline.some((item) => item.type === "error")).toBe(false);
    expect(onNodesUpdate).toHaveBeenCalledOnce();
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
      chapter_review_intensity: "medium",
    });
  });

  it("sends the selected chapter review intensity", () => {
    const { result } = renderHook(() => useSupervisorChat({ workId: "w1" }));
    act(() => result.current.handleSend("写第一章", "high"));
    expect(JSON.parse(authFetchCalls[0][1].body).chapter_review_intensity).toBe("high");
  });

  it("keeps the selected intensity when resuming a session", () => {
    const { result } = renderHook(() => useSupervisorChat({ workId: "w1" }));
    act(() => result.current._testOnSSE("session_created", { session_id: "session-1" }));
    act(() => result.current.handleSend("继续写", "medium"));
    expect(authFetchCalls[0][0]).toBe("/api/supervisor/enqueue");
    expect(JSON.parse(authFetchCalls[0][1].body).chapter_review_intensity).toBe("medium");
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

  it("does not duplicate the final reply after a thinking retry stage", () => {
    const { result } = renderHook(() => useSupervisorChat({ workId: "w1" }));

    act(() => {
      result.current._testOnSSE("supervisor_stream", {
        phase: "content",
        chunk: "我先更新角色卡。",
      });
      result.current._testOnSSE("stage_start", {
        stage: "thinking",
        label: "继续执行",
      });
    });

    expect(result.current.assistantDraft).toBe("");
    expect(result.current.timeline.at(-1)).toMatchObject({
      kind: "step",
      label: "继续执行",
      status: "running",
    });

    act(() => {
      result.current._testOnSSE("supervisor_stream", {
        phase: "content",
        chunk: "角色卡已更新，在侧栏查看。",
      });
    });

    expect(result.current.assistantDraft).toBe("角色卡已更新，在侧栏查看。");
    expect(result.current.timeline.at(-1)).toMatchObject({
      kind: "step",
      label: "继续执行",
      status: "done",
    });

    act(() => {
      result.current._testOnSSE("supervisor_done", {
        message: "角色卡已更新，在侧栏查看。",
      });
    });

    const assistantMsgs = result.current.timeline.filter(
      (item) => item.kind === "message" && item.role === "assistant",
    );
    expect(assistantMsgs).toHaveLength(1);
    expect(assistantMsgs[0].content).toBe("角色卡已更新，在侧栏查看。");
    expect(result.current.assistantDraft).toBe("");
  });

  it("uses supervisor_done.message as the visible reply when content never streamed", () => {
    const { result } = renderHook(() => useSupervisorChat({ workId: "w1" }));

    act(() => {
      result.current._testOnSSE("supervisor_stream", {
        phase: "reasoning",
        chunk: "准备回复",
      });
      result.current._testOnSSE("tool_calls", { tools: ["respond_to_user"] });
    });

    expect(result.current.assistantReasoningDraft).toBe("准备回复");
    expect(result.current.timeline.filter((item) => item.kind === "step")).toHaveLength(0);

    act(() => {
      result.current._testOnSSE("supervisor_done", {
        message: "章节连续性正常，框架基本符合。",
      });
    });

    expect(result.current.running).toBe(false);
    expect(result.current.assistantDraft).toBe("");
    expect(result.current.timeline.at(-1)).toMatchObject({
      role: "assistant",
      content: "章节连续性正常，框架基本符合。",
      reasoningContent: "准备回复",
    });
  });

  it("still tracks work tools when respond_to_user is mixed in the same batch", () => {
    const { result } = renderHook(() => useSupervisorChat({ workId: "w1" }));

    act(() => {
      result.current._testOnSSE("tool_calls", {
        tools: [
          { id: "call-1", name: "update_node" },
          { id: "call-2", name: "respond_to_user" },
        ],
      });
    });

    expect(result.current.timeline).toHaveLength(1);
    expect(result.current.timeline[0]).toMatchObject({
      label: "工具调用 · update_node",
      status: "running",
    });
  });

  it("handles chapter edit diffs and node refresh events", () => {
    const onChapterUpdated = vi.fn();
    const onNodesUpdate = vi.fn();
    const onNodeContentDiff = vi.fn();
    const { result } = renderHook(() =>
      useSupervisorChat({
        workId: "w1",
        callbacks: { onChapterUpdated, onNodesUpdate, onNodeContentDiff },
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
    expect(onNodeContentDiff).toHaveBeenCalledWith("chapter-1", expect.objectContaining({
      title: "第一章",
      hunks: [{ type: "replace" }],
    }));
  });

  it("shows a streamed diff immediately when event and data arrive in separate reads", async () => {
    streamChunks = [
      "event: chapter_edit_diff\n",
      'data: {"chapter_node_id":"chapter-live","node_type":"chapter","title":"第一章","baseline_content":"更早的正文","original_content":"旧文","current_content":"新文","diff":{"hunks":[{"type":"replace","paragraph_index":1,"old_text":"旧文","new_text":"新文"}]}}\n\n',
    ];
    const onNodeContentDiff = vi.fn();
    const { result } = renderHook(() => useSupervisorChat({
      workId: "w1", callbacks: { onNodeContentDiff },
    }));
    act(() => result.current.handleSend("修改第一章"));

    await waitFor(() => expect(result.current.timeline).toEqual(expect.arrayContaining([
      expect.objectContaining({ type: "chapter_content_diff_card" }),
    ])));
    expect(onNodeContentDiff).toHaveBeenCalledWith("chapter-live", expect.objectContaining({
      baseline_content: "更早的正文", original_content: "旧文", current_content: "新文",
    }));
  });

  it("streams a read-only node content diff preview", () => {
    const onNodeContentDiff = vi.fn();
    const { result } = renderHook(() => useSupervisorChat({
      workId: "w1",
      callbacks: { onNodeContentDiff },
    }));

    act(() => {
      result.current._testOnSSE("node_content_diff_preview", {
        phase: "start",
        node_id: "chapter-1",
        node_type: "chapter",
        title: "第一章",
        original_content: "旧文",
      });
      result.current._testOnSSE("node_content_diff_preview", {
        phase: "delta",
        node_id: "chapter-1",
        chunk: "新文",
      });
    });

    expect(onNodeContentDiff).toHaveBeenLastCalledWith("chapter-1", expect.objectContaining({
      preview: true,
      original_content: "旧文",
      current_content: "新文",
      hunks: [expect.objectContaining({ type: "replace", old_text: "旧文", new_text: "新文" })],
    }));
    expect(result.current.timeline).toEqual([]);
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

  it("removes the edited message and abandoned todo branch immediately", () => {
    const { result } = renderHook(() => useSupervisorChat({ workId: "w1" }));

    act(() => {
      result.current.addMessage("user", "保留消息", { dbMessageId: "m1" });
      result.current.addMessage("user", "待编辑消息", { dbMessageId: "m2" });
      result.current._testOnSSE("todolist_generated", {
        todolist: [{ db_id: "old-todo", task_id: "T1", task: "废弃任务" }],
      });
      result.current._testOnSSE("messages_truncated", { from_message_id: "m2" });
    });

    expect(result.current.timeline).toHaveLength(1);
    expect(result.current.timeline[0]).toMatchObject({ dbMessageId: "m1" });
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

  it("does not rebuild respond_to_user as a visible tool step", () => {
    const idRef = { current: 0 };
    const timeline = buildTimelineFromHistoryMessages([
      { role: "user", content: "看一下连续性", id: "m1" },
      {
        role: "tool_call",
        content: "respond_to_user",
        meta: { success: true },
      },
      { role: "assistant", content: "连续正常", id: "m2" },
    ], idRef);

    expect(timeline.map((item) => item.kind)).toEqual(["message", "message"]);
    expect(timeline[1]).toMatchObject({
      role: "assistant",
      content: "连续正常",
    });
  });

  it("does not replay node body diffs when loading a persisted conversation", async () => {
    const onNodeContentDiff = vi.fn();
    const onNodeContentDiffsReset = vi.fn();
    sessionApi.getSupervisorMessages.mockResolvedValueOnce({
      messages: [{
        role: "assistant",
        content: "",
        id: "diff-message-1",
        sort_order: 0,
        meta: {
          type: "chapter_content_diff_card",
          chapterContentDiffCard: {
            node_id: "plot-1",
            node_type: "plot",
            title: "废墟相遇",
            summary: { paragraphs_changed: 1 },
          },
        },
      }],
      has_more: false,
    });
    const { result } = renderHook(() => useSupervisorChat({
      workId: "w1",
      callbacks: { onNodeContentDiff, onNodeContentDiffsReset },
    }));

    await act(async () => {
      await result.current.handleSelectSession({ id: "session-1" });
    });

    expect(onNodeContentDiffsReset).toHaveBeenCalledOnce();
    expect(onNodeContentDiff).not.toHaveBeenCalled();
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

  it("loads the tail page first and prepends the earlier page", async () => {
    sessionApi.getSupervisorMessages
      .mockResolvedValueOnce({
        messages: [{ id: "m3", role: "user", content: "后一句", sort_order: 2 }],
        has_more: true,
      })
      .mockResolvedValueOnce({
        messages: [{ id: "m1", role: "user", content: "前一句", sort_order: 0 }],
        has_more: false,
      });
    const { result } = renderHook(() => useSupervisorChat({ workId: "w1" }));

    await act(async () => {
      await result.current.handleSelectSession({ id: "session-1" });
    });

    expect(result.current.hasMoreHistory).toBe(true);
    expect(result.current.timeline.map((item) => item.content)).toEqual(["后一句"]);

    await act(async () => {
      await result.current.loadOlderMessages();
    });

    expect(sessionApi.getSupervisorMessages).toHaveBeenLastCalledWith("session-1", {
      beforeSortOrder: 2,
    });
    expect(result.current.timeline.map((item) => item.content)).toEqual(["前一句", "后一句"]);
    expect(result.current.hasMoreHistory).toBe(false);
  });

  it("fetches diff hunks when a summary card is expanded", async () => {
    sessionApi.getSupervisorMessages.mockResolvedValueOnce({
      messages: [{
        id: "diff-1",
        role: "assistant",
        content: "",
        sort_order: 0,
        meta: {
          type: "chapter_content_diff_card",
          chapterContentDiffCard: { title: "第一章", node_type: "chapter" },
        },
      }],
      has_more: false,
    });
    sessionApi.getSupervisorDiffDetail.mockResolvedValue({
      hunks: [{ type: "replace", old_text: "旧", new_text: "新" }],
    });
    const { result } = renderHook(() => useSupervisorChat({ workId: "w1" }));

    await act(async () => {
      await result.current.handleSelectSession({ id: "session-1" });
    });
    await act(async () => {
      await result.current.expandDiffDetail("diff-1");
    });

    expect(sessionApi.getSupervisorDiffDetail).toHaveBeenCalledWith("session-1", "diff-1");
    expect(result.current.timeline[0].chapterContentDiffCard.hunks).toEqual([
      { type: "replace", old_text: "旧", new_text: "新" },
    ]);
    expect(result.current.timeline[0].diffDetailOpen).toBe(true);
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
