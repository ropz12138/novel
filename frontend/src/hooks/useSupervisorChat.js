import { useCallback, useEffect, useRef, useState } from "react";
import { authFetch } from "../lib/authFetch";
import { API_BASE } from "../lib/runtime-config";
import { sessionApi } from "../lib/api";
import { normalizeTodoItem } from "../lib/sseEventHandlers";
import { suppressSupersededChapterEditCards } from "../lib/chapterEditDiffCards";

/**
 * Custom hook encapsulating Supervisor chat logic for Canvas AgentChat.
 *
 * @param {Object} options
 * @param {string|null} options.workId
 * @param {Object}      [options.callbacks]
 * @param {Function}    [options.callbacks.onChapterUpdated]
 * @param {Function}    [options.callbacks.onNodesUpdate]
 */
export function useSupervisorChat({ workId, callbacks = {} }) {
  const {
    onChapterUpdated,
    onNodesUpdate,
  } = callbacks;

  // ── State ──

  const [timeline, setTimeline] = useState([]);
  const [input, setInput] = useState("");
  const [running, setRunning] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const activeSessionIdRef = useRef(null);
  const [assistantDraft, setAssistantDraft] = useState("");
  const assistantDraftRef = useRef("");
  const [assistantReasoningDraft, setAssistantReasoningDraft] = useState("");
  const assistantReasoningDraftRef = useRef("");
  const timelineIdRef = useRef(0);
  const sseRef = useRef(null);
  const sseCompletedRef = useRef(false);

  const syncSessionId = useCallback((id) => {
    activeSessionIdRef.current = id;
    setSessionId(id);
  }, []);

  // ── Timeline helpers ──

  const pushExecStep = useCallback((label, { panelOpen = true } = {}) => {
    const id = ++timelineIdRef.current;
    setTimeline((prev) => {
      const updated = prev.map((item) =>
        item.kind === "step" && item.status === "running"
          ? { ...item, status: "done", panelOpen: false }
          : item
      );
      return [...updated, { kind: "step", id, label, status: "running", reasoningStream: "", stream: "", panelOpen, timestamp: Date.now() }];
    });
  }, []);

  const appendLastRunningStream = useCallback((chunk, phase = "content") => {
    if (chunk == null || chunk === "") return;
    const field = phase === "reasoning" ? "reasoningStream" : "stream";
    setTimeline((prev) => {
      let i = prev.findLastIndex((item) => item.kind === "step" && item.status === "running");
      let base = prev;
      if (i < 0) {
        const id = ++timelineIdRef.current;
        base = [...prev, { kind: "step", id, label: "进行中", status: "running", reasoningStream: "", stream: "", panelOpen: true, timestamp: Date.now() }];
        i = base.length - 1;
      }
      const next = [...base];
      next[i] = { ...next[i], [field]: (next[i][field] || "") + chunk, panelOpen: true };
      return next;
    });
  }, []);

  const finalizeLastRunningStep = useCallback(() => {
    setTimeline((prev) => applyFinalizeAllRunningSteps(prev, { onlyLast: true }));
  }, []);

  const finalizeAllRunningSteps = useCallback(() => {
    setTimeline((prev) => applyFinalizeAllRunningSteps(prev));
  }, []);

  const toggleStepPanel = useCallback((id) => {
    setTimeline((prev) => {
      const i = prev.findIndex((item) => item.kind === "step" && item.id === id);
      if (i < 0) return prev;
      const next = [...prev];
      next[i] = { ...next[i], panelOpen: !next[i].panelOpen };
      return next;
    });
  }, []);

  const addMessage = useCallback((role, content, meta = {}) => {
    const id = ++timelineIdRef.current;
    setTimeline((prev) => [...prev, { kind: "message", id, role, content, ...meta, timestamp: Date.now() }]);
  }, []);

  const freezeDraft = useCallback((meta = {}) => {
    const draft = assistantDraftRef.current;
    const reasoning = assistantReasoningDraftRef.current;
    const visibleDraft = isPlaceholderEllipsisContent(draft) ? "" : (draft || "");
    if ((visibleDraft && visibleDraft.trim()) || (reasoning && reasoning.trim())) {
      const id = ++timelineIdRef.current;
      setTimeline((prev) => [...prev, {
        kind: "message",
        id,
        role: "assistant",
        content: visibleDraft,
        reasoningContent: reasoning || "",
        ...meta,
        timestamp: Date.now(),
      }]);
    }
    setAssistantDraft("");
    assistantDraftRef.current = "";
    setAssistantReasoningDraft("");
    assistantReasoningDraftRef.current = "";
  }, []);

  const reloadTimelineFromSession = useCallback(async (sid) => {
    const sessionKey = sid || activeSessionIdRef.current;
    if (!sessionKey) return;
    try {
      const msgs = await sessionApi.getSupervisorMessages(sessionKey);
      if (msgs && msgs.length > 0) {
        const loaded = buildTimelineFromHistoryMessages(msgs, timelineIdRef);
        setTimeline(suppressSupersededChapterEditCards(loaded));
      } else {
        setTimeline([]);
      }
    } catch {
      // ignore
    }
  }, []);

  // ── SSE event handler ──

  const onSSE = useCallback((ev, d) => {
    switch (ev) {
      case "session_created":
        syncSessionId(d.session_id);
        break;

      case "user_actions_message_stored":
        if (d.message_id || d.id) {
          setTimeline((prev) => {
            const dbMessageId = d.message_id || d.id;
            if (prev.some((item) => item.dbMessageId === dbMessageId)) {
              return prev;
            }
            const id = ++timelineIdRef.current;
            const item = {
              kind: "message",
              id,
              role: "user",
              content: d.content || "",
              type: "user_canvas_actions",
              dbMessageId,
              meta: d.meta || { type: "user_canvas_actions" },
              timestamp: Date.now(),
            };
            const pendingUserIndex = prev.findLastIndex(
              (entry) => entry.kind === "message"
                && entry.role === "user"
                && !entry.dbMessageId,
            );
            if (pendingUserIndex < 0) return [...prev, item];
            return [
              ...prev.slice(0, pendingUserIndex),
              item,
              ...prev.slice(pendingUserIndex),
            ];
          });
        }
        break;

      case "user_message_stored":
        if (d.message_id) {
          setTimeline((prev) => {
            let i = prev.findLastIndex(
              (item) => item.kind === "message" && item.role === "user" && !item.dbMessageId,
            );
            if (i < 0) return prev;
            const next = [...prev];
            next[i] = { ...next[i], dbMessageId: d.message_id };
            return next;
          });
        }
        break;

      case "canvas_restored":
        if (onNodesUpdate) onNodesUpdate();
        break;

      case "messages_truncated":
        break;

      case "user_message_edited":
        reloadTimelineFromSession(activeSessionIdRef.current);
        break;

      case "tool_calls": {
        freezeDraft();
        // 一次模型响应中的所有工具调用属于同一个执行步骤；先结束上一阶段，
        // 避免“思考中”和多个旧工具步骤同时保持运行状态。
        setTimeline((prev) => appendToolCallSteps(
          applyFinalizeAllRunningSteps(prev), d.tools || [], timelineIdRef,
        ));
        break;
      }

      case "tool_executed":
        setTimeline((prev) => markToolExecuted(
          prev, d.tool, d.success !== false, d.tool_call_id,
        ));
        break;

      case "supervisor_stream": {
        const phase = d.phase || "content";
        if (phase === "reasoning") {
          setAssistantReasoningDraft((p) => {
            const next = p + d.chunk;
            assistantReasoningDraftRef.current = next;
            return next;
          });
        } else {
          setAssistantDraft((p) => {
            const next = p + d.chunk;
            assistantDraftRef.current = next;
            return next;
          });
        }
        break;
      }

      case "supervisor_done": {
        sseCompletedRef.current = true;
        finalizeAllRunningSteps();
        freezeDraft();
        reconcileTodolist(activeSessionIdRef.current, setTimeline);
        setRunning(false);
        break;
      }

      case "stage_start": {
        freezeDraft();
        // tool_calls 已创建工具步骤，忽略配套阶段事件以免重复。
        if (d.stage === "tool" || d.stage === "tool_calling") break;
        const label = d.label || d.stage || "进行中";
        pushExecStep(label);
        break;
      }

      case "chapter_edit_stream":
        appendLastRunningStream(d.chunk, d.phase || "content");
        break;

      case "nodes_updated":
        // 节点/边创建、更新、删除时触发画布刷新
        if (onNodesUpdate) onNodesUpdate();
        break;

      case "chapter_edit_diff":
      case "node_content_diff": {
        const nodeId = d.node_id || d.chapter_node_id;
        const nodeType = d.node_type || (ev === "chapter_edit_diff" ? "chapter" : undefined);
        finalizeAllRunningSteps();
        addMessage("assistant", "", {
          type: "chapter_content_diff_card",
          chapterContentDiffCard: {
            node_id: nodeId,
            chapter_node_id: d.chapter_node_id || nodeId,
            node_type: nodeType,
            title: d.title,
            hunks: d.diff?.hunks ?? [],
            summary: d.diff?.summary ?? {},
            text_count: d.text_count,
            text_count_delta: d.text_count_delta,
            word_count: d.word_count,
            word_count_delta: d.word_count_delta,
          },
        });
        if (nodeType === "chapter" && onChapterUpdated) onChapterUpdated(nodeId);
        if (nodeType !== "chapter" && onNodesUpdate) onNodesUpdate();
        break;
      }

      case "todolist_generated": {
        finalizeLastRunningStep();
        addMessage("assistant", "", {
          type: "requirements_todolist",
          todoCard: {
            intent_summary: d.intent_summary,
            todolist: (d.todolist || []).map(normalizeTodoItem),
            ready_to_execute: d.ready_to_execute,
          },
        });
        break;
      }

      case "task_status_updated": {
        const { task_item_id, new_status, result_summary } = d || {};
        if (!task_item_id) break;
        setTimeline((prev) =>
          prev.map((item) => {
            if (item.type !== "requirements_todolist" || !item.todoCard?.todolist) return item;
            const updatedTodolist = item.todoCard.todolist.map((t) =>
              t.db_id === task_item_id
                ? { ...t, status: new_status, result_summary: result_summary || t.result_summary, error_message: d.error_message || t.error_message }
                : t
            );
            return { ...item, todoCard: { ...item.todoCard, todolist: updatedTodolist } };
          })
        );
        break;
      }

      case "todolist_task_added": {
        const { db_id, task_id, task_description, owner, dispatch_tool, instruction, depends_on, done_criteria, sort_order } = d || {};
        if (!db_id || !task_id) break;
        setTimeline((prev) =>
          prev.map((item) => {
            if (item.type !== "requirements_todolist" || !item.todoCard?.todolist) return item;
            const newTask = {
              db_id,
              task_id,
              task: task_description,
              owner: owner || "supervisor",
              dispatch_tool: dispatch_tool || "none",
              instruction: instruction || task_description,
              depends_on: Array.isArray(depends_on) ? depends_on : (depends_on ? depends_on.split(",").map(s => s.trim()).filter(Boolean) : []),
              done_criteria: done_criteria || "",
              status: "pending",
              depth: 0,
              parent_id: "",
              agent_scope: "supervisor",
              task_type: "",
              sort_order: sort_order ?? item.todoCard.todolist.length,
            };
            return { ...item, todoCard: { ...item.todoCard, todolist: [...item.todoCard.todolist, newTask] } };
          })
        );
        break;
      }

      case "todolist_task_edited": {
        const { db_id: editDbId } = d || {};
        if (!editDbId) break;
        setTimeline((prev) =>
          prev.map((item) => {
            if (item.type !== "requirements_todolist" || !item.todoCard?.todolist) return item;
            const updatedTodolist = item.todoCard.todolist.map((t) => {
              if (t.db_id !== editDbId) return t;
              const updated = { ...t };
              if (d.task_description !== undefined) updated.task = d.task_description;
              if (d.owner !== undefined) updated.owner = d.owner;
              if (d.dispatch_tool !== undefined) updated.dispatch_tool = d.dispatch_tool;
              if (d.instruction !== undefined) updated.instruction = d.instruction;
              if (d.done_criteria !== undefined) updated.done_criteria = d.done_criteria;
              if (d.depends_on !== undefined) {
                updated.depends_on = Array.isArray(d.depends_on) ? d.depends_on : d.depends_on.split(",").map(s => s.trim()).filter(Boolean);
              }
              return updated;
            });
            return { ...item, todoCard: { ...item.todoCard, todolist: updatedTodolist } };
          })
        );
        break;
      }

      case "todolist_task_deleted": {
        const { db_id: delDbId } = d || {};
        if (!delDbId) break;
        setTimeline((prev) =>
          prev.map((item) => {
            if (item.type !== "requirements_todolist" || !item.todoCard?.todolist) return item;
            const filtered = item.todoCard.todolist.filter((t) => t.db_id !== delDbId);
            return { ...item, todoCard: { ...item.todoCard, todolist: filtered } };
          })
        );
        break;
      }

      case "error":
        sseCompletedRef.current = true;
        finalizeAllRunningSteps();
        addMessage("system", `错误: ${d.message}`, { type: "error" });
        setRunning(false);
        break;

      case "supervisor_interrupted":
        sseCompletedRef.current = true;
        finalizeAllRunningSteps();
        freezeDraft();
        addMessage("system", "任务已被中断", { type: "interrupted" });
        setRunning(false);
        break;

      default:
        break;
    }
  }, [
    syncSessionId, freezeDraft, pushExecStep,
    appendLastRunningStream, finalizeLastRunningStep, finalizeAllRunningSteps, addMessage,
    onChapterUpdated, onNodesUpdate, reloadTimelineFromSession,
  ]);

  // ── SSE connection ──

  const connectSSE = useCallback((url, body) => {
    setRunning(true);
    sseCompletedRef.current = false;
    setAssistantDraft("");
    assistantDraftRef.current = "";
    setAssistantReasoningDraft("");
    assistantReasoningDraftRef.current = "";
    timelineIdRef.current = 0;

    const ctl = new AbortController();
    authFetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: ctl.signal,
    })
      .then(async (res) => {
        if (!res.ok) {
          let msg = `HTTP ${res.status}`;
          try {
            const errBody = await res.json();
            msg = errBody.detail || errBody.message || msg;
          } catch {
            try {
              msg = (await res.text()).slice(0, 200) || msg;
            } catch {
              /* ignore */
            }
          }
          finalizeAllRunningSteps();
          setRunning(false);
          addMessage("system", `错误: ${msg}`, { type: "error" });
          sseCompletedRef.current = true;
          return;
        }
        if (!res.body) {
          handleSseStreamFinished({
            sseCompletedRef,
            addMessage,
            finalizeAllRunningSteps,
            setRunning,
          });
          return;
        }
        const reader = res.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        (async () => {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buf += dec.decode(value, { stream: true });
            const lines = buf.split("\n");
            buf = lines.pop() || "";
            let ev = "";
            for (const ln of lines) {
              if (ln.startsWith("event: ")) {
                ev = ln.slice(7).trim();
              } else if (ln.startsWith("data: ")) {
                try {
                  onSSE(ev, JSON.parse(ln.slice(6)));
                } catch {
                  /* ignore */
                }
              }
            }
          }
          handleSseStreamFinished({
            sseCompletedRef,
            addMessage,
            finalizeAllRunningSteps,
            setRunning,
          });
        })().catch(() => {
          handleSseStreamFinished({
            sseCompletedRef,
            addMessage,
            finalizeAllRunningSteps,
            setRunning,
          });
        });
      })
      .catch((e) => {
        finalizeAllRunningSteps();
        setRunning(false);
        if (e?.name !== "AbortError") {
          addMessage("system", `网络错误: ${e?.message || "无法连接后端"}`, { type: "error" });
        }
      });
    sseRef.current = { close: () => ctl.abort() };
  }, [addMessage, onSSE, finalizeAllRunningSteps]);

  // ── handleSend ──

  const handleSend = useCallback((overrideMsg) => {
    if (running) return;

    const raw = (overrideMsg ?? input).trim();
    if (!raw) return;

    addMessage("user", raw);
    setInput("");

    const sid = activeSessionIdRef.current;
    if (!sid) {
      connectSSE(`${API_BASE}/supervisor/start`, {
        message: raw,
        work_id: workId,
      });
    } else {
      connectSSE(`${API_BASE}/supervisor/resume`, {
        session_id: sid,
        message: raw,
      });
    }
  }, [running, input, addMessage, connectSSE, workId]);

  const handleEditResend = useCallback((dbMessageId, newContent) => {
    if (running) return;
    const trimmed = (newContent || "").trim();
    if (!trimmed || !dbMessageId) return;

    const sid = activeSessionIdRef.current;
    if (!sid) return;

    connectSSE(`${API_BASE}/supervisor/edit-resend`, {
      session_id: sid,
      message_id: dbMessageId,
      message: trimmed,
    });
  }, [running, connectSSE]);

  // ── Session management ──

  const handleSelectSession = useCallback(async (session) => {
    if (running) return;
    setTimeline([]);
    setInput("");
    setAssistantDraft("");
    assistantDraftRef.current = "";
    setAssistantReasoningDraft("");
    assistantReasoningDraftRef.current = "";
    timelineIdRef.current = 0;

    syncSessionId(session.id);

    try {
      const msgs = await sessionApi.getSupervisorMessages(session.id);
      if (msgs && msgs.length > 0) {
        const loaded = buildTimelineFromHistoryMessages(msgs, timelineIdRef);
        setTimeline(suppressSupersededChapterEditCards(loaded));
      }
    } catch (error) {
      addMessage("system", `加载对话失败: ${error?.message || "未知错误"}`, {
        type: "error",
      });
    }
  }, [running, syncSessionId, addMessage]);

  const resetState = useCallback(() => {
    setTimeline([]);
    setInput("");
    setRunning(false);
    syncSessionId(null);
    setAssistantDraft("");
    assistantDraftRef.current = "";
    setAssistantReasoningDraft("");
    assistantReasoningDraftRef.current = "";
    timelineIdRef.current = 0;
    if (sseRef.current) {
      sseRef.current.close();
      sseRef.current = null;
    }
  }, [syncSessionId]);

  // ── Return ──

  return {
    // state
    timeline,
    input,
    running,
    sessionId,
    assistantDraft,
    assistantReasoningDraft,
    // state setters (exposed for external use)
    setInput,
    setRunning,
    setAssistantDraft,
    // timeline helpers
    addMessage,
    pushExecStep,
    appendLastRunningStream,
    finalizeLastRunningStep,
    finalizeAllRunningSteps,
    toggleStepPanel,
    freezeDraft,
    // actions
    handleSend,
    handleEditResend,
    handleSelectSession,
    resetState,
    // SSE ref
    sseRef,
    // test-only: expose onSSE for unit testing event handling
    _testOnSSE: onSSE,
  };
}

