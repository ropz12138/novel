import { useCallback, useEffect, useRef, useState } from "react";
import { authFetch } from "../lib/authFetch";
import { API_BASE } from "../lib/runtime-config";
import { workApi } from "../lib/rpcApi";
import { sessionApi } from "../lib/api";
import { normalizeTodoItem } from "../lib/sseEventHandlers";
import { suppressSupersededChapterEditCards } from "../lib/chapterEditDiffCards";

/**
 * Custom hook encapsulating Supervisor chat logic shared between
 * UnifiedAgentPage and SupervisorChatPanel (WorkDetailPage).
 *
 * @param {Object} options
 * @param {string|null} options.workId
 * @param {boolean}     options.autoMode
 * @param {boolean}     options.enableTodolist
 * @param {boolean}     options.enableEvaluation
 * @param {Object}      [options.callbacks]
 * @param {Function}    [options.callbacks.onOutlineUpdated]
 * @param {Function}    [options.callbacks.onChapterUpdated]
 * @param {Function}    [options.callbacks.onCharactersUpdated]
 * @param {Function}    [options.callbacks.onChapterIntelUpdate]
 * @param {Function}    [options.callbacks.onWorkCreated]
 * @param {Function}    [options.callbacks.onNodesUpdate]
 */
export function useSupervisorChat({ workId, chapterNumber, autoMode, enableTodolist = false, enableEvaluation = false, callbacks = {} }) {
  const {
    onOutlineUpdated,
    onChapterUpdated,
    onCharactersUpdated,
    onChapterIntelUpdate,
    onWorkCreated,
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
  const [editDiff, setEditDiff] = useState(null);
  const [outlineDiff, setOutlineDiff] = useState(null);
  const [characterDiff, setCharacterDiff] = useState(null);
  const [confirming, setConfirming] = useState(false);
  const sseRef = useRef(null);
  const lastOutlinePhaseRef = useRef("");
  const lastQueryCategoryRef = useRef(null);

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

  const pushExecStepDone = useCallback((label) => {
    const id = ++timelineIdRef.current;
    setTimeline((prev) => {
      const updated = prev.map((item) =>
        item.kind === "step" && item.status === "running"
          ? { ...item, status: "done", panelOpen: false }
          : item
      );
      return [...updated, { kind: "step", id, label, status: "done", stream: "", panelOpen: false, timestamp: Date.now() }];
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

  const freezeDraft = useCallback(() => {
    const draft = assistantDraftRef.current;
    if (draft && draft.trim()) {
      const id = ++timelineIdRef.current;
      setTimeline((prev) => [...prev, { kind: "message", id, role: "assistant", content: draft, timestamp: Date.now() }]);
    }
    setAssistantDraft("");
    assistantDraftRef.current = "";
    setAssistantReasoningDraft("");
    assistantReasoningDraftRef.current = "";
  }, []);

  // ── SSE event handler ──

  const onSSE = useCallback((ev, d) => {
    switch (ev) {
      case "session_created":
        syncSessionId(d.session_id);
        break;

      case "tool_calls": {
        freezeDraft();
        const label = `调用工具: ${(d.tools || []).join(", ") || "unknown"}`;
        pushExecStepDone(label);
        break;
      }

      case "tool_result":
        if (d.content) {
          finalizeLastRunningStep();
          addMessage("assistant", d.content, { type: "tool_result" });
        }
        break;

      case "tool_executed":
        finalizeLastRunningStep();
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

      case "supervisor_done":
        finalizeAllRunningSteps();
        freezeDraft();
        lastQueryCategoryRef.current = null;
        reconcileTodolist(activeSessionIdRef.current, setTimeline);
        setRunning(false);
        break;

      case "stage_start": {
        freezeDraft();
        lastQueryCategoryRef.current = null;
        const label = d.label || d.stage || "进行中";
        pushExecStep(label);
        break;
      }

      case "outline_stream":
        appendLastRunningStream(d.chunk, d.phase || "content");
        break;

      case "outline_status":
        if (d?.phase && d.phase !== lastOutlinePhaseRef.current) {
          finalizeLastRunningStep();
          pushExecStep(d?.message || d.phase);
          lastOutlinePhaseRef.current = d.phase;
        } else if (d?.message) {
          appendLastRunningStream(`${d.message}\n`);
        }
        break;

      case "outline_tree_progress": {
        const line = formatOutlineProgress(d);
        if (line) appendLastRunningStream(line);
        break;
      }

      case "outline_done": {
        finalizeLastRunningStep();
        lastOutlinePhaseRef.current = "";
        if (onWorkCreated && d.work_id && !d.stage) {
          onWorkCreated(d);
        }
        addMessage("assistant", formatOutlineDoneMessage(d), {
          type: d.stage ? "outline_stage_done" : "outline_created",
          workId: d.work_id,
          title: d.title,
          stage: d.stage,
        });
        break;
      }

      case "outline_edit_done":
        finalizeLastRunningStep();
        addMessage("assistant", d.message || "大纲已编辑。", { type: "outline_edited" });
        if (onOutlineUpdated && workId) {
          workApi.get(workId)
            .then((r) => r.json())
            .then((w) => { if (w.outline_tree) onOutlineUpdated(w.outline_tree); })
            .catch(() => {});
        }
        break;

      case "plan_stream":
      case "thinking_stream":
      case "write_stream":
      case "edit_chapter_stream":
        appendLastRunningStream(d.chunk, d.phase || "content");
        break;

      case "plan_done":
      case "thinking_done":
      case "write_done":
        finalizeLastRunningStep();
        break;

      case "saved": {
        finalizeLastRunningStep();
        const ch = d.chapter_number;
        addMessage("assistant", `第${ch}章「${d.title}」已保存，共 ${d.word_count} 字。`, {
          type: "chapter_saved",
        });
        if (onChapterUpdated) onChapterUpdated(ch);
        break;
      }

      case "evaluation_done":
        finalizeLastRunningStep();
        pushExecStepDone(
          `章节评估完成：编辑 ${d.editor?.total_score ?? "-"} /60，读者 ${d.reader?.total_score ?? "-"} /60`
        );
        break;

      case "title_proposed":
        if (d?.title) pushExecStepDone(`拟定标题: ${d.title}`);
        break;

      case "query_result": {
        const source = d.source || "资料";
        const category = extractQueryCategory(source);
        if (category && lastQueryCategoryRef.current === category) {
          // Merge into the last step of the same category
          setTimeline((prev) => {
            const lastIdx = prev.findLastIndex((item) => item.kind === "step" && item.queryCategory === category);
            if (lastIdx < 0) {
              // fallback: create new step
              const id = ++timelineIdRef.current;
              return [...prev, { kind: "step", id, label: `查询 ${source}`, status: "done", stream: "", panelOpen: false, queryCategory: category, queryCount: 1, querySources: [source], timestamp: Date.now() }];
            }
            const step = prev[lastIdx];
            const newCount = (step.queryCount || 1) + 1;
            const sources = [...(step.querySources || [step.label.replace(/^查询 /, "")]), source];
            const next = [...prev];
            next[lastIdx] = { ...next[lastIdx], label: `查询 ${category} (${newCount}项)`, queryCount: newCount, querySources: sources };
            return next;
          });
        } else {
          lastQueryCategoryRef.current = category;
          const id = ++timelineIdRef.current;
          setTimeline((prev) => {
            const updated = prev.map((item) =>
              item.kind === "step" && item.status === "running"
                ? { ...item, status: "done", panelOpen: false }
                : item
            );
            return [...updated, { kind: "step", id, label: `查询 ${source}`, status: "done", stream: "", panelOpen: false, queryCategory: category, queryCount: 1, querySources: [source], timestamp: Date.now() }];
          });
        }
        break;
      }

      case "characters_updated":
        if (d?.message) pushExecStepDone(d.message);
        if (onCharactersUpdated) onCharactersUpdated();
        break;

      case "nodes_updated":
        // 节点/边创建、更新、删除时触发画布刷新
        if (onNodesUpdate) onNodesUpdate();
        break;

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

      case "subtasks_created": {
        const subtasks = (d.subtasks || []).map(normalizeTodoItem);
        setTimeline((prev) =>
          prev.map((item) => {
            if (item.type !== "requirements_todolist" || !item.todoCard?.todolist) return item;
            const existing = new Set(item.todoCard.todolist.map((t) => t.db_id).filter(Boolean));
            const merged = [...item.todoCard.todolist];
            subtasks.forEach((subtask) => {
              if (!existing.has(subtask.db_id)) {
                merged.push(subtask);
                existing.add(subtask.db_id);
              }
            });
            return { ...item, todoCard: { ...item.todoCard, todolist: merged } };
          })
        );
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

      case "todolist_readiness_updated": {
        const { ready_to_execute } = d || {};
        setTimeline((prev) =>
          prev.map((item) => {
            if (item.type !== "requirements_todolist" || !item.todoCard) return item;
            return { ...item, todoCard: { ...item.todoCard, ready_to_execute: !!ready_to_execute } };
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

      case "edit_chapter_hunk_diff": {
        addMessage("assistant", "", {
          type: "patch_diff_card",
          patchDiffCard: {
            hunks: d.hunks || [],
            summary: d.summary || {},
          },
        });
        break;
      }

      case "edit_chapter_diff": {
        finalizeLastRunningStep();
        if (autoMode) break;
        const readonly = !!d.readonly;
        if (readonly) {
          addMessage("assistant", "", {
            type: "edit_diff_card",
            diffCard: { diff: d.diff, summary: d.summary, new_content: d.new_content, chapter_number: d.chapter_number, readonly: true },
          });
        } else {
          setEditDiff({ diff: d.diff, summary: d.summary, new_content: d.new_content, chapter_number: d.chapter_number, readonly: false });
        }
        break;
      }

      case "edit_chapter_applied":
        if (onChapterUpdated && d.chapter_number) onChapterUpdated(d.chapter_number);
        break;

      case "edit_chapter_auto_applied": {
        finalizeLastRunningStep();
        setEditDiff(null);
        setTimeline((prev) => {
          const ch = d.chapter_number;
          const filtered = prev.filter(
            (item) =>
              !(
                item.kind === "message"
                && item.type === "edit_diff_card"
                && item.diffCard?.chapter_number === ch
                && !item.diffCard?.readonly
              )
          );
          const id = ++timelineIdRef.current;
          return [
            ...filtered,
            {
              kind: "message",
              id,
              role: "assistant",
              content: "",
              type: "edit_diff_card",
              diffCard: {
                diff: d.diff,
                summary: d.summary,
                new_content: d.new_content,
                chapter_number: d.chapter_number,
                readonly: true,
              },
              timestamp: Date.now(),
            },
          ];
        });
        if (onChapterUpdated && d.chapter_number) onChapterUpdated(d.chapter_number);
        break;
      }

      case "edit_chapter_accepted":
        finalizeLastRunningStep();
        setEditDiff(null);
        if (onChapterUpdated && d.chapter_number) onChapterUpdated(d.chapter_number);
        break;

      case "chapter_metadata_diff": {
        addMessage("assistant", "", {
          type: "metadata_diff_card",
          metadataDiffCard: {
            chapter_number: d.chapter_number,
            diff: d.diff,
            diff_summary: d.diff_summary,
          },
        });
        break;
      }

      case "chapter_metadata_generated": {
        finalizeLastRunningStep();
        if (onChapterIntelUpdate) {
          onChapterIntelUpdate({
            chapter_number: d.chapter_number,
            summary: d.summary,
            key_plot_points: d.key_plot_points,
            outline_links: d.outline_links,
            involved_characters: d.involved_characters,
            foreshadows: d.foreshadows,
            facts: d.facts,
          });
        }
        if (d.summary) {
          addMessage("assistant", "", {
            type: "chapter_meta_card",
            chapterMetaCard: {
              chapter_number: d.chapter_number,
              summary: d.summary,
              key_plot_points: d.key_plot_points || [],
            },
          });
        }
        break;
      }

      case "consistency_checked": {
        addMessage("assistant", "", {
          type: "consistency_report_card",
          consistencyReportCard: {
            chapter_number: d.chapter_number,
            consistency_status: d.consistency_status,
            decision: d.decision,
            reason: d.reason,
          },
        });
        break;
      }

      case "outline_edit_diff": {
        finalizeLastRunningStep();
        const readonly = !!d.readonly;
        if (readonly) {
          addMessage("assistant", "", {
            type: "outline_diff_card",
            outlineDiffCard: { diff: d.diff, summary: d.summary, message: d.message, operations: d.operations, readonly: true },
          });
        } else {
          setOutlineDiff({ diff: d.diff, summary: d.summary, message: d.message, operations: d.operations, readonly: false });
          addMessage("assistant", "", {
            type: "outline_diff_card",
            outlineDiffCard: { diff: d.diff, summary: d.summary, message: d.message, operations: d.operations, readonly: false },
          });
        }
        break;
      }

      case "character_edit_diff": {
        finalizeLastRunningStep();
        addMessage("assistant", "", {
          type: "character_diff_card",
          characterDiffCard: { diff: d.diff, summary: d.summary, readonly: !!d.readonly },
        });
        setCharacterDiff({ diff: d.diff, summary: d.summary, readonly: !!d.readonly });
        break;
      }

      case "error":
        finalizeAllRunningSteps();
        addMessage("system", `错误: ${d.message}`, { type: "error" });
        setRunning(false);
        break;

      case "outline_stage_error":
        finalizeAllRunningSteps();
        if (d?.message) {
          addMessage("system", d.message, { type: "outline_stage_error", stage: d.stage });
        }
        break;

      case "supervisor_interrupted":
        finalizeAllRunningSteps();
        freezeDraft();
        addMessage("system", "任务已被中断", { type: "interrupted" });
        setRunning(false);
        break;

      default:
        break;
    }
  }, [
    syncSessionId, freezeDraft, pushExecStep, pushExecStepDone,
    appendLastRunningStream, finalizeLastRunningStep, finalizeAllRunningSteps, addMessage,
    onWorkCreated, onOutlineUpdated, onChapterUpdated, onCharactersUpdated,
    onChapterIntelUpdate, onNodesUpdate, workId, autoMode,
  ]);

  // ── SSE connection ──

  const connectSSE = useCallback((url, body) => {
    setRunning(true);
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
          return;
        }
        if (!res.body) {
          finalizeAllRunningSteps();
          setRunning(false);
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
          finalizeAllRunningSteps();
          setRunning(false);
        })().catch(() => {
          finalizeAllRunningSteps();
          setRunning(false);
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

  const handleSend = useCallback(() => {
    if (running || !input.trim()) return;

    const raw = input.trim();
    const msg = chapterNumber != null ? `[用户正在查看第${chapterNumber}章]\n${raw}` : raw;
    addMessage("user", raw);
    setInput("");

    const sid = activeSessionIdRef.current;
    if (!sid) {
      connectSSE(`${API_BASE}/supervisor/start`, {
        message: msg,
        work_id: workId,
        auto_mode: autoMode,
        enable_todolist: enableTodolist,
        enable_evaluation: enableEvaluation,
      });
    } else {
      connectSSE(`${API_BASE}/supervisor/resume`, {
        session_id: sid,
        message: msg,
        enable_todolist: enableTodolist,
        enable_evaluation: enableEvaluation,
      });
    }
  }, [running, input, chapterNumber, addMessage, connectSSE, workId, autoMode, enableTodolist, enableEvaluation]);

  // ── Confirm handlers ──

  const handleInterrupt = useCallback(async () => {
    const sid = activeSessionIdRef.current || sessionId;
    if (!sid || !running) {
      if (running && !sid) {
        addMessage("system", "中断失败：会话尚未就绪，请稍后再试。", { type: "error" });
      }
      return;
    }
    addMessage("system", "已请求中断，将在当前生成步骤结束后停止…", { type: "interrupt_pending" });
    try {
      const res = await authFetch(`${API_BASE}/supervisor/interrupt`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sid }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        addMessage("system", `中断失败: ${data.detail || `HTTP ${res.status}`}`, { type: "error" });
      }
    } catch (err) {
      addMessage("system", `中断请求失败: ${err.message}`, { type: "error" });
    }
  }, [sessionId, running, addMessage]);

  const handleConfirmEdit = useCallback(async (action, targetDiff = null) => {
    const diffTarget = targetDiff || editDiff;
    if (!sessionId || !diffTarget || confirming) return;
    setConfirming(true);
    try {
      const res = await authFetch(`${API_BASE}/supervisor/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          action,
          new_content: action === "accept" ? diffTarget.new_content : undefined,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || data.message || `HTTP ${res.status}`);
      }
      if (data.error) {
        throw new Error(data.error);
      }
      if (action === "accept") {
        setEditDiff(null);
        setRunning(false);
        const ch = data.chapter_number || diffTarget.chapter_number;
        if (onChapterUpdated) onChapterUpdated(ch);
        addMessage("assistant", `第${ch}章修改已保存。`, { type: "chapter_edited" });
      } else {
        setEditDiff(null);
        setRunning(false);
        addMessage("assistant", "已拒绝修改。", { type: "edit_cancelled" });
      }
    } catch (err) {
      addMessage("system", `确认失败: ${err.message}`, { type: "error" });
    } finally {
      setConfirming(false);
    }
  }, [sessionId, editDiff, confirming, addMessage, onChapterUpdated]);

  const handleConfirmOutline = useCallback(async (action) => {
    if (!sessionId || (!outlineDiff && !characterDiff) || confirming) return;
    setConfirming(true);
    try {
      const res = await authFetch(`${API_BASE}/supervisor/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, action }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || data.message || `HTTP ${res.status}`);
      }
      if (data.error) {
        throw new Error(data.error);
      }
      if (data.status === "accepted") {
        setOutlineDiff(null);
        setCharacterDiff(null);
        setRunning(false);
        addMessage("assistant", "大纲和角色修改已保存。", { type: "outline_edited" });
        if (onOutlineUpdated && workId) {
          workApi.get(workId)
            .then((r) => r.json())
            .then((w) => { if (w.outline_tree) onOutlineUpdated(w.outline_tree); })
            .catch(() => {});
        }
      } else {
        setOutlineDiff(null);
        setCharacterDiff(null);
        setRunning(false);
        addMessage("assistant", "大纲和角色修改已取消，保持原样。", { type: "edit_cancelled" });
      }
    } catch (err) {
      addMessage("system", `确认失败: ${err.message}`, { type: "error" });
    } finally {
      setConfirming(false);
    }
  }, [sessionId, outlineDiff, characterDiff, confirming, addMessage, onOutlineUpdated, workId]);

  // ── Session management ──

  const handleSelectSession = useCallback(async (session) => {
    if (running) return;
    setTimeline([]);
    setInput("");
    setAssistantDraft("");
    assistantDraftRef.current = "";
    setAssistantReasoningDraft("");
    assistantReasoningDraftRef.current = "";
    setEditDiff(null);
    setOutlineDiff(null);
    setCharacterDiff(null);
    setConfirming(false);
    timelineIdRef.current = 0;
    lastOutlinePhaseRef.current = "";
    lastQueryCategoryRef.current = null;

    syncSessionId(session.id);

    try {
      const msgs = await sessionApi.getSupervisorMessages(session.id);
      if (msgs && msgs.length > 0) {
        const loaded = msgs
          .filter((m) => ["user", "assistant", "tool_call", "tool_result"].includes(m.role))
          .map((m) => {
            const id = ++timelineIdRef.current;
            const ts = m.created_at ? new Date(m.created_at).getTime() : Date.now();

            if (m.role === "tool_call") {
              return {
                kind: "message",
                id,
                role: "assistant",
                content: `调用工具: ${m.content || "unknown"}`,
                type: "agent_phase",
                title: "工具调用",
                meta: m.meta || {},
                timestamp: ts,
              };
            }
            if (m.role === "tool_result") {
              return {
                kind: "message",
                id,
                role: "assistant",
                content: m.content || "",
                type: "agent_phase",
                title: `工具结果${m.meta?.tool_name ? ` · ${m.meta.tool_name}` : ""}`,
                meta: m.meta || {},
                timestamp: ts,
              };
            }

            const isProcess = m.meta?.type === "process_note" || (m.meta?.type === "agent_phase" && ["stage_start", "evaluation_done"].includes(m.meta?.event));
            if (m.role === "assistant" && isProcess) {
              return {
                kind: "step",
                id,
                label: m.content || m.meta?.label || "处理中",
                status: "done",
                stream: "",
                panelOpen: false,
                timestamp: ts,
              };
            }

            if (
              m.role === "assistant"
              && m.meta?.type === "requirements_todolist"
              && m.meta?.todoCard
            ) {
              return {
                kind: "message",
                id,
                role: "assistant",
                content: "",
                type: "requirements_todolist",
                todoCard: m.meta.todoCard,
                meta: m.meta || {},
                timestamp: ts,
              };
            }

            if (
              m.role === "assistant"
              && m.meta?.intent === "requirements_planner"
              && m.meta?.requirements_plan
            ) {
              return {
                kind: "message",
                id,
                role: "assistant",
                content: "",
                type: "requirements_todolist",
                todoCard: m.meta.requirements_plan,
                meta: m.meta || {},
                timestamp: ts,
              };
            }

            return {
              kind: "message",
              id,
              role: m.role,
              content: m.content,
              type: m.meta?.type,
              title: m.meta?.title,
              diffCard: m.meta?.diffCard,
              outlineDiffCard: m.meta?.outlineDiffCard,
              characterDiffCard: m.meta?.characterDiffCard,
              patchDiffCard: m.meta?.patchDiffCard,
              chapterMetaCard: m.meta?.chapterMetaCard,
              metadataDiffCard: m.meta?.metadataDiffCard,
              consistencyReportCard: m.meta?.consistencyReportCard,
              meta: m.meta || {},
              timestamp: ts,
            };
          });
        setTimeline(suppressSupersededChapterEditCards(loaded));
      }
    } catch {
      // ignore
    }
  }, [running, syncSessionId]);

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
    lastOutlinePhaseRef.current = "";
    lastQueryCategoryRef.current = null;
    setEditDiff(null);
    setOutlineDiff(null);
    setCharacterDiff(null);
    setConfirming(false);
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
    editDiff,
    outlineDiff,
    characterDiff,
    confirming,
    // state setters (exposed for external use)
    setInput,
    setRunning,
    setAssistantDraft,
    // timeline helpers
    addMessage,
    pushExecStep,
    pushExecStepDone,
    appendLastRunningStream,
    finalizeLastRunningStep,
    finalizeAllRunningSteps,
    toggleStepPanel,
    freezeDraft,
    // actions
    handleSend,
    handleInterrupt,
    handleConfirmEdit,
    handleConfirmOutline,
    handleSelectSession,
    resetState,
    // SSE ref
    sseRef,
    // test-only: expose onSSE for unit testing event handling
    _testOnSSE: onSSE,
  };
}

// ── Helpers ──

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

export function formatOutlineDoneMessage(d) {
  const title = d?.title || "未命名作品";
  switch (d?.stage) {
    case "meso":
      return "中纲生成完成。";
    case "micro":
      return "小纲生成完成。";
    case "character_details":
      return "角色详情生成完成。";
    default:
      return `已创建作品「${title}」的大纲。`;
  }
}

function formatOutlineProgress(d) {
  if (!d?.section || !d?.node) return "";
  const n = d.node;
  if (d.section === "story") return `作品：${n.title || "未命名"}｜${n.genre || "未分类"}｜${n.volume || ""}\n`;
  if (d.section === "macro_phases") return `大纲 ${d.index ?? ""}/${d.total ?? ""}：${n.name || ""}${n.goal ? `｜${n.goal}` : ""}\n`;
  if (d.section === "meso_stages") return `中纲 ${d.index ?? ""}/${d.total ?? ""}：${n.name || ""} - ${n.conflict || n.cause || ""}\n`;
  if (d.section === "foreshadowing") return `伏笔 ${d.index ?? ""}/${d.total ?? ""}：${n.content || ""}\n`;
  if (d.section === "characters") return `角色 ${d.index ?? ""}/${d.total ?? ""}：${n.name || ""}（${n.role_type || "配角"}）\n`;
  return "";
}

/**
 * Extract the "category" from a query_result source string.
 * e.g. "伏笔 F1" -> "伏笔", "第1章大纲" -> "章节大纲", "第1章" -> "前文", "角色设定" -> null (single)
 */
function extractQueryCategory(source) {
  if (!source) return null;
  if (/^伏笔\s/i.test(source)) return "伏笔";
  if (/^第\d+章大纲/.test(source)) return "章节大纲";
  if (/^第\d+章$/.test(source)) return "前文";
  return source;
}

/**
 * Fetch authoritative todolist from server and replace in-memory cards.
 * Ensures the UI reflects final state even if SSE events were missed
 * during long-running sessions.
 */
async function reconcileTodolist(sessionId, setTimeline) {
  if (!sessionId) return;
  try {
    const { sessionApi } = await import("../lib/api.js");
    const msgs = await sessionApi.getSupervisorMessages(sessionId);
    if (!msgs || msgs.length === 0) return;

    const serverCards = [];
    for (const m of msgs) {
      if (m.role !== "assistant" || !m.meta) continue;
      if (m.meta.type === "requirements_todolist" && m.meta.todoCard?.todolist) {
        serverCards.push(m.meta.todoCard);
      } else if (m.meta.intent === "requirements_planner" && m.meta.requirements_plan?.todolist) {
        serverCards.push(m.meta.requirements_plan);
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
