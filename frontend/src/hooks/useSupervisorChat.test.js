import { act, renderHook, waitFor } from "@testing-library/react";
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

const { useSupervisorChat, buildTimelineFromHistoryMessages } = await import("./useSupervisorChat.js");

function stripTimelineForCompare(timeline) {
  return timeline.map((item) => {
    if (item.kind === "step") {
      const { id, timestamp, ...rest } = item;
      return rest;
    }
    const { id, timestamp, meta, type, title, diffCard, outlineDiffCard, characterDiffCard,
      patchDiffCard, chapterMetaCard, metadataDiffCard, consistencyReportCard, operatedNodeIds,
      ...rest } = item;
    return rest;
  });
}

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
      expect(result.current.assistantReasoningDraft).toBe("");
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

  describe("finalizeAllRunningSteps", () => {
    it("marks every running step as done", async () => {
      const { applyFinalizeAllRunningSteps } = await import("./useSupervisorChat");
      const timeline = [
        { kind: "step", id: 1, label: "生成小纲", status: "running" },
        { kind: "message", id: 2, role: "user", content: "hi" },
        { kind: "step", id: 3, label: "进行中", status: "running" },
      ];
      const next = applyFinalizeAllRunningSteps(timeline);
      expect(next[0].status).toBe("done");
      expect(next[2].status).toBe("done");
    });

    it("clears running step after stage_start when supervisor_done arrives without outline_done", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current.setRunning(true);
        result.current._testOnSSE("stage_start", { stage: "micro_outline_create", label: "生成小纲" });
        result.current._testOnSSE("supervisor_done", {});
      });

      expect(result.current.timeline.some((item) => item.kind === "step" && item.status === "running")).toBe(false);
      const step = result.current.timeline.find((item) => item.label === "生成小纲");
      expect(step?.status).toBe("done");
      expect(result.current.running).toBe(false);
    });

    it("clears running step on error event", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current.setRunning(true);
        result.current._testOnSSE("stage_start", { stage: "micro_outline_create", label: "生成小纲" });
        result.current._testOnSSE("error", { message: "Request timed out." });
      });

      expect(result.current.timeline.some((item) => item.kind === "step" && item.status === "running")).toBe(false);
      expect(result.current.running).toBe(false);
    });

    it("clears running step on outline_stage_error event", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("stage_start", { stage: "micro_outline_create", label: "生成小纲" });
        result.current._testOnSSE("outline_stage_error", {
          stage: "micro",
          message: "小纲生成失败：timeout",
        });
      });

      expect(result.current.timeline.some((item) => item.kind === "step" && item.status === "running")).toBe(false);
      const errMsg = result.current.timeline.find((m) => m.type === "outline_stage_error");
      expect(errMsg?.content).toContain("小纲生成失败");
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

    it("preserves multiline input in timeline and request body", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: true })
      );

      act(() => {
        result.current.setInput("第一行\n第二行");
      });

      act(() => {
        result.current.handleSend();
      });

      expect(
        result.current.timeline.some((m) => m.role === "user" && m.content === "第一行\n第二行")
      ).toBe(true);

      const body = JSON.parse(mockAuthFetchCalls[0][1].body);
      expect(body.message).toBe("第一行\n第二行");
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
        useSupervisorChat({
          workId: "w1",
          autoMode: false,
          enableTodolist: true,
          enableEvaluation: true,
        })
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
      expect(body.enable_todolist).toBe(true);
      expect(body.enable_evaluation).toBe(true);
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
    it("adds one running step per tool, marks done on tool_executed, and freezes draft", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("supervisor_stream", { chunk: "thinking..." });
      });

      act(() => {
        result.current._testOnSSE("tool_calls", { tools: ["read_outline", "generate_chapter"] });
      });

      expect(result.current.assistantDraft).toBe("");

      const frozenMsg = result.current.timeline.find(
        (m) => m.kind === "message" && m.content === "thinking..."
      );
      expect(frozenMsg).toBeDefined();

      const toolSteps = result.current.timeline.filter((m) => m.kind === "step");
      expect(toolSteps).toHaveLength(2);
      expect(toolSteps[0].label).toBe("工具调用 · read_outline");
      expect(toolSteps[1].label).toBe("工具调用 · generate_chapter");
      expect(toolSteps.every((s) => s.status === "running")).toBe(true);

      act(() => {
        result.current._testOnSSE("tool_executed", { tool: "read_outline", success: true });
        result.current._testOnSSE("tool_executed", { tool: "generate_chapter", success: true });
      });

      const doneSteps = result.current.timeline.filter((m) => m.kind === "step");
      expect(doneSteps.every((s) => s.status === "done")).toBe(true);
    });

    it("marks tool step failed when tool_executed reports success=false", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("tool_calls", { tools: ["write_chapter"] });
        result.current._testOnSSE("tool_executed", { tool: "write_chapter", success: false });
      });

      const toolStep = result.current.timeline.find(
        (m) => m.kind === "step" && m.toolCallKey === "write_chapter"
      );
      expect(toolStep.status).toBe("failed");
    });

    it("ignores tool_result SSE events", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("tool_calls", { tools: ["read_outline"] });
        result.current._testOnSSE("tool_result", { content: '{"hidden": true}' });
      });

      expect(result.current.timeline.filter((m) => m.kind === "message")).toHaveLength(0);
      expect(result.current.timeline.filter((m) => m.kind === "step")).toHaveLength(1);
    });

    it("merges consecutive same-tool calls with ×N counter", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("tool_calls", { tools: ["write_chapter"] });
        result.current._testOnSSE("tool_executed", { tool: "write_chapter", success: true });
      });
      expect(result.current.timeline).toHaveLength(1);
      expect(result.current.timeline[0].label).toBe("工具调用 · write_chapter");
      expect(result.current.timeline[0].status).toBe("done");

      act(() => {
        result.current._testOnSSE("tool_calls", { tools: ["write_chapter"] });
      });
      expect(result.current.timeline).toHaveLength(1);
      expect(result.current.timeline[0].label).toBe("工具调用 · write_chapter ×2");
      expect(result.current.timeline[0].status).toBe("running");

      act(() => {
        result.current._testOnSSE("tool_executed", { tool: "write_chapter", success: true });
      });
      expect(result.current.timeline).toHaveLength(1);
      expect(result.current.timeline[0].label).toBe("工具调用 · write_chapter ×2");
      expect(result.current.timeline[0].status).toBe("done");

      act(() => {
        result.current._testOnSSE("tool_calls", { tools: ["write_chapter"] });
        result.current._testOnSSE("tool_executed", { tool: "write_chapter", success: true });
      });
      expect(result.current.timeline).toHaveLength(1);
      expect(result.current.timeline[0].label).toBe("工具调用 · write_chapter ×3");
    });

    it("resets counter when a different tool is called", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("tool_calls", { tools: ["write_chapter"] });
        result.current._testOnSSE("tool_executed", { tool: "write_chapter", success: true });
        result.current._testOnSSE("tool_calls", { tools: ["write_chapter"] });
        result.current._testOnSSE("tool_executed", { tool: "write_chapter", success: true });
      });
      expect(result.current.timeline).toHaveLength(1);
      expect(result.current.timeline[0].label).toBe("工具调用 · write_chapter ×2");

      act(() => {
        result.current._testOnSSE("tool_calls", { tools: ["read_outline"] });
        result.current._testOnSSE("tool_executed", { tool: "read_outline", success: true });
      });
      expect(result.current.timeline).toHaveLength(2);
      expect(result.current.timeline[0].label).toBe("工具调用 · write_chapter ×2");
      expect(result.current.timeline[1].label).toBe("工具调用 · read_outline");
    });

    it("does not merge different tools from the same tool_calls event", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("tool_calls", { tools: ["write_chapter"] });
        result.current._testOnSSE("tool_executed", { tool: "write_chapter", success: true });
        result.current._testOnSSE("tool_calls", { tools: ["write_chapter", "read_outline"] });
      });

      const toolSteps = result.current.timeline.filter((m) => m.kind === "step");
      expect(toolSteps).toHaveLength(2);
      expect(toolSteps[0].label).toBe("工具调用 · write_chapter ×2");
      expect(toolSteps[1].label).toBe("工具调用 · read_outline");
    });

    it("preserves ×N counter across stage_start events", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("tool_calls", { tools: ["write_chapter"] });
        result.current._testOnSSE("tool_executed", { tool: "write_chapter", success: true });
        result.current._testOnSSE("tool_calls", { tools: ["write_chapter"] });
        result.current._testOnSSE("tool_executed", { tool: "write_chapter", success: true });
      });
      expect(result.current.timeline[0].label).toBe("工具调用 · write_chapter ×2");

      act(() => {
        result.current._testOnSSE("stage_start", { stage: "tool", label: "调用工具: write_chapter" });
      });

      act(() => {
        result.current._testOnSSE("tool_calls", { tools: ["write_chapter"] });
        result.current._testOnSSE("tool_executed", { tool: "write_chapter", success: true });
      });
      const toolSteps = result.current.timeline.filter(
        (m) => m.kind === "step" && m.toolCallKey === "write_chapter"
      );
      expect(toolSteps).toHaveLength(1);
      expect(toolSteps[0].label).toBe("工具调用 · write_chapter ×3");
    });

    it("merges same-tool calls across stage_start/tool_executed interleaving (真实事件流)", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("tool_calls", { tools: ["write_chapter"] });
        result.current._testOnSSE("stage_start", { stage: "tool", label: "调用工具: write_chapter" });
        result.current._testOnSSE("tool_executed", { tool: "write_chapter", success: true });
      });

      act(() => {
        result.current._testOnSSE("tool_calls", { tools: ["write_chapter"] });
        result.current._testOnSSE("stage_start", { stage: "tool", label: "调用工具: write_chapter" });
        result.current._testOnSSE("tool_executed", { tool: "write_chapter", success: true });
      });

      const toolSteps = result.current.timeline.filter(
        (m) => m.kind === "step" && m.toolCallKey === "write_chapter"
      );
      expect(toolSteps).toHaveLength(1);
      expect(toolSteps[0].label).toBe("工具调用 · write_chapter ×2");

      const allToolStepsByLabel = result.current.timeline.filter(
        (m) => m.kind === "step" && m.label.includes("write_chapter")
      );
      expect(allToolStepsByLabel).toHaveLength(1);
    });

    it("does not create duplicate step when stage_start(tool) follows tool_calls", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("tool_calls", { tools: ["read_outline"] });
        result.current._testOnSSE("stage_start", { stage: "tool", label: "调用工具: read_outline" });
      });

      const toolSteps = result.current.timeline.filter(
        (m) => m.kind === "step" && m.label.includes("read_outline")
      );
      expect(toolSteps).toHaveLength(1);
      expect(toolSteps[0].status).toBe("running");
    });

    it("still creates step for non-tool stage_start (e.g. thinking)", () => {
      // 非工具阶段的 stage_start 应照常创建 step（回归保护）
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("stage_start", { stage: "thinking", label: "分析需求" });
      });

      const step = result.current.timeline.find(
        (m) => m.kind === "step" && m.label === "分析需求"
      );
      expect(step).toBeDefined();
      expect(step.status).toBe("running");
    });
  });

  describe("SSE event: supervisor_stream / supervisor_done", () => {
    it("accumulates reasoning stream before content stream", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("supervisor_stream", { chunk: "分析", phase: "reasoning" });
        result.current._testOnSSE("supervisor_stream", { chunk: "中", phase: "reasoning" });
        result.current._testOnSSE("supervisor_stream", { chunk: "你好", phase: "content" });
      });

      expect(result.current.assistantReasoningDraft).toBe("分析中");
      expect(result.current.assistantDraft).toBe("你好");
    });

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

    it("does not trigger onWorkCreated for stage-only outline_done", () => {
      const onWorkCreated = vi.fn();

      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false, callbacks: { onWorkCreated } })
      );

      act(() => {
        result.current._testOnSSE("outline_done", {
          work_id: "w1",
          title: "尸帝",
          stage: "meso",
        });
      });

      expect(onWorkCreated).not.toHaveBeenCalled();
      const msg = result.current.timeline.find((m) => m.type === "outline_stage_done");
      expect(msg?.content).toBe("中纲生成完成。");
    });

    it("shows fallback title when macro outline_done lacks title", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: null, autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("outline_done", { work_id: "w3" });
      });

      const msg = result.current.timeline.find((m) => m.type === "outline_created");
      expect(msg?.content).toBe("已创建作品「未命名作品」的大纲。");
    });
  });

  describe("SSE event: outline_stream", () => {
    it("appends content chunk to running step stream", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current.setRunning(true);
        result.current._testOnSSE("stage_start", { stage: "macro_outline", label: "生成宏纲" });
        result.current._testOnSSE("outline_stream", { chunk: "第一幕：", phase: "content" });
      });

      const step = result.current.timeline.find((s) => s.kind === "step" && s.label === "生成宏纲");
      expect(step?.stream).toContain("第一幕：");
    });

    it("appends reasoning chunk to running step reasoningStream", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current.setRunning(true);
        result.current._testOnSSE("stage_start", { stage: "macro_outline", label: "生成宏纲" });
        result.current._testOnSSE("outline_stream", { chunk: "thinking...", phase: "reasoning" });
      });

      const step = result.current.timeline.find((s) => s.kind === "step" && s.label === "生成宏纲");
      expect(step?.reasoningStream).toContain("thinking...");
    });
  });

  describe("formatOutlineDoneMessage", () => {
    it("formats macro outline creation", async () => {
      const { formatOutlineDoneMessage } = await import("./useSupervisorChat");
      expect(formatOutlineDoneMessage({ title: "尸帝" })).toBe(
        "已创建作品「尸帝」的大纲。"
      );
    });

    it("formats stage-specific messages", async () => {
      const { formatOutlineDoneMessage } = await import("./useSupervisorChat");
      expect(formatOutlineDoneMessage({ stage: "meso", title: "尸帝" })).toBe(
        "中纲生成完成。"
      );
      expect(formatOutlineDoneMessage({ stage: "micro", title: "尸帝" })).toBe(
        "小纲生成完成。"
      );
      expect(formatOutlineDoneMessage({ stage: "character_details", title: "尸帝" })).toBe(
        "角色详情生成完成。"
      );
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

  describe("SSE event: edit_chapter_applied", () => {
    it("triggers onChapterUpdated when chapter content is saved", () => {
      const onChapterUpdated = vi.fn();

      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: true, callbacks: { onChapterUpdated } })
      );

      act(() => {
        result.current._testOnSSE("edit_chapter_applied", {
          chapter_number: 5,
          title: "第五章",
          word_count: 3200,
        });
      });

      expect(onChapterUpdated).toHaveBeenCalledWith(5);
    });

    it("does not call onChapterUpdated when chapter_number is missing", () => {
      const onChapterUpdated = vi.fn();

      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: true, callbacks: { onChapterUpdated } })
      );

      act(() => {
        result.current._testOnSSE("edit_chapter_applied", { title: "第五章", word_count: 3200 });
      });

      expect(onChapterUpdated).not.toHaveBeenCalled();
    });
  });

  describe("SSE event: edit_chapter_accepted", () => {
    it("triggers onChapterUpdated and clears editDiff", () => {
      const onChapterUpdated = vi.fn();

      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false, callbacks: { onChapterUpdated } })
      );

      act(() => {
        result.current._testOnSSE("edit_chapter_diff", {
          diff: [],
          summary: {},
          new_content: "new",
          chapter_number: 3,
          readonly: false,
        });
        result.current._testOnSSE("edit_chapter_accepted", {
          chapter_number: 3,
          title: "第三章",
          word_count: 1500,
        });
      });

      expect(onChapterUpdated).toHaveBeenCalledWith(3);
      expect(result.current.editDiff).toBe(null);
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

  describe("SSE event: edit_chapter_stream / write_stream with phase", () => {
    it("accumulates reasoning and content in running step", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current.pushExecStep("写第1章");
        result.current._testOnSSE("write_stream", { chunk: "构思", phase: "reasoning" });
        result.current._testOnSSE("edit_chapter_stream", { chunk: '{"edits":', phase: "content" });
      });

      const step = result.current.timeline.find((item) => item.kind === "step" && item.status === "running");
      expect(step.reasoningStream).toBe("构思");
      expect(step.stream).toBe('{"edits":');
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

    it("ignores non-readonly diffs in auto mode", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: true })
      );

      act(() => {
        result.current._testOnSSE("edit_chapter_diff", {
          diff: [{ old: "a", new: "b" }],
          summary: { lines_added: 1, lines_removed: 1 },
          new_content: "updated text",
          chapter_number: 1,
          readonly: false,
        });
      });

      expect(result.current.editDiff).toBe(null);
      expect(result.current.timeline.some((m) => m.type === "edit_diff_card")).toBe(false);
    });
  });

  describe("SSE event: chapter_edit_diff", () => {
    it("adds chapter_content_diff_card to timeline", () => {
      const onChapterUpdated = vi.fn();
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: true, callbacks: { onChapterUpdated } })
      );

      act(() => {
        result.current._testOnSSE("chapter_edit_diff", {
          chapter_node_id: "ch-1",
          title: "第1章",
          word_count: 120,
          word_count_delta: 5,
          diff: {
            hunks: [{
              type: "replace",
              paragraph_index: 1,
              old_text: "旧",
              new_text: "新",
            }],
            summary: { paragraphs_changed: 1, chars_added: 1, chars_removed: 1 },
          },
        });
      });

      const msg = result.current.timeline.find((m) => m.type === "chapter_content_diff_card");
      expect(msg).toBeDefined();
      expect(msg.chapterContentDiffCard.title).toBe("第1章");
      expect(msg.chapterContentDiffCard.hunks).toHaveLength(1);
      expect(onChapterUpdated).toHaveBeenCalledWith("ch-1");
    });
  });

  describe("SSE event: chapter_edit_stream", () => {
    it("accumulates stream in running step", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current.pushExecStep("编辑章节");
        result.current._testOnSSE("chapter_edit_stream", { chunk: '{"edits":', phase: "content" });
      });

      const step = result.current.timeline.find((item) => item.kind === "step" && item.status === "running");
      expect(step.stream).toBe('{"edits":');
    });
  });

  describe("SSE event: edit_chapter_auto_applied", () => {
    it("removes pending non-readonly card for same chapter", async () => {
      const { sessionApi } = await import("../lib/api.js");
      sessionApi.getSupervisorMessages.mockResolvedValue([
        {
          role: "assistant",
          content: "",
          meta: {
            type: "edit_diff_card",
            diffCard: {
              chapter_number: 1,
              readonly: false,
              summary: { lines_added: 11, lines_removed: 45 },
              diff: [],
            },
          },
          created_at: new Date().toISOString(),
        },
      ]);

      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: true })
      );

      await act(async () => {
        await result.current.handleSelectSession({ id: "s1" });
      });

      expect(result.current.timeline.filter((m) => m.type === "edit_diff_card")).toHaveLength(1);

      act(() => {
        result.current._testOnSSE("edit_chapter_auto_applied", {
          diff: [],
          summary: { lines_added: 11, lines_removed: 45 },
          new_content: "new",
          chapter_number: 1,
        });
      });

      const cards = result.current.timeline.filter((m) => m.type === "edit_diff_card");
      expect(cards).toHaveLength(1);
      expect(cards[0].diffCard.readonly).toBe(true);
    });

    it("dedupes persisted pending card when loading session with auto-applied card", async () => {
      const { sessionApi } = await import("../lib/api.js");
      sessionApi.getSupervisorMessages.mockResolvedValue([
        {
          role: "assistant",
          content: "",
          meta: {
            type: "edit_diff_card",
            diffCard: { chapter_number: 1, readonly: false, summary: {}, diff: [] },
          },
          created_at: new Date().toISOString(),
        },
        {
          role: "assistant",
          content: "",
          meta: {
            type: "edit_diff_card",
            diffCard: { chapter_number: 1, readonly: true, summary: {}, diff: [] },
          },
          created_at: new Date().toISOString(),
        },
      ]);

      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: true })
      );

      await act(async () => {
        await result.current.handleSelectSession({ id: "s1" });
      });

      const cards = result.current.timeline.filter((m) => m.type === "edit_diff_card");
      expect(cards).toHaveLength(1);
      expect(cards[0].diffCard.readonly).toBe(true);
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

  describe("SSE event: chapter_metadata_diff", () => {
    it("maps diff_summary from d.diff_summary (not d.summary)", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("chapter_metadata_diff", {
          chapter_number: 1,
          summary: "这是一段文本摘要",
          diff: { summary: { type: "modified", old: "旧", new: "新" } },
          diff_summary: { total_added: 10, total_modified: 5, total_removed: 3, total_changes: 18 },
        });
      });

      const msg = result.current.timeline.find(
        (m) => m.type === "metadata_diff_card"
      );
      expect(msg).toBeDefined();
      expect(msg.metadataDiffCard.chapter_number).toBe(1);
      expect(msg.metadataDiffCard.diff_summary).toEqual({
        total_added: 10,
        total_modified: 5,
        total_removed: 3,
        total_changes: 18,
      });
    });
  });

  describe("SSE event: supervisor_done — todolist reconciliation", () => {
    it("reconciles todolist with authoritative server state after stream ends", async () => {
      const { sessionApi } = await import("../lib/api.js");
      const authoritativeTodolist = [
        { db_id: "ti-1", task_id: "T1", task: "task 1", status: "completed", parent_id: "" },
        { db_id: "ti-2", task_id: "T2", task: "task 2", status: "completed", parent_id: "" },
        { db_id: "ti-3", task_id: "T2.1", task: "subtask 1", status: "completed", parent_id: "ti-2" },
      ];
      sessionApi.getSupervisorMessages.mockResolvedValue([
        {
          role: "assistant",
          content: "",
          meta: {
            type: "requirements_todolist",
            todoCard: {
              intent_summary: "test",
              todolist: authoritativeTodolist,
              ready_to_execute: true,
            },
          },
          created_at: new Date().toISOString(),
        },
      ]);

      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      // Set up session and stale todolist (T2 still pending)
      act(() => {
        result.current._testOnSSE("session_created", { session_id: "s1" });
        result.current._testOnSSE("todolist_generated", {
          intent_summary: "test",
          todolist: [
            { db_id: "ti-1", task_id: "T1", task: "task 1", status: "pending" },
            { db_id: "ti-2", task_id: "T2", task: "task 2", status: "pending" },
          ],
          ready_to_execute: true,
        });
      });

      // Verify initial state is stale
      const msgBefore = result.current.timeline.find(
        (m) => m.type === "requirements_todolist"
      );
      expect(msgBefore.todoCard.todolist[1].status).toBe("pending");

      // Fire supervisor_done — triggers reconciliation
      await act(async () => {
        result.current._testOnSSE("supervisor_done", {});
      });

      // After reconciliation, todolist should reflect server state
      await waitFor(() => {
        const msgAfter = result.current.timeline.find(
          (m) => m.type === "requirements_todolist"
        );
        expect(msgAfter.todoCard.todolist[1].status).toBe("completed");
        expect(msgAfter.todoCard.todolist).toHaveLength(3);
        expect(msgAfter.todoCard.todolist[2].task_id).toBe("T2.1");
      });
    });

    it("does not crash if reconciliation fetch fails", async () => {
      const { sessionApi } = await import("../lib/api.js");
      sessionApi.getSupervisorMessages.mockRejectedValue(new Error("network error"));

      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("session_created", { session_id: "s1" });
        result.current._testOnSSE("todolist_generated", {
          intent_summary: "test",
          todolist: [
            { db_id: "ti-1", task_id: "T1", task: "task 1", status: "pending" },
          ],
          ready_to_execute: false,
        });
      });

      // Should not throw
      await act(async () => {
        result.current._testOnSSE("supervisor_done", {});
      });

      // Todolist should remain unchanged (graceful degradation)
      const msg = result.current.timeline.find(
        (m) => m.type === "requirements_todolist"
      );
      expect(msg.todoCard.todolist[0].status).toBe("pending");
      expect(result.current.running).toBe(false);
    });

    it("skips reconciliation when no sessionId exists", async () => {
      const { sessionApi } = await import("../lib/api.js");

      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      // No session_created event — sessionId is null
      await act(async () => {
        result.current._testOnSSE("supervisor_done", {});
      });

      expect(sessionApi.getSupervisorMessages).not.toHaveBeenCalled();
      expect(result.current.running).toBe(false);
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

  // ── todolist_task_added ──

  describe("todolist_task_added", () => {
    it("appends new task to the todolist card", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("session_created", { session_id: "s1" });
        result.current._testOnSSE("todolist_generated", {
          todolist: [
            { db_id: "db1", task_id: "T1", task: "原任务", owner: "supervisor", status: "pending", depth: 0, parent_id: "", agent_scope: "supervisor", depends_on: [], done_criteria: "", task_type: "", dispatch_tool: "none", instruction: "原任务" },
          ],
          intent_summary: "test",
        });
      });

      act(() => {
        result.current._testOnSSE("todolist_task_added", {
          db_id: "db2",
          task_id: "T2",
          task_description: "新任务",
          owner: "chapter_agent",
          dispatch_tool: "dispatch_chapter",
          instruction: "执行新任务",
          depends_on: "T1",
          done_criteria: "完成标准",
          sort_order: 1,
        });
      });

      const msg = result.current.timeline.find((m) => m.type === "requirements_todolist");
      expect(msg.todoCard.todolist).toHaveLength(2);
      const newTask = msg.todoCard.todolist[1];
      expect(newTask.db_id).toBe("db2");
      expect(newTask.task_id).toBe("T2");
      expect(newTask.task).toBe("新任务");
      expect(newTask.status).toBe("pending");
      expect(newTask.depends_on).toEqual(["T1"]);
    });
  });

  // ── todolist_task_edited ──

  describe("todolist_task_edited", () => {
    it("updates existing task fields", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("session_created", { session_id: "s1" });
        result.current._testOnSSE("todolist_generated", {
          todolist: [
            { db_id: "db1", task_id: "T1", task: "旧描述", owner: "supervisor", status: "pending", depth: 0, parent_id: "", agent_scope: "supervisor", depends_on: [], done_criteria: "", task_type: "", dispatch_tool: "none", instruction: "旧指令" },
          ],
          intent_summary: "test",
        });
      });

      act(() => {
        result.current._testOnSSE("todolist_task_edited", {
          db_id: "db1",
          task_description: "新描述",
          instruction: "新指令",
        });
      });

      const msg = result.current.timeline.find((m) => m.type === "requirements_todolist");
      expect(msg.todoCard.todolist[0].task).toBe("新描述");
      expect(msg.todoCard.todolist[0].instruction).toBe("新指令");
    });

    it("preserves fields not included in the update", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("session_created", { session_id: "s1" });
        result.current._testOnSSE("todolist_generated", {
          todolist: [
            { db_id: "db1", task_id: "T1", task: "描述", owner: "chapter_agent", status: "pending", depth: 0, parent_id: "", agent_scope: "supervisor", depends_on: ["T0"], done_criteria: "标准", task_type: "", dispatch_tool: "dispatch_chapter", instruction: "指令" },
          ],
          intent_summary: "test",
        });
      });

      act(() => {
        result.current._testOnSSE("todolist_task_edited", {
          db_id: "db1",
          task_description: "新描述",
        });
      });

      const msg = result.current.timeline.find((m) => m.type === "requirements_todolist");
      const t = msg.todoCard.todolist[0];
      expect(t.task).toBe("新描述");
      expect(t.owner).toBe("chapter_agent");
      expect(t.instruction).toBe("指令");
      expect(t.done_criteria).toBe("标准");
    });
  });

  // ── todolist_task_deleted ──

  describe("todolist_task_deleted", () => {
    it("removes task from the todolist card", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("session_created", { session_id: "s1" });
        result.current._testOnSSE("todolist_generated", {
          todolist: [
            { db_id: "db1", task_id: "T1", task: "任务1", owner: "supervisor", status: "pending", depth: 0, parent_id: "", agent_scope: "supervisor", depends_on: [], done_criteria: "", task_type: "", dispatch_tool: "none", instruction: "任务1" },
            { db_id: "db2", task_id: "T2", task: "任务2", owner: "supervisor", status: "pending", depth: 0, parent_id: "", agent_scope: "supervisor", depends_on: [], done_criteria: "", task_type: "", dispatch_tool: "none", instruction: "任务2" },
          ],
          intent_summary: "test",
        });
      });

      act(() => {
        result.current._testOnSSE("todolist_task_deleted", {
          db_id: "db2",
        });
      });

      const msg = result.current.timeline.find((m) => m.type === "requirements_todolist");
      expect(msg.todoCard.todolist).toHaveLength(1);
      expect(msg.todoCard.todolist[0].db_id).toBe("db1");
    });

    it("does nothing when db_id does not match", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("session_created", { session_id: "s1" });
        result.current._testOnSSE("todolist_generated", {
          todolist: [
            { db_id: "db1", task_id: "T1", task: "任务1", owner: "supervisor", status: "pending", depth: 0, parent_id: "", agent_scope: "supervisor", depends_on: [], done_criteria: "", task_type: "", dispatch_tool: "none", instruction: "任务1" },
          ],
          intent_summary: "test",
        });
      });

      act(() => {
        result.current._testOnSSE("todolist_task_deleted", {
          db_id: "nonexistent",
        });
      });

      const msg = result.current.timeline.find((m) => m.type === "requirements_todolist");
      expect(msg.todoCard.todolist).toHaveLength(1);
    });
  });

  describe("buildTimelineFromHistoryMessages", () => {
    it("merges consecutive same-tool calls with ×N like streaming", () => {
      const timeline = buildTimelineFromHistoryMessages([
        { role: "user", content: "写一章" },
        { role: "assistant", content: "好的", meta: { phase: "intermediate" } },
        { role: "tool_call", content: "write_chapter", meta: { success: true } },
        { role: "tool_call", content: "write_chapter", meta: { success: true } },
        { role: "assistant", content: "写完了", meta: { phase: "final" } },
      ]);

      const toolSteps = timeline.filter((m) => m.kind === "step" && m.toolCallKey === "write_chapter");
      expect(toolSteps).toHaveLength(1);
      expect(toolSteps[0].label).toBe("工具调用 · write_chapter ×2");
      expect(toolSteps[0].status).toBe("done");
    });

    it("creates one step per adjacent tool_call row like streaming", () => {
      const timeline = buildTimelineFromHistoryMessages([
        { role: "assistant", content: "先看大纲", meta: { phase: "intermediate" } },
        { role: "tool_call", content: "read_outline", meta: { success: true } },
        { role: "tool_call", content: "generate_chapter", meta: { success: true } },
      ]);

      const toolSteps = timeline.filter((m) => m.kind === "step");
      expect(toolSteps).toHaveLength(2);
      expect(toolSteps[0].label).toBe("工具调用 · read_outline");
      expect(toolSteps[1].label).toBe("工具调用 · generate_chapter");
    });

    it("does not merge same-tool calls across message boundaries in history", () => {
      const timeline = buildTimelineFromHistoryMessages([
        { role: "user", content: "先设计下一章" },
        { role: "assistant", content: "我先读取上下文", meta: { phase: "intermediate" } },
        { role: "tool_call", content: "read_node_content", meta: { success: true } },
        { role: "assistant", content: "设计完成", meta: { phase: "final" } },
        { role: "user", content: "再设计下一章" },
        { role: "assistant", content: "继续读取上下文", meta: { phase: "intermediate" } },
        { role: "tool_call", content: "read_node_content", meta: { success: true } },
        { role: "assistant", content: "新的设计完成", meta: { phase: "final" } },
      ]);

      const toolSteps = timeline.filter((m) => m.kind === "step" && m.toolCallKey === "read_node_content");
      expect(toolSteps).toHaveLength(2);
      expect(toolSteps[0].label).toBe("工具调用 · read_node_content");
      expect(toolSteps[1].label).toBe("工具调用 · read_node_content");
    });

    it("marks failed tool batch with failed status", () => {
      const timeline = buildTimelineFromHistoryMessages([
        { role: "tool_call", content: "write_chapter", meta: { success: false } },
      ]);

      expect(timeline[0].status).toBe("failed");
    });

    it("keeps write_todolist step before requirements_todolist bubble in history", () => {
      const timeline = buildTimelineFromHistoryMessages([
        { role: "assistant", content: "我来规划", meta: { phase: "intermediate" } },
        { role: "tool_call", content: "write_todolist", meta: { success: true } },
        {
          role: "assistant",
          content: "",
          meta: {
            type: "requirements_todolist",
            todoCard: {
              todolist: [{ task_id: "T1", task: "任务A", status: "pending" }],
              ready_to_execute: true,
            },
          },
        },
      ]);

      const toolIdx = timeline.findIndex(
        (m) => m.kind === "step" && m.toolCallKey === "write_todolist"
      );
      const todoIdx = timeline.findIndex((m) => m.type === "requirements_todolist");
      expect(toolIdx).toBeGreaterThanOrEqual(0);
      expect(todoIdx).toBeGreaterThan(toolIdx);
    });

    it("produces the same tool step shape as streaming SSE for an equivalent turn", () => {
      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      act(() => {
        result.current._testOnSSE("supervisor_stream", { chunk: "让我看看画布" });
        result.current._testOnSSE("tool_calls", { tools: ["get_canvas_index", "query_nodes"] });
        result.current._testOnSSE("tool_executed", { tool: "get_canvas_index", success: true });
        result.current._testOnSSE("tool_executed", { tool: "query_nodes", success: true });
      });

      act(() => {
        result.current._testOnSSE("supervisor_stream", { chunk: "当前有 3 个节点" });
        result.current._testOnSSE("supervisor_done", {});
      });

      const streamingSteps = stripTimelineForCompare(
        result.current.timeline.filter((m) => m.kind === "step")
      );
      const historySteps = stripTimelineForCompare(
        buildTimelineFromHistoryMessages([
          { role: "assistant", content: "让我看看画布", meta: { phase: "intermediate" } },
          { role: "tool_call", content: "get_canvas_index", meta: { success: true } },
          { role: "tool_call", content: "query_nodes", meta: { success: true } },
          { role: "assistant", content: "当前有 3 个节点", meta: { phase: "final" } },
        ]).filter((m) => m.kind === "step")
      );

      expect(historySteps).toEqual(streamingSteps);
    });
  });

  describe("handleSelectSession — history replay", () => {
    it("loads session with merged tool steps matching streaming rules", async () => {
      const { sessionApi } = await import("../lib/api.js");
      sessionApi.getSupervisorMessages.mockResolvedValue([
        { role: "user", content: "你好", created_at: new Date().toISOString() },
        { role: "assistant", content: "正在处理", meta: { phase: "intermediate" }, created_at: new Date().toISOString() },
        { role: "tool_call", content: "write_chapter", meta: { success: true }, created_at: new Date().toISOString() },
        { role: "tool_call", content: "write_chapter", meta: { success: true }, created_at: new Date().toISOString() },
        { role: "assistant", content: "完成", meta: { phase: "final" }, created_at: new Date().toISOString() },
      ]);

      const { result } = renderHook(() =>
        useSupervisorChat({ workId: "w1", autoMode: false })
      );

      await act(async () => {
        await result.current.handleSelectSession({ id: "s1" });
      });

      const toolStep = result.current.timeline.find(
        (m) => m.kind === "step" && m.toolCallKey === "write_chapter"
      );
      expect(toolStep.label).toBe("工具调用 · write_chapter ×2");
      expect(result.current.timeline.filter((m) => m.role === "user")).toHaveLength(1);
    });
  });

  describe("SSE stream abnormal end", () => {
    it("shows error when stream ends without supervisor_done", async () => {
      const { handleSseStreamFinished, SSE_ABNORMAL_END_MESSAGE } = await import("./useSupervisorChat");
      const sseCompletedRef = { current: false };
      const messages = [];
      const timeline = [
        { kind: "step", id: 1, label: "AI 思考中", status: "running" },
      ];
      let running = true;

      handleSseStreamFinished({
        sseCompletedRef,
        addMessage: (_role, content, meta) => messages.push({ content, meta }),
        finalizeAllRunningSteps: () => {
          timeline[0].status = "done";
        },
        setRunning: (v) => { running = v; },
      });

      expect(messages).toHaveLength(1);
      expect(messages[0].content).toBe(SSE_ABNORMAL_END_MESSAGE);
      expect(messages[0].meta.type).toBe("error");
      expect(timeline[0].status).toBe("done");
      expect(running).toBe(false);
    });

    it("does not show error when supervisor_done already received", async () => {
      const { handleSseStreamFinished } = await import("./useSupervisorChat");
      const sseCompletedRef = { current: true };
      const messages = [];
      let running = true;

      const abnormal = handleSseStreamFinished({
        sseCompletedRef,
        addMessage: (_role, content) => messages.push({ content }),
        finalizeAllRunningSteps: () => {},
        setRunning: (v) => { running = v; },
      });

      expect(abnormal).toBe(false);
      expect(messages).toHaveLength(0);
      expect(running).toBe(false);
    });
  });
});