// ── Helpers ──

/** op-4.8 等模型在连续 tool_call 时常用 "..." / "…" 作为无意义正文占位。 */
export function isPlaceholderEllipsisContent(content) {
  if (content == null) return false;
  const text = String(content).trim();
  return text === "..." || text === "…";
}

function shouldSkipAssistantEllipsisMessage(m) {
  if (m?.role !== "assistant") return false;
  const meta = m.meta || {};
  if (meta.type === "requirements_todolist" && meta.todoCard) return false;
  if (meta.type === "chapter_content_diff_card" && meta.chapterContentDiffCard) return false;
  if (meta.type === "process_note") return false;
  if (meta.type === "agent_phase" && meta.event === "stage_start") return false;
  if (String(meta.reasoning_content || "").trim()) return false;
  return isPlaceholderEllipsisContent(m.content);
}

function messageTimestamp(m) {
  return m.created_at ? new Date(m.created_at).getTime() : Date.now();
}

function mapStoredMessageToTimelineItem(m, idRef) {
  const id = ++idRef.current;
  const ts = messageTimestamp(m);
  const meta = m.meta || {};

  const isProcess = meta.type === "process_note"
    || (meta.type === "agent_phase" && meta.event === "stage_start");
  if (m.role === "assistant" && isProcess) {
    return {
      kind: "step",
      id,
      label: m.content || meta.label || "处理中",
      status: "done",
      stream: "",
      panelOpen: false,
      timestamp: ts,
    };
  }

  if (m.role === "assistant" && meta.type === "requirements_todolist" && meta.todoCard) {
    return {
      kind: "message",
      id,
      role: "assistant",
      content: "",
      type: "requirements_todolist",
      todoCard: meta.todoCard,
      meta,
      timestamp: ts,
    };
  }

  return {
    kind: "message",
    id,
    role: m.role,
    content: m.content,
    reasoningContent: meta.reasoning_content || "",
    type: meta.type,
    title: meta.title,
    chapterContentDiffCard: meta.chapterContentDiffCard,
    dbMessageId: m.id,
    meta,
    timestamp: ts,
  };
}

