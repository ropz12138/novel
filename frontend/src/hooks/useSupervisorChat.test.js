import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

// ── Mocks ──

let mockAuthFetchResponse = null;
let mockAuthFetchError = null;
let mockAuthFetchCalls = [];

vi.mock("../lib/authFetch", () => ({
  authFetch: (url, opts) => {
    // Strip signal to avoid jsdom AbortController issues
    const { signal, ...rest } = opts || {};
    mockAuthFetchCalls.push([url, rest]);
    if (mockAuthFetchError) return Promise.reject(mockAuthFetchError);
    if (mockAuthFetchResponse) return Promise.resolve(mockAuthFetchResponse());
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
  },
}));

vi.mock("../lib/runtime-config", () => ({
  API_BASE: "/api",
}));

vi.mock("../lib/api", () => ({
  sessionApi: {
    listSupervisor: vi.fn(() => Promise.resolve([])),
    getSupervisorMessages: vi.fn(() => Promise.resolve([])),
    deleteSupervisor: vi.fn(() => Promise.resolve()),
  },
}));

// ── Import after mocks ──

const { useSupervisorChat } = await import("./useSupervisorChat.js");

// ── Helper: simulate SSE events via onSSE directly ──

function simulateSSE(result, events) {
  act(() => {
    for (const { event, data } of events) {
      result.current._testOnSSE(event, data);
    }
  });
}

// ── Tests ──

