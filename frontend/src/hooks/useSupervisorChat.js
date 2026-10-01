import { useCallback, useEffect, useRef, useState } from "react";
import { authFetch } from "../lib/authFetch";
import { API_BASE } from "../lib/runtime-config";
import { sessionApi } from "../lib/api";
import { normalizeTodoItem } from "../lib/sseEventHandlers";
import { suppressSupersededChapterEditCards } from "../lib/chapterEditDiffCards";
import { buildContentDiffFromContents } from "../lib/inlineContentDiff";

/**
 * Custom hook encapsulating Supervisor chat logic for Canvas AgentChat.
 *
 * @param {Object} options
 * @param {string|null} options.workId
 * @param {Object}      [options.callbacks]
 * @param {Function}    [options.callbacks.onChapterUpdated]
 * @param {Function}    [options.callbacks.onNodesUpdate]
 */
export function useSupervisorChat({ workId, callbacks = {}, disconnectPollIntervalMs = 1000 }) {
  const {
    onChapterUpdated,
    onNodesUpdate,
    onNodeContentDiff,
    onNodeContentDiffsReset,
  } = callbacks;

  // ── State ──

  const [timeline, setTimeline] = useState([]);
  const [input, setInput] = useState("");
  const [pendingMessages, setPendingMessages] = useState([]);
  const [running, setRunning] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const activeSessionIdRef = useRef(null);
  const [assistantDraft, setAssistantDraft] = useState("");
  const assistantDraftRef = useRef("");
  const [assistantReasoningDraft, setAssistantReasoningDraft] = useState("");
  const assistantReasoningDraftRef = useRef("");
  const contentPreviewRef = useRef(new Map());
  const timelineIdRef = useRef(0);
  const sseRef = useRef(null);
  const sseCompletedRef = useRef(false);
  const disconnectRecoveryRef = useRef(null);
  const resumeStreamRef = useRef(null);
  const historyCursorRef = useRef(null);
  const hasMoreHistoryRef = useRef(false);
  const historyGenRef = useRef(0);
  const [hasMoreHistory, setHasMoreHistory] = useState(false);

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
    const hasVisible = Boolean(visibleDraft && visibleDraft.trim());
    const hasReasoning = Boolean(reasoning && reasoning.trim());
    if (hasVisible || hasReasoning) {
      setTimeline((prev) => {
        const last = [...prev].reverse().find(
          (item) => item.kind === "message" && item.role === "assistant",
        );
        if (
          last
          && (last.content || "") === visibleDraft
          && (last.reasoningContent || "") === (reasoning || "")
        ) {
          return prev;
        }
        const id = ++timelineIdRef.current;
        return [...prev, {
          kind: "message",
          id,
          role: "assistant",
          content: visibleDraft,
          reasoningContent: reasoning || "",
          ...meta,
          timestamp: Date.now(),
        }];
      });
    }
    setAssistantDraft("");
    assistantDraftRef.current = "";
    setAssistantReasoningDraft("");
    assistantReasoningDraftRef.current = "";
  }, []);

  const rememberHistoryPage = useCallback((page) => {
    const messages = page.messages;
    hasMoreHistoryRef.current = page.has_more;
    setHasMoreHistory(page.has_more);
    const oldest = messages.reduce((min, message) => {
      if (min == null || message.sort_order < min) return message.sort_order;
      return min;
    }, null);
    if (oldest != null) historyCursorRef.current = oldest;
    return messages;
  }, []);

  const replaceTimelineFromPage = useCallback((page) => {
    const messages = rememberHistoryPage(page);
    if (messages.length === 0) {
      setTimeline([]);
      onNodeContentDiffsReset?.();
      return;
    }
    const loaded = buildTimelineFromHistoryMessages(messages, timelineIdRef);
    const visibleTimeline = suppressSupersededChapterEditCards(loaded);
    setTimeline(visibleTimeline);
    restoreNodeContentDiffsFromTimeline(
      visibleTimeline,
      onNodeContentDiffsReset,
      onNodeContentDiff,
    );
  }, [onNodeContentDiff, onNodeContentDiffsReset, rememberHistoryPage]);

  const reloadTimelineFromSession = useCallback(async (sid) => {
    const sessionKey = sid || activeSessionIdRef.current;
    if (!sessionKey) return;
    const gen = ++historyGenRef.current;
    try {
      const page = await sessionApi.getSupervisorMessages(sessionKey);
      if (gen !== historyGenRef.current) return;
      replaceTimelineFromPage(page);
    } catch {
      // ignore
    }
  }, [replaceTimelineFromPage]);

  const recoverDisconnectedRun = useCallback(async () => {
    if (sseCompletedRef.current || disconnectRecoveryRef.current) return;
    const sid = activeSessionIdRef.current;
    if (!sid) {
      finalizeAllRunningSteps();
      setRunning(false);
      addMessage("system", "连接中断，无法确认 Agent 执行状态", { type: "error" });
      return;
    }

    const recovery = {};
    disconnectRecoveryRef.current = recovery;
    finalizeAllRunningSteps();
    setRunning(true);

    try {
      while (disconnectRecoveryRef.current === recovery) {
        const session = await sessionApi.getSupervisor(sid);
        if (disconnectRecoveryRef.current !== recovery) return;

        if (session.status === "running") {
          pushExecStep("重连中...");
          await new Promise((resolve) => setTimeout(resolve, disconnectPollIntervalMs));
          if (disconnectRecoveryRef.current !== recovery) return;
          disconnectRecoveryRef.current = null;
          resumeStreamRef.current?.(sid);
          return;
        }

        sseCompletedRef.current = true;
        setAssistantDraft("");
        assistantDraftRef.current = "";
        setAssistantReasoningDraft("");
        assistantReasoningDraftRef.current = "";
        await reloadTimelineFromSession(sid);
        if (disconnectRecoveryRef.current !== recovery) return;
        onNodesUpdate?.();
        disconnectRecoveryRef.current = null;
        finalizeAllRunningSteps();
        setRunning(false);

        if (session.status === "interrupted") {
          addMessage("system", "Agent 执行已中断", { type: "error" });
        } else if (session.status === "error") {
          addMessage("system", "Agent 执行失败", { type: "error" });
        }
        return;
      }
    } catch (error) {
      if (disconnectRecoveryRef.current !== recovery) return;
      disconnectRecoveryRef.current = null;
      finalizeAllRunningSteps();
      setRunning(false);
      addMessage("system", `无法查询 Agent 执行状态: ${error?.message || "未知错误"}`, {
        type: "error",
      });
    }
  }, [
    addMessage,
    disconnectPollIntervalMs,
    finalizeAllRunningSteps,
    onNodesUpdate,
    pushExecStep,
    reloadTimelineFromSession,
  ]);

  // ── SSE event handler ──

  const onSSE = useCallback((ev, d) => {
    switch (ev) {
      case "queue_updated":
        setPendingMessages(d.pending_messages || []);
        setRunning(Boolean(d.running));
        break;

      case "queued_message_started":
        sseCompletedRef.current = false;
        setRunning(true);
        setAssistantDraft("");
        assistantDraftRef.current = "";
        setAssistantReasoningDraft("");
        assistantReasoningDraftRef.current = "";
        setTimeline((prev) => {
          if (prev.some((item) => item.dbMessageId === d.message_id)) return prev;
          const optimistic = prev.findIndex((item) => item.role === "user" && !item.dbMessageId && item.content === d.content);
          if (optimistic >= 0) return prev.map((item, index) => index === optimistic ? { ...item, dbMessageId: d.message_id } : item);
          return [...prev, { kind: "message", id: ++timelineIdRef.current, role: "user", content: d.content, dbMessageId: d.message_id, timestamp: Date.now() }];
        });
        break;
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
        setTimeline((prev) => {
          const i = prev.findIndex(
            (item) => item.kind === "message" && item.dbMessageId === d.from_message_id,
          );
          return i >= 0 ? prev.slice(0, i) : prev;
        });
        break;

      case "user_message_edited":
        reloadTimelineFromSession(activeSessionIdRef.current);
        break;

      case "tool_calls": {
        const workTools = visibleWorkTools(d.tools || []);
        if (workTools.length === 0) break;
        freezeDraft();
        // 一次模型响应中的所有工具调用属于同一个执行步骤；先结束上一阶段，
        // 避免“思考中”和多个旧工具步骤同时保持运行状态。
        setTimeline((prev) => appendToolCallSteps(
          applyFinalizeAllRunningSteps(prev), workTools, timelineIdRef,
        ));
        break;
      }

      case "tool_executed":
        if (isRespondToUserTool(d.tool)) break;
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
          // 正文已经开始输出时，思考阶段已结束，不应继续显示旋转中的“继续执行”。
          finalizeAllRunningSteps();
          setAssistantDraft((p) => {
            const next = p + d.chunk;
            assistantDraftRef.current = next;
            return next;
          });
        }
        break;
      }

      case "supervisor_turn_done":
      case "supervisor_done": {
        const finished = ev === "supervisor_done";
        sseCompletedRef.current = finished;
        finalizeAllRunningSteps();
        const finalText = typeof d.message === "string" ? d.message : "";
        if (finalText.trim()) {
          assistantDraftRef.current = finalText;
          setAssistantDraft(finalText);
        }
        freezeDraft();
        reconcileTodolist(activeSessionIdRef.current, setTimeline);
        setRunning(!finished);
        if (finished) setPendingMessages([]);
        break;
      }

      case "stage_start": {
        // tool_calls 已创建工具步骤，忽略配套阶段事件以免重复。
        if (d.stage === "tool" || d.stage === "tool_calling") break;
        const label = d.label || d.stage || "进行中";
        if (d.stage === "thinking") {
          // 新一轮思考意味着上一轮输出未被接受；丢弃它，避免最终正文继续拼接后重复显示。
          setAssistantDraft("");
          assistantDraftRef.current = "";
          setAssistantReasoningDraft("");
          assistantReasoningDraftRef.current = "";
        } else {
          freezeDraft();
        }
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

      case "node_content_diff_preview": {
        const nodeId = d.node_id;
        if (!nodeId) break;
        if (d.phase === "start") {
          contentPreviewRef.current.set(nodeId, {
            node_id: nodeId,
            node_type: d.node_type || "chapter",
            title: d.title || "",
            original_content: d.original_content || "",
            current_content: "",
          });
          break;
        }
        const preview = contentPreviewRef.current.get(nodeId);
        if (!preview) break;
        if (d.phase === "delta") preview.current_content += d.chunk || "";
        if (d.phase === "complete") preview.current_content = d.current_content || preview.current_content;
        const hunks = buildContentDiffFromContents(
          preview.original_content,
          preview.current_content,
        );
        const charsAdded = hunks.reduce((sum, hunk) => sum + (hunk.new_text || "").length, 0);
        const charsRemoved = hunks.reduce((sum, hunk) => sum + (hunk.old_text || "").length, 0);
        onNodeContentDiff?.(nodeId, {
          ...preview,
          preview: true,
          preview_phase: d.phase,
          hunks,
          summary: {
            paragraphs_changed: hunks.length,
            chars_added: charsAdded,
            chars_removed: charsRemoved,
          },
        });
        break;
      }

      case "chapter_edit_diff":
      case "node_content_diff": {
        const nodeId = d.node_id || d.chapter_node_id;
        const nodeType = d.node_type || (ev === "chapter_edit_diff" ? "chapter" : undefined);
        contentPreviewRef.current.delete(nodeId);
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
            baseline_content: d.baseline_content,
            original_content: d.original_content,
            current_content: d.current_content,
            text_count: d.text_count,
            text_count_delta: d.text_count_delta,
            word_count: d.word_count,
            word_count_delta: d.word_count_delta,
          },
        });
        if (nodeType === "chapter" && onChapterUpdated) onChapterUpdated(nodeId);
        if (nodeType !== "chapter" && onNodesUpdate) onNodesUpdate();
        if (nodeId && onNodeContentDiff) {
          onNodeContentDiff(nodeId, {
            node_id: nodeId,
            node_type: nodeType,
            title: d.title,
            hunks: d.diff?.hunks ?? [],
            summary: d.diff?.summary ?? {},
            baseline_content: d.baseline_content,
            original_content: d.original_content,
            current_content: d.current_content,
            text_count: d.text_count,
            text_count_delta: d.text_count_delta,
            word_count: d.word_count,
            word_count_delta: d.word_count_delta,
          });
        }
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

      case "supervisor_turn_error":
      case "error":
        sseCompletedRef.current = ev === "error";
        finalizeAllRunningSteps();
        addMessage(
          "system",
          d.message === "AI额度不足，请稍后再试" ? d.message : `错误: ${d.message}`,
          { type: "error" },
        );
        setRunning(ev !== "error");
        if (ev === "error") setPendingMessages([]);
        break;

      case "supervisor_interrupted": {
        setPendingMessages([]);
        sseCompletedRef.current = true;
        finalizeAllRunningSteps();
        setAssistantDraft("");
        assistantDraftRef.current = "";
        setAssistantReasoningDraft("");
        assistantReasoningDraftRef.current = "";
        setRunning(false);
        onNodesUpdate?.();
        Promise.resolve(reloadTimelineFromSession()).finally(() => {
          addMessage("system", "任务已被中断", { type: "interrupted" });
        });
        break;
      }

      default:
        break;
    }
  }, [
    syncSessionId, freezeDraft, pushExecStep,
    appendLastRunningStream, finalizeLastRunningStep, finalizeAllRunningSteps, addMessage,
    onChapterUpdated, onNodesUpdate, onNodeContentDiff, reloadTimelineFromSession,
  ]);

  // ── SSE connection ──

  const connectSSE = useCallback((url, body, { resume = false } = {}) => {
    sseRef.current?.close();
    disconnectRecoveryRef.current = null;
    setRunning(true);
    sseCompletedRef.current = false;
    if (!resume) {
      setAssistantDraft("");
      assistantDraftRef.current = "";
      setAssistantReasoningDraft("");
      assistantReasoningDraftRef.current = "";
      timelineIdRef.current = 0;
    }

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
          recoverDisconnectedRun();
          return;
        }
        const reader = res.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        let ev = "";
        const consumeLines = (chunk) => {
          buf += chunk;
          const lines = buf.split("\n");
          buf = lines.pop() || "";
          for (const ln of lines) {
            if (ln.startsWith("event: ")) {
              ev = ln.slice(7).trim();
            } else if (ln.startsWith("data: ")) {
              try {
                onSSE(ev, JSON.parse(ln.slice(6)));
              } catch {
                /* ignore */
              }
            } else if (ln.trim() === "") {
              ev = "";
            }
          }
        };
        (async () => {
          while (true) {
            const { done, value } = await reader.read();
            if (ctl.signal.aborted) return;
            if (value) consumeLines(dec.decode(value, { stream: !done }));
            if (done) {
              consumeLines(dec.decode());
              if (buf.trim()) consumeLines("\n");
              break;
            }
          }
          if (!sseCompletedRef.current) recoverDisconnectedRun();
        })().catch(() => {
          if (!ctl.signal.aborted && !sseCompletedRef.current) recoverDisconnectedRun();
        });
      })
      .catch((e) => {
        if (e?.name !== "AbortError") {
          recoverDisconnectedRun();
        }
      });
    sseRef.current = { close: () => ctl.abort() };
  }, [onSSE, recoverDisconnectedRun]);

  resumeStreamRef.current = (sid) => connectSSE(`${API_BASE}/supervisor/stream`, {
    session_id: sid,
  }, { resume: true });

  // ── handleSend ──

  const handleStop = useCallback(async () => {
    const sid = activeSessionIdRef.current;
    if (!sid || !running) return;
    setAssistantDraft("");
    assistantDraftRef.current = "";
    setAssistantReasoningDraft("");
    assistantReasoningDraftRef.current = "";
    await sessionApi.stopSupervisor(sid);
  }, [running]);

  const handleSend = useCallback((overrideMsg, chapterReviewIntensity = "medium") => {
    const raw = (overrideMsg ?? input).trim();
    if (!raw) return;

    const sid = activeSessionIdRef.current;
    if (!sid) {
      if (running) return;
      addMessage("user", raw);
      setInput("");
      connectSSE(`${API_BASE}/supervisor/start`, {
        message: raw,
        work_id: workId,
        chapter_review_intensity: chapterReviewIntensity,
      });
    } else {
      void (async () => {
      try {
        const res = await authFetch(`${API_BASE}/supervisor/enqueue`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
        session_id: sid,
        message: raw,
        chapter_review_intensity: chapterReviewIntensity,
          }),
        });
        if (!res.ok) throw new Error("消息提交失败，请重试");
        const state = await res.json();
        setInput("");
        // 保留正在读取的 SSE；空闲或已结束时订阅后端任务流。
        if (state.started_new_stream || !running || sseCompletedRef.current) {
          connectSSE(`${API_BASE}/supervisor/stream`, { session_id: sid }, { resume: true });
        }
      } catch (error) {
        addMessage("system", error.message, { type: "error" });
      }
      })();
    }
  }, [running, input, addMessage, connectSSE, workId]);

  const handleEditResend = useCallback((dbMessageId, newContent, chapterReviewIntensity = "medium") => {
    if (running) return;
    const trimmed = (newContent || "").trim();
    if (!trimmed || !dbMessageId) return;

    const sid = activeSessionIdRef.current;
    if (!sid) return;

    connectSSE(`${API_BASE}/supervisor/edit-resend`, {
      session_id: sid,
      message_id: dbMessageId,
      message: trimmed,
      chapter_review_intensity: chapterReviewIntensity,
    });
  }, [running, connectSSE]);

  // ── Session management ──

  const handleSelectSession = useCallback(async (session) => {
    if (running) return;
    setPendingMessages([]);
    disconnectRecoveryRef.current = null;
    setTimeline([]);
    setInput("");
    setAssistantDraft("");
    assistantDraftRef.current = "";
    setAssistantReasoningDraft("");
    assistantReasoningDraftRef.current = "";
    timelineIdRef.current = 0;
    historyCursorRef.current = null;
    hasMoreHistoryRef.current = false;
    setHasMoreHistory(false);
    const gen = ++historyGenRef.current;

    syncSessionId(session.id);

    try {
      const page = await sessionApi.getSupervisorMessages(session.id);
      if (gen !== historyGenRef.current) return;
      replaceTimelineFromPage(page);
    } catch (error) {
      addMessage("system", `加载对话失败: ${error?.message || "未知错误"}`, {
        type: "error",
      });
    }

    if (session.status === "running") {
      sseCompletedRef.current = false;
      recoverDisconnectedRun();
    }
  }, [
    running,
    syncSessionId,
    addMessage,
    onNodeContentDiff,
    onNodeContentDiffsReset,
    recoverDisconnectedRun,
    replaceTimelineFromPage,
  ]);

  const loadOlderMessages = useCallback(async () => {
    const sid = activeSessionIdRef.current;
    const before = historyCursorRef.current;
    if (!sid || before == null || !hasMoreHistoryRef.current) return;
    const gen = historyGenRef.current;
    const page = await sessionApi.getSupervisorMessages(sid, { beforeSortOrder: before });
    if (gen !== historyGenRef.current) return;
    const messages = page.messages;
    const hasMore = page.has_more && messages.length > 0;
    hasMoreHistoryRef.current = hasMore;
    setHasMoreHistory(hasMore);
    if (messages.length === 0) return;
    historyCursorRef.current = messages.reduce((min, message) => {
      if (min == null || message.sort_order < min) return message.sort_order;
      return min;
    }, null);
    const loaded = buildTimelineFromHistoryMessages(messages, timelineIdRef);
    setTimeline((prev) => suppressSupersededChapterEditCards([...loaded, ...prev]));
  }, []);

  const expandDiffDetail = useCallback(async (messageId) => {
    const sid = activeSessionIdRef.current;
    if (!sid || !messageId) return;
    let alreadyLoaded = false;
    setTimeline((prev) => {
      const item = prev.find((entry) => entry.dbMessageId === messageId);
      alreadyLoaded = Array.isArray(item?.chapterContentDiffCard?.hunks);
      if (!alreadyLoaded) return prev;
      return prev.map((entry) => (
        entry.dbMessageId === messageId ? { ...entry, diffDetailOpen: true } : entry
      ));
    });
    if (alreadyLoaded) return;
    const detail = await sessionApi.getSupervisorDiffDetail(sid, messageId);
    setTimeline((prev) => prev.map((entry) => {
      if (entry.dbMessageId !== messageId) return entry;
      return {
        ...entry,
        diffDetailOpen: true,
        chapterContentDiffCard: {
          ...entry.chapterContentDiffCard,
          hunks: detail.hunks,
        },
      };
    }));
  }, []);

  const collapseDiffDetail = useCallback((messageId) => {
    setTimeline((prev) => prev.map((entry) => (
      entry.dbMessageId === messageId ? { ...entry, diffDetailOpen: false } : entry
    )));
  }, []);

  const resetState = useCallback(() => {
    disconnectRecoveryRef.current = null;
    setPendingMessages([]);
    setTimeline([]);
    setInput("");
    setRunning(false);
    syncSessionId(null);
    setAssistantDraft("");
    assistantDraftRef.current = "";
    setAssistantReasoningDraft("");
    assistantReasoningDraftRef.current = "";
    timelineIdRef.current = 0;
    historyCursorRef.current = null;
    hasMoreHistoryRef.current = false;
    setHasMoreHistory(false);
    historyGenRef.current += 1;
    onNodeContentDiffsReset?.();
    if (sseRef.current) {
      sseRef.current.close();
      sseRef.current = null;
    }
  }, [syncSessionId, onNodeContentDiffsReset]);

  // ── Return ──

  return {
    // state
    timeline,
    hasMoreHistory,
    input,
    pendingMessages,
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
    handleStop,
    handleEditResend,
    handleSelectSession,
    refreshCurrentSession: reloadTimelineFromSession,
    loadOlderMessages,
    expandDiffDetail,
    collapseDiffDetail,
    resetState,
    // SSE ref
    sseRef,
    // test-only: expose onSSE for unit testing event handling
    _testOnSSE: onSSE,
  };
}

// ── Helpers ──

export function restoreNodeContentDiffsFromTimeline(
  _timeline,
  onReset,
  _onNodeContentDiff,
) {
  onReset?.();
}

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
        if (isRespondToUserTool(toolName)) {
          i += 1;
          continue;
        }
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

const RESPOND_TO_USER_TOOL = "respond_to_user";

export function isRespondToUserTool(tool) {
  return toolCallName(tool) === RESPOND_TO_USER_TOOL;
}

export function visibleWorkTools(tools) {
  return (tools || []).filter((tool) => tool && !isRespondToUserTool(tool));
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
    const page = await sessionApi.getSupervisorMessages(sessionId);
    const msgs = page.messages;
    if (msgs.length === 0) return;

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