/** 从 DB 消息重建 timeline，工具 step 与流式 SSE 使用同一套 upsert/mark 逻辑。 */
export function buildTimelineFromHistoryMessages(msgs, idRef = { current: 0 }) {
  const filtered = (msgs || []).filter((m) =>
    ["user", "assistant", "tool_call"].includes(m.role)
    && !shouldSkipAssistantEllipsisMessage(m)
  );

  let timeline = [];
  let i = 0;

  while (i < filtered.length) {
    const m = filtered[i];

    if (m.role === "tool_call") {
      while (i < filtered.length && filtered[i].role === "tool_call") {
        const row = filtered[i];
        const toolName = row.content || "unknown";
        const success = row.meta?.success !== false;
        const ts = messageTimestamp(row);

        timeline = upsertToolCallStep(timeline, [toolName], idRef);
        const stepIdx = timeline.findLastIndex(
          (item) => item.kind === "step" && item.toolCallKey === toolName
        );
        if (stepIdx >= 0) {
          const next = [...timeline];
          next[stepIdx] = { ...next[stepIdx], timestamp: ts };
          timeline = next;
        }
        timeline = markToolExecuted(timeline, toolName, success);
        i += 1;
      }
      continue;
    }

    timeline.push(mapStoredMessageToTimelineItem(m, idRef));
    i += 1;
  }

  return timeline;
}