describe("useSupervisorChat", () => {
  beforeEach(() => {
    mockAuthFetchResponse = null;
    mockAuthFetchError = null;
    mockAuthFetchCalls = [];
    vi.clearAllMocks();
  });

  // ── Initial state ──

  describe("initial state", () => {
    it("returns correct default state", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      expect(result.current.timeline).toEqual([]);
      expect(result.current.input).toBe("");
      expect(result.current.running).toBe(false);
      expect(result.current.sessionId).toBe(null);
      expect(result.current.assistantDraft).toBe("");
      expect(result.current.editDiff).toBe(null);
      expect(result.current.outlineDiff).toBe(null);
      expect(result.current.characterDiff).toBe(null);
      expect(result.current.confirming).toBe(false);
    });
  });

  // ── Timeline management ──

  describe("addMessage", () => {
    it("appends a user message to timeline", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current.addMessage("user", "hello");
      });

      expect(result.current.timeline).toHaveLength(1);
      const msg = result.current.timeline[0];
      expect(msg.kind).toBe("message");
      expect(msg.role).toBe("user");
      expect(msg.content).toBe("hello");
    });

    it("appends a message with extra meta", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current.addMessage("assistant", "", { type: "outline_created", workId: "w1" });
      });

      const msg = result.current.timeline[0];
      expect(msg.type).toBe("outline_created");
      expect(msg.workId).toBe("w1");
    });
  });

  describe("pushExecStep / finalizeLastRunningStep", () => {
    it("adds a running step and then finalizes it", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current.pushExecStep("thinking");
      });

      expect(result.current.timeline).toHaveLength(1);
      expect(result.current.timeline[0].status).toBe("running");
      expect(result.current.timeline[0].label).toBe("thinking");

      act(() => {
        result.current.finalizeLastRunningStep();
      });

      expect(result.current.timeline[0].status).toBe("done");
    });
  });

  describe("pushExecStepDone", () => {
    it("finalizes running steps and appends a done step", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current.pushExecStep("generating");
        result.current.pushExecStepDone("generation complete");
      });

      expect(result.current.timeline).toHaveLength(2);
      expect(result.current.timeline[0].status).toBe("done");
      expect(result.current.timeline[1].status).toBe("done");
      expect(result.current.timeline[1].label).toBe("generation complete");
    });
  });

  describe("appendLastRunningStream", () => {
    it("appends text to the last running step", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current.pushExecStep("writing");
      });

      act(() => {
        result.current.appendLastRunningStream("hello ");
        result.current.appendLastRunningStream("world");
      });

      expect(result.current.timeline[0].stream).toBe("hello world");
    });

    it("creates a new running step if none exists", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current.appendLastRunningStream("orphan text");
      });

      expect(result.current.timeline).toHaveLength(1);
      expect(result.current.timeline[0].status).toBe("running");
      expect(result.current.timeline[0].stream).toBe("orphan text");
    });
  });

  describe("freezeDraft", () => {
    it("freezes assistantDraft into a timeline message via supervisor_stream + tool_calls", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("supervisor_stream", { chunk: "partial response" });
      });
      expect(result.current.assistantDraft).toBe("partial response");

      // tool_calls triggers freezeDraft
      act(() => {
        result.current._testOnSSE("tool_calls", { tools: ["read_outline"] });
      });

      expect(result.current.assistantDraft).toBe("");
      const frozenMsg = result.current.timeline.find(
        (m) => m.kind === "message" && m.content === "partial response"
      );
      expect(frozenMsg).toBeDefined();
      expect(frozenMsg.role).toBe("assistant");
    });

    it("does nothing if draft is empty", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current.freezeDraft();
      });

      expect(result.current.timeline).toHaveLength(0);
    });
  });

  describe("toggleStepPanel", () => {
    it("toggles panelOpen on a step", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current.pushExecStep("step1", { panelOpen: true });
      });

      const stepId = result.current.timeline[0].id;

      act(() => {
        result.current.toggleStepPanel(stepId);
      });

      expect(result.current.timeline[0].panelOpen).toBe(false);

      act(() => {
        result.current.toggleStepPanel(stepId);
      });

      expect(result.current.timeline[0].panelOpen).toBe(true);
    });
  });

  // ── Input management ──

  describe("setInput", () => {
    it("updates input value", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current.setInput("test input");
      });

      expect(result.current.input).toBe("test input");
    });
  });

  // ── handleSend (non-SSE aspects) ──

  describe("handleSend", () => {
    it("does nothing when running", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current.setRunning(true);
      });

      act(() => {
        result.current.setInput("hello");
        result.current.handleSend();
      });

      expect(result.current.timeline).toHaveLength(0);
    });

    it("does nothing when input is empty", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current.handleSend();
      });

      expect(result.current.timeline).toHaveLength(0);
    });

    it("adds user message to timeline and initiates SSE with correct params", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: true })
      );

      act(() => {
        result.current.setInput("create an outline");
      });

      act(() => {
        result.current.handleSend();
      });

      // User message should be in timeline
      expect(result.current.timeline.some((m) => m.role === "user" && m.content === "create an outline")).toBe(true);
      expect(result.current.input).toBe("");
      expect(result.current.running).toBe(true);

      // Should have called supervisor/start
      expect(mockAuthFetchCalls.length).toBeGreaterThan(0);
      expect(mockAuthFetchCalls[0][0]).toContain("/supervisor/start");
      const body = JSON.parse(mockAuthFetchCalls[0][1].body);
      expect(body.message).toBe("create an outline");
      expect(body.work_id).toBe("w1");
      expect(body.auto_mode).toBe(true);
    });

    it("sends resume when session exists", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      // Simulate session_created
      act(() => {
        result.current._testOnSSE("session_created", { session_id: "s1" });
      });
      expect(result.current.sessionId).toBe("s1");

      mockAuthFetchCalls = [];

      act(() => {
        result.current.setInput("continue");
      });

      // handleSend triggers connectSSE which may fail in jsdom,
      // but we can still verify the correct fetch was attempted
      act(() => {
        result.current.handleSend();
      });

      // Verify the fetch was called with resume endpoint
      expect(mockAuthFetchCalls.length).toBeGreaterThan(0);
      expect(mockAuthFetchCalls[0][0]).toContain("/supervisor/resume");
      const body = JSON.parse(mockAuthFetchCalls[0][1].body);
      expect(body.session_id).toBe("s1");
      expect(body.message).toBe("continue");
    });
  });

  // ── SSE event handling (tested via _testOnSSE) ──

  describe("SSE event: session_created", () => {
    it("sets sessionId", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("session_created", { session_id: "new-session" });
      });

      expect(result.current.sessionId).toBe("new-session");
    });
  });

  describe("SSE event: tool_calls", () => {
    it("adds a done step with tool names and freezes draft", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      // Set up some draft text to verify freezeDraft is called
      act(() => {
        result.current._testOnSSE("supervisor_stream", { chunk: "thinking..." });
      });

      act(() => {
        result.current._testOnSSE("tool_calls", { tools: ["read_outline", "generate_chapter"] });
      });

      // Draft should be frozen
      expect(result.current.assistantDraft).toBe("");

      // Frozen message should be in timeline
      const frozenMsg = result.current.timeline.find(
        (m) => m.kind === "message" && m.content === "thinking..."
      );
      expect(frozenMsg).toBeDefined();

      // Tool step should be in timeline
      const toolStep = result.current.timeline.find(
        (m) => m.kind === "step" && m.label.includes("read_outline")
      );
      expect(toolStep).toBeDefined();
      expect(toolStep.label).toContain("generate_chapter");
      expect(toolStep.status).toBe("done");
    });
  });

  describe("SSE event: supervisor_stream / supervisor_done", () => {
    it("accumulates stream text and finalizes on done", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current.setRunning(true);
        result.current._testOnSSE("supervisor_stream", { chunk: "Hello " });
        result.current._testOnSSE("supervisor_stream", { chunk: "world" });
      });

      expect(result.current.assistantDraft).toBe("Hello world");

      act(() => {
        result.current._testOnSSE("supervisor_done", {});
      });

      // supervisor_done freezes draft and stops running
      expect(result.current.running).toBe(false);
      expect(result.current.assistantDraft).toBe("");

      // Frozen message should be in timeline
      const msg = result.current.timeline.find(
        (m) => m.kind === "message" && m.content === "Hello world"
      );
      expect(msg).toBeDefined();
    });
  });

  describe("SSE event: outline_done", () => {
    it("triggers onWorkCreated callback and adds message", () => {
      const onWorkCreated = vi.fn();

      const { result } = renderHook(() =>
        useSupervisorChat({ workId: null, autoMode: false, callbacks: { onWorkCreated } })
      );

      act(() => {
        result.current._testOnSSE("outline_done", { work_id: "w2", title: "New Novel" });
      });

      expect(onWorkCreated).toHaveBeenCalledWith({ work_id: "w2", title: "New Novel" });

      const msg = result.current.timeline.find(
        (m) => m.type === "outline_created"
      );
      expect(msg).toBeDefined();
      expect(msg.content).toContain("New Novel");
    });
  });

  describe("SSE event: saved", () => {
    it("triggers onChapterUpdated callback and adds message", () => {
      const onChapterUpdated = vi.fn();

      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false, callbacks: { onChapterUpdated } })
      );

      act(() => {
        result.current._testOnSSE("saved", { chapter_number: 3, title: "Chapter 3", word_count: 2000 });
      });

      expect(onChapterUpdated).toHaveBeenCalledWith(3);

      const msg = result.current.timeline.find(
        (m) => m.type === "chapter_saved"
      );
      expect(msg).toBeDefined();
      expect(msg.content).toContain("第3章");
    });
  });

  describe("SSE event: error", () => {
    it("adds error message to timeline and stops running", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current.setRunning(true);
        result.current._testOnSSE("error", { message: "something went wrong" });
      });

      const errMsg = result.current.timeline.find(
        (m) => m.type === "error"
      );
      expect(errMsg).toBeDefined();
      expect(errMsg.content).toContain("something went wrong");
      expect(result.current.running).toBe(false);
    });
  });

  describe("SSE event: stage_start", () => {
    it("adds a running step with label", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("stage_start", { stage: "thinking", label: "分析需求" });
      });

      const step = result.current.timeline.find(
        (m) => m.kind === "step" && m.status === "running"
      );
      expect(step).toBeDefined();
      expect(step.label).toBe("分析需求");
    });

    it("freezes existing assistantDraft before creating a new step", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      // Simulate: first round of LLM output
      act(() => {
        result.current._testOnSSE("stage_start", { stage: "thinking", label: "AI 思考中" });
        result.current._testOnSSE("supervisor_stream", { chunk: "第一轮回复" });
      });
      expect(result.current.assistantDraft).toBe("第一轮回复");

      // Now a new stage_start arrives (e.g. tool_calling or a second thinking round)
      act(() => {
        result.current._testOnSSE("stage_start", { stage: "tool_calling", label: "调用工具" });
      });

      // The previous draft should be frozen into a timeline message
      expect(result.current.assistantDraft).toBe("");
      const frozenMsg = result.current.timeline.find(
        (m) => m.kind === "message" && m.content === "第一轮回复"
      );
      expect(frozenMsg).toBeDefined();
      expect(frozenMsg.role).toBe("assistant");

      // A new running step should exist
      const steps = result.current.timeline.filter(
        (m) => m.kind === "step"
      );
      expect(steps.length).toBeGreaterThanOrEqual(2);
      const lastStep = steps[steps.length - 1];
      expect(lastStep.label).toBe("调用工具");
      expect(lastStep.status).toBe("running");
    });

    it("does not create empty message when freezing empty draft on stage_start", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      // stage_start with no prior draft
      act(() => {
        result.current._testOnSSE("stage_start", { stage: "thinking", label: "AI 思考中" });
      });

      // No frozen message should be created (draft was empty)
      const frozenMsg = result.current.timeline.find(
        (m) => m.kind === "message"
      );
      expect(frozenMsg).toBeUndefined();

      // Step should still be created
      const step = result.current.timeline.find(
        (m) => m.kind === "step" && m.status === "running"
      );
      expect(step).toBeDefined();
    });

    it("separates two rounds of supervisor_stream into distinct messages", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      // Round 1: thinking → stream
      act(() => {
        result.current._testOnSSE("stage_start", { stage: "thinking", label: "思考1" });
        result.current._testOnSSE("supervisor_stream", { chunk: "第一轮" });
      });
      expect(result.current.assistantDraft).toBe("第一轮");

      // Transition: stage_start freezes round 1
      act(() => {
        result.current._testOnSSE("stage_start", { stage: "tool_calling", label: "调用工具" });
      });
      expect(result.current.assistantDraft).toBe("");

      // Round 2: new thinking → stream
      act(() => {
        result.current._testOnSSE("stage_start", { stage: "thinking", label: "思考2" });
        result.current._testOnSSE("supervisor_stream", { chunk: "第二轮" });
      });
      expect(result.current.assistantDraft).toBe("第二轮");

      // Finalize
      act(() => {
        result.current._testOnSSE("supervisor_done", {});
      });

      // Should have two separate frozen messages
      const frozenMsgs = result.current.timeline.filter(
        (m) => m.kind === "message" && m.role === "assistant" && m.content
      );
      expect(frozenMsgs).toHaveLength(2);
      expect(frozenMsgs[0].content).toBe("第一轮");
      expect(frozenMsgs[1].content).toBe("第二轮");
    });
  });

  describe("SSE event: todolist_generated", () => {
    it("adds a requirements_todolist message", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("todolist_generated", {
          intent_summary: "修改大纲",
          todolist: [
            { db_id: "ti-1", task_id: "T1", task: "编辑大纲", status: "pending" },
          ],
          ready_to_execute: true,
        });
      });

      const msg = result.current.timeline.find(
        (m) => m.type === "requirements_todolist"
      );
      expect(msg).toBeDefined();
      expect(msg.todoCard.intent_summary).toBe("修改大纲");
      expect(msg.todoCard.todolist).toHaveLength(1);
      expect(msg.todoCard.ready_to_execute).toBe(true);
    });
  });

  describe("SSE event: subtasks_created", () => {
    it("merges subtasks into existing todolist", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      // First create a todolist
      act(() => {
        result.current._testOnSSE("todolist_generated", {
          intent_summary: "test",
          todolist: [
            { db_id: "ti-1", task_id: "T1", task: "parent task", status: "pending" },
          ],
          ready_to_execute: false,
        });
      });

      // Then add subtasks
      act(() => {
        result.current._testOnSSE("subtasks_created", {
          subtasks: [
            { db_id: "ti-2", task_id: "T1.1", task: "subtask 1", status: "pending" },
          ],
        });
      });

      const msg = result.current.timeline.find(
        (m) => m.type === "requirements_todolist"
      );
      expect(msg.todoCard.todolist).toHaveLength(2);
    });
  });

  describe("SSE event: task_status_updated", () => {
    it("updates task status in existing todolist", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("todolist_generated", {
          intent_summary: "test",
          todolist: [
            { db_id: "ti-1", task_id: "T1", task: "task 1", status: "pending" },
          ],
          ready_to_execute: false,
        });
      });

      act(() => {
        result.current._testOnSSE("task_status_updated", {
          task_item_id: "ti-1",
          new_status: "completed",
          result_summary: "done",
        });
      });

      const msg = result.current.timeline.find(
        (m) => m.type === "requirements_todolist"
      );
      expect(msg.todoCard.todolist[0].status).toBe("completed");
      expect(msg.todoCard.todolist[0].result_summary).toBe("done");
    });
  });

  describe("SSE event: edit_chapter_diff", () => {
    it("sets editDiff for non-readonly diffs", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("edit_chapter_diff", {
          diff: [{ old: "a", new: "b" }],
          summary: { lines_added: 1, lines_removed: 1 },
          new_content: "updated text",
          chapter_number: 3,
          readonly: false,
        });
      });

      expect(result.current.editDiff).toBeDefined();
      expect(result.current.editDiff.chapter_number).toBe(3);
      expect(result.current.editDiff.readonly).toBe(false);
    });

    it("adds message for readonly diffs", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("edit_chapter_diff", {
          diff: [],
          summary: {},
          new_content: "auto",
          chapter_number: 1,
          readonly: true,
        });
      });

      expect(result.current.editDiff).toBe(null);
      const msg = result.current.timeline.find(
        (m) => m.type === "edit_diff_card" && m.diffCard?.readonly
      );
      expect(msg).toBeDefined();
    });
  });

  describe("SSE event: outline_edit_diff", () => {
    it("sets outlineDiff for non-readonly diffs", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("outline_edit_diff", {
          diff: {},
          summary: { total_added: 1 },
          message: "updated",
          operations: [],
          readonly: false,
        });
      });

      expect(result.current.outlineDiff).toBeDefined();
      expect(result.current.outlineDiff.readonly).toBe(false);
    });
  });

  describe("SSE event: characters_updated", () => {
    it("triggers onCharactersUpdated callback", () => {
      const onCharactersUpdated = vi.fn();

      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false, callbacks: { onCharactersUpdated } })
      );

      act(() => {
        result.current._testOnSSE("characters_updated", { message: "角色已更新" });
      });

      expect(onCharactersUpdated).toHaveBeenCalled();
    });
  });

  describe("SSE event: chapter_metadata_generated", () => {
    it("triggers onChapterIntelUpdate callback and adds card", () => {
      const onChapterIntelUpdate = vi.fn();

      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false, callbacks: { onChapterIntelUpdate } })
      );

      act(() => {
        result.current._testOnSSE("chapter_metadata_generated", {
          chapter_number: 5,
          summary: "A summary",
          key_plot_points: ["event1"],
          outline_links: ["T1"],
          involved_characters: ["char1"],
        });
      });

      expect(onChapterIntelUpdate).toHaveBeenCalledWith(
        expect.objectContaining({ chapter_number: 5, summary: "A summary" })
      );

      const card = result.current.timeline.find(
        (m) => m.type === "chapter_meta_card"
      );
      expect(card).toBeDefined();
    });
  });

  // ── resetState ──

  describe("resetState", () => {
    it("clears all state", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      // Set up some state
      act(() => {
        result.current.addMessage("user", "hello");
        result.current._testOnSSE("session_created", { session_id: "s1" });
        result.current.setInput("some text");
        result.current._testOnSSE("supervisor_stream", { chunk: "draft" });
      });

      expect(result.current.sessionId).toBe("s1");
      expect(result.current.timeline.length).toBeGreaterThan(0);

      act(() => {
        result.current.resetState();
      });

      expect(result.current.timeline).toEqual([]);
      expect(result.current.input).toBe("");
      expect(result.current.running).toBe(false);
      expect(result.current.sessionId).toBe(null);
      expect(result.current.assistantDraft).toBe("");
      expect(result.current.editDiff).toBe(null);
      expect(result.current.outlineDiff).toBe(null);
      expect(result.current.characterDiff).toBe(null);
      expect(result.current.confirming).toBe(false);
    });
  });

  // ── handleConfirmEdit ──

  describe("handleConfirmEdit", () => {
    it("sends confirm request with accept action", async () => {
      mockAuthFetchResponse = () => ({ ok: true, status: 200, json: () => Promise.resolve({ status: "accepted" }) });

      const onChapterUpdated = vi.fn();
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false, callbacks: { onChapterUpdated } })
      );

      // Set up state
      act(() => {
        result.current._testOnSSE("session_created", { session_id: "s1" });
        result.current._testOnSSE("edit_chapter_diff", {
          diff: [], summary: {}, new_content: "new", chapter_number: 3, readonly: false,
        });
      });

      await act(async () => {
        await result.current.handleConfirmEdit("accept");
      });

      // Check confirm call was made
      const confirmCall = mockAuthFetchCalls.find((c) => c[0].includes("/supervisor/confirm"));
      expect(confirmCall).toBeDefined();
      const body = JSON.parse(confirmCall[1].body);
      expect(body.action).toBe("accept");
      expect(body.session_id).toBe("s1");

      expect(onChapterUpdated).toHaveBeenCalledWith(3);
    });
  });
});