export function appendToolCallSteps(timeline, tools, idRef) {
  const calls = (tools || []).filter(Boolean);
  return calls.length ? upsertToolCallStep(timeline, calls, idRef) : timeline;
}

export function formatToolCallLabel(tools, count = 1) {
  const names = (tools || []).map(toolCallName).filter(Boolean);
  const base = names.length > 0 ? names.join(", ") : "unknown";
  const label = `工具调用 · ${base}`;
  return count > 1 ? `${label} ×${count}` : label;
}

export function upsertToolCallStep(timeline, tools, idRef) {
  const pendingToolCalls = (tools || []).map(normalizeToolCall);
  const pendingTools = pendingToolCalls.map((call) => call.name);
  const key = pendingToolCalls.map((call) => call.id || call.name).join(",") || "unknown";
  const lastIdx = timeline.length - 1;
  const lastItem = timeline[lastIdx];
  const mergeIdx = lastItem?.kind === "step"
    && lastItem.status === "running"
    && lastItem.toolCallKey === key ? lastIdx : -1;

  if (mergeIdx >= 0) {
    const existing = timeline[mergeIdx];
    const count = (existing.toolCallCount || 1) + 1;
    const next = [...timeline];
    next[mergeIdx] = {
      ...existing,
      status: "running",
      toolCallCount: count,
      label: formatToolCallLabel(pendingTools, count),
      pendingTools,
      pendingToolCalls,
      toolResults: {},
      panelOpen: false,
    };
    return next;
  }

  const id = ++idRef.current;
  return [
    ...timeline,
    {
      kind: "step",
      id,
      label: formatToolCallLabel(pendingTools),
      toolCallKey: key,
      toolCallCount: 1,
      status: "running",
      pendingTools,
      pendingToolCalls,
      toolResults: {},
      stream: "",
      reasoningStream: "",
      panelOpen: false,
      timestamp: Date.now(),
    },
  ];
}

function toolCallName(tool) {
  return typeof tool === "string" ? tool : tool?.name || "";
}

function normalizeToolCall(tool, index) {
  const name = toolCallName(tool) || "unknown";
  return {
    name,
    // 旧 SSE 服务端只发送工具名；保留一个稳定的兼容键。
    id: typeof tool === "string" ? `${name}:${index}` : tool?.id || `${name}:${index}`,
  };
}

export function markToolExecuted(timeline, tool, success, toolCallId = "") {
  const idx = timeline.findLastIndex(
    (item) =>
      item.kind === "step"
      && item.status === "running"
      && (item.pendingToolCalls || []).some((call) =>
        toolCallId ? call.id === toolCallId : call.name === tool
      )
  );
  if (idx < 0) return timeline;

  const next = [...timeline];
  const step = next[idx];
  const resolvedCall = (step.pendingToolCalls || []).find((call) =>
    toolCallId ? call.id === toolCallId : call.name === tool && !(call.id in (step.toolResults || {}))
  );
  if (!resolvedCall) return timeline;
  const toolResults = { ...(step.toolResults || {}), [resolvedCall.id]: success };
  const pending = step.pendingToolCalls || [];
  const allDone = pending.every((call) => call.id in toolResults);
  const anyFailed = Object.values(toolResults).some((v) => v === false);

  next[idx] = {
    ...step,
    toolResults,
    status: allDone ? (anyFailed ? "failed" : "done") : "running",
    panelOpen: false,
  };
  return next;
}

export const SSE_ABNORMAL_END_MESSAGE = "连接中断，Agent 未完成执行。请继续对话重试。";

export function handleSseStreamFinished({ sseCompletedRef, addMessage, finalizeAllRunningSteps, setRunning }) {
  const abnormal = !sseCompletedRef.current;
  finalizeAllRunningSteps();
  setRunning(false);
  if (abnormal) {
    addMessage("system", SSE_ABNORMAL_END_MESSAGE, { type: "error" });
  }
  return abnormal;
}

export function applyFinalizeAllRunningSteps(timeline, { onlyLast = false } = {}) {
  const hasRunning = timeline.some((item) => item.kind === "step" && item.status === "running");
  if (!hasRunning) return timeline;

  if (onlyLast) {
    const i = timeline.findLastIndex((item) => item.kind === "step" && item.status === "running");
    if (i < 0) return timeline;
    const next = [...timeline];
    next[i] = { ...next[i], status: "done", panelOpen: false };
    return next;
  }

  return timeline.map((item) =>
    item.kind === "step" && item.status === "running"
      ? { ...item, status: "done", panelOpen: false }
      : item
  );
}

/**
 * Fetch authoritative todolist from server and replace in-memory cards.
 * Ensures the UI reflects final state even if SSE events were missed
 * during long-running sessions.
 */
async function reconcileTodolist(sessionId, setTimeline) {
  if (!sessionId) return;
  try {
    const msgs = await sessionApi.getSupervisorMessages(sessionId);
    if (!msgs || msgs.length === 0) return;

    const serverCards = [];
    for (const m of msgs) {
      if (m.role !== "assistant" || !m.meta) continue;
      if (m.meta.type === "requirements_todolist" && m.meta.todoCard?.todolist) {
        serverCards.push(m.meta.todoCard);
      }
    }
    if (serverCards.length === 0) return;

    setTimeline((prev) =>
      prev.map((item) => {
        if (item.type !== "requirements_todolist" || !item.todoCard?.todolist) return item;
        const match = serverCards.find(
          (sc) => sc.todolist.length > 0 && item.todoCard.todolist.some((t) => t.db_id === sc.todolist[0].db_id)
        );
        return match ? { ...item, todoCard: match } : item;
      })
    );
  } catch {
    // Reconciliation is best-effort; do not disrupt the user on failure.
  }
}
