import { API_BASE } from "../lib/runtime-config";
import { authFetch } from "../lib/authFetch";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  BookOpen,
  Check,
  Loader2,
  MessageSquare,
  PenLine,
  Send,
  Sparkles,
  Zap,
  Bot,
  User,
  GitBranch,
  X,
} from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { DiffViewer } from "../components/agent/DiffViewer";
import { OutlineDiffViewer } from "../components/agent/OutlineDiffViewer";
import { CharacterDiffViewer } from "../components/agent/CharacterDiffViewer";
import { PatchDiffViewer } from "../components/agent/PatchDiffViewer";
import { MetadataDiffViewer } from "../components/agent/MetadataDiffViewer";
import { SessionSidebar } from "../components/SessionSidebar";
import { sessionApi } from "../lib/api";


const mdComponents = {
  h1: ({ node, ...props }) => <h1 className="text-base font-bold text-slate-800 mt-3 mb-1.5" {...props} />,
  h2: ({ node, ...props }) => <h2 className="text-sm font-bold text-slate-800 mt-2.5 mb-1" {...props} />,
  h3: ({ node, ...props }) => <h3 className="text-sm font-semibold text-slate-700 mt-2 mb-0.5" {...props} />,
  ul: ({ node, ...props }) => <ul className="list-disc pl-5 my-1.5 space-y-0.5" {...props} />,
  ol: ({ node, ...props }) => <ol className="list-decimal pl-5 my-1.5 space-y-0.5" {...props} />,
  li: ({ node, ...props }) => <li className="text-sm" {...props} />,
  p: ({ node, ...props }) => <p className="my-1.5" {...props} />,
  strong: ({ node, ...props }) => <strong className="font-semibold text-slate-800" {...props} />,
  code: ({ node, inline, ...props }) =>
    inline ? (
      <code className="rounded bg-slate-100 px-1 py-0.5 text-xs text-violet-700" {...props} />
    ) : (
      <code className="block rounded bg-slate-50 p-2.5 text-xs text-slate-600 overflow-x-auto my-2" {...props} />
    ),
  hr: ({ node, ...props }) => <hr className="my-3 border-slate-200" {...props} />,
  blockquote: ({ node, ...props }) => (
    <blockquote className="border-l-3 border-blue-300 pl-3 my-2 text-slate-600 italic" {...props} />
  ),
  table: ({ node, ...props }) => (
    <div className="overflow-x-auto my-2">
      <table className="text-xs border-collapse" {...props} />
    </div>
  ),
  th: ({ node, ...props }) => <th className="border border-slate-200 px-2 py-1 bg-slate-50 font-medium" {...props} />,
  td: ({ node, ...props }) => <td className="border border-slate-200 px-2 py-1" {...props} />,
};

function intentBadge(intent) {
  const map = {
    create_outline: { text: "创建大纲", color: "bg-purple-100 text-purple-700" },
    edit_outline: { text: "编辑大纲", color: "bg-blue-100 text-blue-700" },
    write_chapter: { text: "撰写章节", color: "bg-green-100 text-green-700" },
    edit_chapter: { text: "修改章节", color: "bg-amber-100 text-amber-700" },
    chat: { text: "对话", color: "bg-slate-100 text-slate-600" },
  };
  const info = map[intent] || map.chat;
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${info.color}`}>
      {info.text}
    </span>
  );
}

function formatOutlineProgress(d) {
  if (!d?.section || !d?.node) return "";
  const n = d.node;
  if (d.section === "story") return `📘 作品：${n.title || "未命名"}｜${n.genre || "未分类"}｜${n.volume || ""}\n`;
  if (d.section === "timeline") return `🧭 主线 ${d.index}/${d.total}：${n.time_node || ""} - ${n.development_node || ""}${n.summary ? `｜${n.summary}` : ""}\n`;
  if (d.section === "branches") return `🌿 支线 ${d.index}/${d.total}：${n.name || ""} - ${n.summary || ""}\n`;
  if (d.section === "foreshadowing") return `🪝 伏笔 ${d.index}/${d.total}：${n.content || ""}\n`;
  if (d.section === "characters") return `👤 角色 ${d.index}/${d.total}：${n.name || ""}（${n.role_type || "配角"}）\n`;
  return "";
}

export function UnifiedAgentPage() {
  const navigate = useNavigate();
  const [timeline, setTimeline] = useState([]);
  const [input, setInput] = useState("");
  const [running, setRunning] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const activeSessionIdRef = useRef(null);
  const [workId, setWorkId] = useState(null);
  const [workTitle, setWorkTitle] = useState(null);
  const [currentStage, setCurrentStage] = useState(null);
  const [currentIntent, setCurrentIntent] = useState(null);
  const [assistantDraft, setAssistantDraft] = useState("");
  const timelineIdRef = useRef(0);
  const [editDiff, setEditDiff] = useState(null); // { diff, summary, new_content, chapter_number, readonly }
  const [outlineDiff, setOutlineDiff] = useState(null); // { diff, summary }
  const [characterDiff, setCharacterDiff] = useState(null); // { diff, summary }
  const [confirming, setConfirming] = useState(false);
  const [sessionSidebarOpen, setSessionSidebarOpen] = useState(false);
  const [autoMode, setAutoMode] = useState(true);

  const chatEndRef = useRef(null);
  const sseRef = useRef(null);
  const assistantDraftRef = useRef("");
  const lastOutlinePhaseRef = useRef("");

  const syncSessionId = (id) => {
    activeSessionIdRef.current = id;
    setSessionId(id);
  };

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [timeline, assistantDraft, editDiff, outlineDiff, characterDiff, running]);

  // Close any running steps, then append a new running step
  const pushExecStep = (label, { panelOpen = true } = {}) => {
    const id = ++timelineIdRef.current;
    setTimeline((prev) => {
      const updated = prev.map((item) =>
        item.kind === "step" && item.status === "running"
          ? { ...item, status: "done", panelOpen: false }
          : item
      );
      return [...updated, { kind: "step", id, label, status: "running", stream: "", panelOpen, timestamp: Date.now() }];
    });
  };

  // Close any running steps, then append a done step
  const pushExecStepDone = (label) => {
    const id = ++timelineIdRef.current;
    setTimeline((prev) => {
      const updated = prev.map((item) =>
        item.kind === "step" && item.status === "running"
          ? { ...item, status: "done", panelOpen: false }
          : item
      );
      return [...updated, { kind: "step", id, label, status: "done", stream: "", panelOpen: false, timestamp: Date.now() }];
    });
  };

  const appendLastRunningStream = (chunk) => {
    if (chunk == null || chunk === "") return;
    setTimeline((prev) => {
      let i = prev.findLastIndex((item) => item.kind === "step" && item.status === "running");
      let base = prev;
      if (i < 0) {
        const id = ++timelineIdRef.current;
        base = [...prev, { kind: "step", id, label: "进行中", status: "running", stream: "", panelOpen: true, timestamp: Date.now() }];
        i = base.length - 1;
      }
      const next = [...base];
      next[i] = { ...next[i], stream: next[i].stream + chunk, panelOpen: true };
      return next;
    });
  };

  const finalizeLastRunningStep = () => {
    setTimeline((prev) => {
      const i = prev.findLastIndex((item) => item.kind === "step" && item.status === "running");
      if (i < 0) return prev;
      const next = [...prev];
      next[i] = { ...next[i], status: "done", panelOpen: false };
      return next;
    });
  };

  const toggleStepPanel = (id) => {
    setTimeline((prev) => {
      const i = prev.findIndex((item) => item.kind === "step" && item.id === id);
      if (i < 0) return prev;
      const next = [...prev];
      next[i] = { ...next[i], panelOpen: !next[i].panelOpen };
      return next;
    });
  };

  // Load session list on mount
  useEffect(() => {
    const loadSessions = async () => {
      try {
        const list = await sessionApi.listSupervisor(workId);
        // list is stored in SessionSidebar internally, no need for local state
      } catch {
        // ignore
      }
    };
    loadSessions();
  }, [workId]);

  // Load messages when selecting an existing session
  const handleSelectSession = async (session) => {
    if (running) return;
    resetState();
    syncSessionId(session.id);
    if (session.work_id) {
      setWorkId(session.work_id);
    }
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
              chapterMetaCard: m.meta?.chapterMetaCard,
              metadataDiffCard: m.meta?.metadataDiffCard,
              consistencyReportCard: m.meta?.consistencyReportCard,
              meta: m.meta || {},
              timestamp: ts,
            };
          });
        setTimeline(loaded);
      }
    } catch {
      // ignore
    }
  };

  const resetState = () => {
    setTimeline([]);
    setInput("");
    setRunning(false);
    syncSessionId(null);
    setWorkId(null);
    setWorkTitle(null);
    setCurrentStage(null);
    setCurrentIntent(null);
    setAssistantDraft("");
    timelineIdRef.current = 0;
    setEditDiff(null);
    setConfirming(false);
    setAutoMode(false);
    if (sseRef.current) {
      sseRef.current.close();
      sseRef.current = null;
    }
  };

  const addMessage = (role, content, meta = {}) => {
    const id = ++timelineIdRef.current;
    setTimeline((prev) => [...prev, { kind: "message", id, role, content, ...meta, timestamp: Date.now() }]);
  };

  const freezeDraft = () => {
    const draft = assistantDraftRef.current;
    if (draft && draft.trim()) {
      const id = ++timelineIdRef.current;
      setTimeline((prev) => [...prev, { kind: "message", id, role: "assistant", content: draft, timestamp: Date.now() }]);
    }
    setAssistantDraft("");
    assistantDraftRef.current = "";
  };

  const connectSSE = (url, body) => {
    setRunning(true);
    setAssistantDraft("");
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
          setRunning(false);
          addMessage("system", `错误: ${msg}`, { type: "error" });
          return;
        }
        if (!res.body) {
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
          setRunning(false);
        })().catch(() => setRunning(false));
      })
      .catch((e) => {
        setRunning(false);
        if (e?.name !== "AbortError") {
          addMessage("system", `网络错误: ${e?.message || "无法连接后端"}`, { type: "error" });
        }
      });
    sseRef.current = { close: () => ctl.abort() };
  };

  const onSSE = (ev, d) => {
    switch (ev) {
      case "session_created":
        syncSessionId(d.session_id);
        break;
      case "tool_calls": {
        freezeDraft();
        const label = `调用工具: ${(d.tools || []).join(", ") || "unknown"}`;
        const id = ++timelineIdRef.current;
        setTimeline((prev) => {
          const updated = prev.map((item) =>
            item.kind === "step" && item.status === "running"
              ? { ...item, status: "done", panelOpen: false }
              : item
          );
          return [...updated, { kind: "step", id, label, status: "done", stream: "", panelOpen: false, timestamp: Date.now() }];
        });
        break;
      }
      case "tool_result":
        break;
      case "tool_executed":
        break;
      case "supervisor_stream":
        setAssistantDraft((p) => {
          const next = p + d.chunk;
          assistantDraftRef.current = next;
          return next;
        });
        break;
      case "supervisor_done": {
        finalizeLastRunningStep();
        freezeDraft();
        setCurrentStage("done");
        setCurrentIntent(null);
        break;
      }
      case "stage_start": {
        const label = d.label || d.stage || "进行中";
        setCurrentStage(d.stage);
        if (d.stage === "thinking" || d.stage === "tool_calling") {
          freezeDraft();
        }
        pushExecStep(label);
        break;
      }

      case "outline_stream":
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
        if (d.work_id) {
          setWorkId(d.work_id);
          setWorkTitle(d.title);
        }
        addMessage("assistant", `已创建作品「${d.title}」的大纲。`, { type: "outline_created", workId: d.work_id, title: d.title });
        break;
      }

      case "outline_edit_done":
        finalizeLastRunningStep();
        addMessage("assistant", d.message || "大纲已编辑。", { type: "outline_edited" });
        break;

      case "plan_stream":
      case "thinking_stream":
      case "write_stream":
      case "edit_chapter_stream":
        appendLastRunningStream(d.chunk);
        break;
      case "plan_done":
        finalizeLastRunningStep();
        break;
      case "thinking_done":
        finalizeLastRunningStep();
        break;
      case "write_done":
        finalizeLastRunningStep();
        break;
      case "evaluation_done":
        finalizeLastRunningStep();
        pushExecStepDone(
          `章节评估完成：编辑 ${d.editor?.total_score ?? "-"} /60，读者 ${d.reader?.total_score ?? "-"} /60`
        );
        break;
      case "saved":
        finalizeLastRunningStep();
        addMessage("assistant", `第${d.chapter_number}章「${d.title}」已保存，共 ${d.word_count} 字。`, {
          type: "chapter_saved",
        });
        break;
      case "title_proposed":
        if (d?.title) pushExecStepDone(`拟定标题: ${d.title}`);
        break;
      case "query_result":
        pushExecStepDone(`查询 ${d.source || "资料"}: ${String(d.summary || "").slice(0, 100)}`);
        break;
      case "characters_updated":
        if (d?.message) pushExecStepDone(d.message);
        break;
      case "todolist_generated":
        finalizeLastRunningStep();
        addMessage("assistant", "", {
          type: "requirements_todolist",
          todoCard: {
            intent_summary: d.intent_summary,
            todolist: (d.todolist || []).map((t) => ({
              db_id: t.db_id || "",
              task_id: t.task_id || t.id || "",
              task: t.task || "",
              owner: t.owner || "supervisor",
              status: t.status || "pending",
              depends_on: t.depends_on || [],
              done_criteria: t.done_criteria || "",
            })),
            ready_to_execute: d.ready_to_execute,
          },
        });
        break;
      case "task_status_updated": {
        const { task_item_id, new_status, result_summary } = d || {};
        if (!task_item_id) break;
        setMessages((prev) =>
          prev.map((msg) => {
            if (msg.meta?.type !== "requirements_todolist" || !msg.meta?.todoCard?.todolist) return msg;
            const updatedTodolist = msg.meta.todoCard.todolist.map((t) =>
              t.db_id === task_item_id ? { ...t, status: new_status, result_summary: result_summary || t.result_summary } : t
            );
            return { ...msg, meta: { ...msg.meta, todoCard: { ...msg.meta.todoCard, todolist: updatedTodolist } } };
          })
        );
        break;
      }

      case "todolist_readiness_updated": {
        const { ready_to_execute } = d || {};
        setMessages((prev) =>
          prev.map((msg) => {
            if (msg.meta?.type !== "requirements_todolist" || !msg.meta?.todoCard) return msg;
            return { ...msg, meta: { ...msg.meta, todoCard: { ...msg.meta.todoCard, ready_to_execute: !!ready_to_execute } } };
          })
        );
        break;
      }

      case "edit_chapter_hunk_diff":
        {
        addMessage("assistant", "", {
          type: "patch_diff_card",
          patchDiffCard: {
            hunks: d.hunks || [],
            summary: d.summary || {},
          },
        });
        }
        break;

      case "edit_chapter_diff":
        finalizeLastRunningStep();
        {
        const card = {
          diff: d.diff,
          summary: d.summary,
          new_content: d.new_content,
          chapter_number: d.chapter_number,
          readonly: false,
        };
        setEditDiff(card);
        addMessage("assistant", "", { type: "edit_diff_card", diffCard: card });
        }
        break;
      case "edit_chapter_auto_applied":
        finalizeLastRunningStep();
        {
        const card = {
          diff: d.diff,
          summary: d.summary,
          chapter_number: d.chapter_number,
          readonly: true,
        };
        setEditDiff(null);
        addMessage("assistant", "", { type: "edit_diff_card", diffCard: card });
        }
        setRunning(false);
        {
        const title = d?.title || `第${d.chapter_number}章`;
        const wordCount = Number.isFinite(d?.word_count) ? d.word_count : "未知";
        addMessage("assistant", `第${d.chapter_number}章「${title}」已自动优化并保存，共 ${wordCount} 字。`, {
          type: "chapter_edited",
        });
        }
        break;
      case "edit_chapter_accepted":
        setEditDiff(null);
        setRunning(false);
        addMessage("assistant", `第${d.chapter_number}章「${d.title}」修改已保存，共 ${d.word_count} 字。`, {
          type: "chapter_edited",
        });
        break;
      case "chapter_metadata_diff":
        addMessage("assistant", "", {
          type: "metadata_diff_card",
          metadataDiffCard: {
            chapter_number: d.chapter_number,
            summary: d.summary,
            key_plot_points: d.key_plot_points || [],
            foreshadows: d.foreshadows || [],
            diff: d.diff || {},
            diff_summary: d.diff_summary || {},
          },
        });
        break;
      case "chapter_metadata_generated":
        addMessage("assistant", "", {
          type: "chapter_meta_card",
          chapterMetaCard: {
            chapter_number: d.chapter_number,
            summary: d.summary,
            key_plot_points: d.key_plot_points || [],
            foreshadows_added: d.foreshadows_added || [],
          },
        });
        break;
      case "consistency_checked":
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

      case "outline_edit_diff":
        finalizeLastRunningStep();
        setOutlineDiff({
          diff: d.diff,
          summary: d.summary,
          message: d.message,
          operations: d.operations,
          readonly: !!d.readonly,
        });
        setRunning(false);
        break;
      case "character_edit_diff":
        setCharacterDiff({
          diff: d.diff,
          summary: d.summary,
          readonly: !!d.readonly,
        });
        setRunning(false);
        break;

      case "error":
        finalizeLastRunningStep();
        setAssistantDraft("");
        addMessage("system", `错误: ${d.message}`, { type: "error" });
        setRunning(false);
        break;
      default:
        break;
    }
  };

  const handleSend = () => {
    if (running || !input.trim()) return;

    const msg = input.trim();
    addMessage("user", msg);
    setInput("");

    const sid = activeSessionIdRef.current;
    if (!sid) {
      // Start new supervisor session
      connectSSE(`${API_BASE}/supervisor/start`, { message: msg, work_id: workId, auto_mode: autoMode });
    } else {
      // Resume existing session
      connectSSE(`${API_BASE}/supervisor/resume`, { session_id: sid, message: msg });
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleConfirmEdit = async (action, targetDiff = null) => {
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
      const data = await res.json();
      if (data.status === "accepted") {
        addMessage("assistant", `第${diffTarget.chapter_number}章修改已保存。`, { type: "chapter_edited" });
      } else {
        addMessage("assistant", `第${diffTarget.chapter_number}章修改已取消，正文保持不变。`, { type: "edit_cancelled" });
      }
      setEditDiff(null);
      setRunning(false);
    } catch (err) {
      addMessage("system", `确认失败: ${err.message}`, { type: "error" });
    } finally {
      setConfirming(false);
    }
  };

  const handleConfirmOutline = async (action) => {
    if (!sessionId || (!outlineDiff && !characterDiff) || confirming) return;
    setConfirming(true);
    try {
      const res = await authFetch(`${API_BASE}/supervisor/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          action,
        }),
      });
      const data = await res.json();
      if (data.status === "accepted") {
        addMessage("assistant", "大纲和角色修改已保存。", { type: "outline_edited" });
      } else {
        addMessage("assistant", "大纲和角色修改已取消，保持原样。", { type: "edit_cancelled" });
      }
      setOutlineDiff(null);
      setCharacterDiff(null);
      setRunning(false);
    } catch (err) {
      addMessage("system", `确认失败: ${err.message}`, { type: "error" });
    } finally {
      setConfirming(false);
    }
  };

  return (
    <main className="flex h-screen flex-col bg-white">
      {/* Top bar */}
      <header className="flex shrink-0 items-center justify-between border-b border-slate-200 px-4 py-2.5">
        <div className="flex items-center gap-3">
          <Button asChild variant="ghost" size="sm" className="h-7 px-2">
            <Link to="/dashboard">
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
          <div className="h-4 w-px bg-slate-200" />
          <Bot className="h-4 w-4 text-blue-500" />
          <span className="text-sm font-semibold text-slate-800">AI 写作助手</span>
          {workTitle && (
            <>
              <span className="text-xs text-slate-400">/</span>
              <span className="flex items-center gap-1 text-sm text-slate-600">
                <BookOpen className="h-3.5 w-3.5" />
                {workTitle}
              </span>
            </>
          )}
          {currentIntent && intentBadge(currentIntent)}
        </div>
        <div className="flex items-center gap-2">
          {!sessionId && (
            <button
              onClick={() => setAutoMode(!autoMode)}
              className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs transition-colors ${
                autoMode
                  ? "bg-amber-100 text-amber-700 hover:bg-amber-200"
                  : "bg-slate-100 text-slate-500 hover:bg-slate-200"
              }`}
              title={autoMode ? "自动模式：编辑直接生效" : "手动模式：编辑需要确认"}
            >
              <Zap className="h-3 w-3" />
              {autoMode ? "自动" : "手动"}
            </button>
          )}
          {sessionId && autoMode && !running && (
            <span className="flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[10px] text-amber-600">
              <Zap className="h-3 w-3" />
              自动模式
            </span>
          )}
          {running && (
            <span className="flex items-center gap-1.5 rounded-full bg-blue-50 px-2.5 py-1 text-xs text-blue-600">
              <Loader2 className="h-3 w-3 animate-spin" />
              {currentStage || "处理中"}
            </span>
          )}
          {sessionId && !running && (
            <Button variant="ghost" size="sm" className="h-7 text-xs text-slate-500" onClick={resetState}>
              新对话
            </Button>
          )}
        </div>
      </header>

      {/* Body */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: session sidebar */}
        <SessionSidebar
          workId={workId}
          type="supervisor"
          activeId={sessionId}
          onSelect={handleSelectSession}
          onNew={resetState}
          collapsed={!sessionSidebarOpen}
          onToggle={() => setSessionSidebarOpen(!sessionSidebarOpen)}
        />

        {/* Chat area */}
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-4 py-4">
            <div className="mx-auto max-w-3xl space-y-4">
              {/* Empty state */}
              {timeline.length === 0 && !running && (
                <div className="flex flex-col items-center justify-center py-20 text-center">
                  <div className="rounded-full bg-blue-100 p-4 mb-4">
                    <Sparkles className="h-8 w-8 text-blue-500" />
                  </div>
                  <h2 className="text-lg font-semibold text-slate-800">AI 写作助手</h2>
                  <p className="mt-2 max-w-md text-sm text-slate-500">
                    告诉我你想做什么，我会自动识别并执行：
                  </p>
                  <div className="mt-5 flex flex-wrap justify-center gap-2">
                    {[
                      { text: "帮我写一个科幻大纲", intent: "创建大纲" },
                      { text: "在主线3后加一个反派暗杀的支线", intent: "编辑大纲" },
                      { text: "写第1章", intent: "撰写章节" },
                      { text: "把第1章开头的环境描写改得更生动", intent: "修改章节" },
                    ].map((ex) => (
                      <button
                        key={ex.text}
                        onClick={() => {
                          setInput(ex.text);
                        }}
                        className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-left text-xs transition hover:border-blue-300 hover:bg-blue-50"
                      >
                        <span className="text-slate-700">{ex.text}</span>
                        <span className="ml-1.5 text-[10px] text-slate-400">{ex.intent}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Timeline: messages + steps interleaved by time */}
              {timeline.map((item) => {
                if (item.kind === "step") {
                  const showContent = item.status === "running" || (item.status === "done" && item.panelOpen);
                  return (
                    <div key={`s-${item.id}`} className="flex gap-2 justify-start pl-1">
                      <div className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center text-slate-300">
                        {item.status === "running" ? (
                          <Loader2 className="h-3 w-3 animate-spin text-slate-400" />
                        ) : (
                          <Check className="h-3 w-3 text-slate-300" />
                        )}
                      </div>
                      <div className="max-w-[min(100%,42rem)] flex-1 min-w-0 py-0.5">
                        <div
                          className={`text-[11px] font-normal leading-snug text-slate-400 select-none ${item.stream && item.stream.trim() ? "cursor-pointer hover:text-slate-600" : ""}`}
                          onClick={() => item.stream && item.stream.trim() && toggleStepPanel(item.id)}
                        >
                          {item.label}
                        </div>
                        {showContent && item.stream && item.stream.trim().length > 0 && (
                          <div
                            ref={(el) => {
                              if (el && item.status === "running") {
                                el.scrollTop = el.scrollHeight;
                              }
                            }}
                            className="mt-1 max-h-32 overflow-y-auto whitespace-pre-wrap break-words text-[10px] font-normal leading-relaxed text-slate-400"
                          >
                            {item.stream}
                            {item.status === "running" && (
                              <span className="inline-block h-2.5 w-px animate-pulse bg-slate-400 align-text-bottom" />
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                }

                // kind === "message"
                const msg = item;
                return (
                  <div key={`m-${item.id}`} className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                    {msg.role !== "user" && (
                      <div
                        className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${
                          msg.type === "error" ? "bg-red-100 text-red-500" : "bg-blue-100 text-blue-500"
                        }`}
                      >
                        {msg.type === "error" ? "!" : <Bot className="h-3.5 w-3.5" />}
                      </div>
                    )}
                    <div
                      className={`max-w-[80%] rounded-xl px-4 py-2.5 text-sm leading-relaxed ${
                        msg.role === "user"
                          ? "bg-blue-600 text-white"
                          : msg.type === "error"
                            ? "bg-red-50 text-red-700 border border-red-200"
                            : msg.type === "agent_phase"
                              ? "bg-slate-50 text-slate-800 border border-slate-200"
                              : "bg-slate-100 text-slate-800"
                      }`}
                    >
                      {msg.type === "patch_diff_card" ? (
                        <div className="space-y-2">
                          <div className="flex items-center justify-between">
                            <p className="text-sm text-slate-700">
                              章节局部修改
                              <span className="ml-2 text-xs text-slate-400">
                                {msg.patchDiffCard?.summary?.applied ?? 0} 处改动
                              </span>
                            </p>
                          </div>
                          <PatchDiffViewer
                            hunks={msg.patchDiffCard?.hunks ?? []}
                            summary={msg.patchDiffCard?.summary ?? {}}
                          />
                        </div>
                      ) : msg.type === "edit_diff_card" ? (
                        <div className="space-y-2">
                          <div className="flex items-center justify-between">
                            <p className="text-sm text-slate-700">
                              第{msg.diffCard?.chapter_number}章修改建议
                              <span className="ml-2 text-xs text-slate-400">
                                +{msg.diffCard?.summary?.lines_added ?? 0}行 / -{msg.diffCard?.summary?.lines_removed ?? 0}行
                              </span>
                            </p>
                          </div>
                          <DiffViewer diff={msg.diffCard?.diff ?? []} summary={msg.diffCard?.summary ?? {}} collapsed />
                          {msg.diffCard?.readonly ? (
                            <div className="text-xs text-slate-500">
                              已自动应用并保存，无需确认。
                            </div>
                          ) : (
                            <div className="flex items-center gap-2 justify-end">
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-8 px-3 text-xs text-slate-500 hover:text-red-600 hover:bg-red-50"
                                onClick={() => handleConfirmEdit("reject", msg.diffCard)}
                                disabled={confirming}
                              >
                                <X className="mr-1.5 h-3.5 w-3.5" />
                                拒绝
                              </Button>
                              <Button
                                size="sm"
                                className="h-8 px-3 text-xs bg-emerald-600 hover:bg-emerald-700 text-white"
                                onClick={() => handleConfirmEdit("accept", msg.diffCard)}
                                disabled={confirming}
                              >
                                {confirming ? (
                                  <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
                                ) : (
                                  <Check className="mr-1.5 h-3.5 w-3.5" />
                                )}
                                接受修改
                              </Button>
                            </div>
                          )}
                        </div>
                      ) : msg.type === "requirements_todolist" ? (
                        <div className="space-y-2">
                          <div className="flex items-center justify-between">
                            <p className="text-sm font-medium text-slate-700">需求任务清单</p>
                            <span
                              className={`rounded-full px-2 py-0.5 text-[10px] ${
                                msg.todoCard?.ready_to_execute
                                  ? "bg-emerald-100 text-emerald-700"
                                  : "bg-amber-100 text-amber-700"
                              }`}
                            >
                              {msg.todoCard?.ready_to_execute ? "可执行" : "待澄清"}
                            </span>
                          </div>
                          {msg.todoCard?.intent_summary && (
                            <p className="text-xs text-slate-600">
                              目标：{msg.todoCard.intent_summary}
                            </p>
                          )}
                          {(msg.todoCard?.todolist || []).length > 0 ? (
                            <div className="space-y-2">
                              {(msg.todoCard.todolist || []).map((t, idx) => {
                                const statusIcon = {
                                  pending: "○",
                                  in_progress: "◑",
                                  completed: "✓",
                                  skipped: "⊘",
                                  failed: "✗",
                                }[t.status || "pending"] || "○";
                                const statusColor = {
                                  pending: "text-slate-400",
                                  in_progress: "text-blue-500",
                                  completed: "text-emerald-500",
                                  skipped: "text-slate-300",
                                  failed: "text-red-500",
                                }[t.status || "pending"] || "text-slate-400";
                                const borderColor = {
                                  completed: "border-emerald-200 bg-emerald-50/50",
                                  failed: "border-red-200 bg-red-50/50",
                                  in_progress: "border-blue-200 bg-blue-50/50",
                                }[t.status || "pending"] || "border-slate-200 bg-white";
                                return (
                                <div key={`${t.db_id || t.task_id || "T"}-${idx}`} className={`rounded-lg border p-2.5 ${borderColor}`}>
                                  <div className="flex items-center gap-2 text-xs">
                                    <span className={`text-sm ${statusColor}`}>{statusIcon}</span>
                                    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-600">{t.task_id || `T${idx + 1}`}</span>
                                    <span className={`font-medium ${t.status === "completed" ? "text-slate-400 line-through" : "text-slate-700"}`}>{t.task || "未命名任务"}</span>
                                  </div>
                                  <div className="mt-1 space-y-1 text-[11px] text-slate-500">
                                    <p>负责人：{t.owner || "supervisor"}</p>
                                    <p>状态：{t.status || "pending"}</p>
                                    {Array.isArray(t.depends_on) && t.depends_on.length > 0 && (
                                      <p>依赖：{t.depends_on.join(", ")}</p>
                                    )}
                                    {t.done_criteria && <p>验收：{t.done_criteria}</p>}
                                    {t.result_summary && <p className="text-emerald-600">结果：{t.result_summary}</p>}
                                  </div>
                                </div>
                                );
                              })}
                            </div>
                          ) : (
                            <p className="text-xs text-slate-500">暂无任务项。</p>
                          )}
                        </div>
                      ) : msg.type === "outline_diff_card" ? (
                        <div className="space-y-2">
                          <div className="flex items-center justify-between">
                            <p className="text-sm text-slate-700">
                              大纲变更建议
                              <span className="ml-2 text-xs text-slate-400">
                                +{msg.outlineDiffCard?.summary?.total_added ?? 0} / ~{msg.outlineDiffCard?.summary?.total_modified ?? 0} / -{msg.outlineDiffCard?.summary?.total_removed ?? 0}
                              </span>
                            </p>
                          </div>
                          <OutlineDiffViewer diff={msg.outlineDiffCard?.diff ?? {}} summary={msg.outlineDiffCard?.summary ?? {}} collapsed />
                        </div>
                      ) : msg.type === "character_diff_card" ? (
                        <div className="space-y-2">
                          <div className="flex items-center justify-between">
                            <p className="text-sm text-slate-700">
                              角色变更建议
                              <span className="ml-2 text-xs text-slate-400">
                                +{msg.characterDiffCard?.summary?.total_added ?? 0} / ~{msg.characterDiffCard?.summary?.total_modified ?? 0} / -{msg.characterDiffCard?.summary?.total_removed ?? 0}
                              </span>
                            </p>
                          </div>
                          <CharacterDiffViewer diff={msg.characterDiffCard?.diff ?? {}} summary={msg.characterDiffCard?.summary ?? {}} collapsed />
                        </div>
                      ) : msg.type === "metadata_diff_card" ? (
                        <div className="space-y-2">
                          <div className="flex items-center justify-between">
                            <p className="text-sm text-slate-700">
                              第{msg.metadataDiffCard?.chapter_number}章元数据变更
                              <span className="ml-2 text-xs text-slate-400">
                                +{msg.metadataDiffCard?.diff_summary?.total_added ?? 0} / ~{msg.metadataDiffCard?.diff_summary?.total_modified ?? 0} / -{msg.metadataDiffCard?.diff_summary?.total_removed ?? 0}
                              </span>
                            </p>
                          </div>
                          <MetadataDiffViewer diff={msg.metadataDiffCard?.diff ?? {}} summary={msg.metadataDiffCard?.diff_summary ?? {}} collapsed />
                        </div>
                      ) : msg.type === "chapter_meta_card" ? (
                        <div className="space-y-2">
                          <p className="text-sm font-medium text-slate-700">章节结构元数据（第{msg.chapterMetaCard?.chapter_number}章）</p>
                          <p className="text-xs text-slate-600 whitespace-pre-wrap">{msg.chapterMetaCard?.summary || "无摘要"}</p>
                          <div className="text-xs text-slate-600">
                            <p className="font-medium text-slate-700">关键剧情点</p>
                            {(msg.chapterMetaCard?.key_plot_points || []).length > 0 ? (
                              <ul className="list-disc pl-4">
                                {(msg.chapterMetaCard?.key_plot_points || []).map((p, idx) => <li key={`kp-${idx}`}>{p}</li>)}
                              </ul>
                            ) : (
                              <p>无</p>
                            )}
                          </div>
                        </div>
                      ) : msg.type === "consistency_report_card" ? (
                        <div className="space-y-1">
                          <p className="text-sm font-medium text-slate-700">一致性检查（第{msg.consistencyReportCard?.chapter_number}章）</p>
                          <p className="text-xs text-slate-600">状态：{msg.consistencyReportCard?.consistency_status || "aligned"}</p>
                          <p className="text-xs text-slate-600">决策：{msg.consistencyReportCard?.decision || "none"}</p>
                          <p className="text-xs text-slate-600 whitespace-pre-wrap">{msg.consistencyReportCard?.reason || ""}</p>
                        </div>
                      ) : msg.role === "user" ? (
                        <p>{msg.content}</p>
                      ) : (
                        <>
                          {msg.type === "agent_phase" && msg.title && (
                            <div className="mb-1.5 flex items-center gap-1.5 border-b border-slate-200/80 pb-1 text-xs font-medium text-slate-500">
                              <PenLine className="h-3 w-3 shrink-0 text-violet-500" />
                              {msg.title}
                            </div>
                          )}
                          <Markdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                            {msg.content}
                          </Markdown>
                        </>
                      )}
                      {msg.workId && (
                        <div className="mt-2 pt-2 border-t border-slate-200/50">
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 text-[10px] text-blue-600"
                            onClick={() => navigate(`/works/${msg.workId}`)}
                          >
                            查看作品
                          </Button>
                        </div>
                      )}
                    </div>
                    {msg.role === "user" && (
                      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-200 text-slate-500">
                        <User className="h-3.5 w-3.5" />
                      </div>
                    )}
                  </div>
                );
              })}

              {(outlineDiff || characterDiff) && (
                <div className="flex gap-3 justify-start">
                  <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-violet-100 text-violet-600">
                    <Bot className="h-3.5 w-3.5" />
                  </div>
                  <div className="max-w-[85%] space-y-2">
                    {outlineDiff && (
                      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
                        <div className="px-4 py-2.5 border-b border-slate-100 flex items-center justify-between">
                          <p className="text-sm text-slate-700">
                            大纲变更建议
                            <span className="ml-2 text-xs text-slate-400">
                              +{outlineDiff.summary?.total_added ?? 0} / ~{outlineDiff.summary?.total_modified ?? 0} / -{outlineDiff.summary?.total_removed ?? 0}
                            </span>
                          </p>
                        </div>
                        <div className="px-2 py-2">
                          <OutlineDiffViewer diff={outlineDiff.diff} summary={outlineDiff.summary ?? {}} collapsed />
                        </div>
                      </div>
                    )}
                    {characterDiff && (
                      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
                        <div className="px-4 py-2.5 border-b border-slate-100 flex items-center justify-between">
                          <p className="text-sm text-slate-700">
                            角色变更建议
                            <span className="ml-2 text-xs text-slate-400">
                              +{characterDiff.summary?.total_added ?? 0} / ~{characterDiff.summary?.total_modified ?? 0} / -{characterDiff.summary?.total_removed ?? 0}
                            </span>
                          </p>
                        </div>
                        <div className="px-2 py-2">
                          <CharacterDiffViewer diff={characterDiff.diff} summary={characterDiff.summary ?? {}} collapsed />
                        </div>
                      </div>
                    )}
                    {outlineDiff?.readonly ? (
                      <div className="text-xs text-slate-500 text-right">
                        已自动应用并保存，无需确认。
                      </div>
                    ) : (
                      <div className="flex items-center gap-2 justify-end">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-8 px-3 text-xs text-slate-500 hover:text-red-600 hover:bg-red-50"
                          onClick={() => handleConfirmOutline("reject")}
                          disabled={confirming}
                        >
                          <X className="mr-1.5 h-3.5 w-3.5" />
                          拒绝
                        </Button>
                        <Button
                          size="sm"
                          className="h-8 px-3 text-xs bg-emerald-600 hover:bg-emerald-700 text-white"
                          onClick={() => handleConfirmOutline("accept")}
                          disabled={confirming}
                        >
                          {confirming ? (
                            <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
                          ) : (
                            <Check className="mr-1.5 h-3.5 w-3.5" />
                          )}
                          接受修改
                        </Button>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {assistantDraft && (
                <div className="flex gap-3 justify-start">
                  <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-100 text-blue-500">
                    <Bot className="h-3.5 w-3.5" />
                  </div>
                  <div className="max-w-[85%] rounded-xl bg-slate-100 px-4 py-2.5 text-sm leading-relaxed text-slate-800">
                    <Markdown remarkPlugins={[remarkGfm]}>{assistantDraft}</Markdown>
                    {running && (
                      <span className="inline-block h-2.5 w-px animate-pulse bg-slate-400 align-text-bottom ml-0.5" />
                    )}
                  </div>
                </div>
              )}

              {running && !timeline.some((item) => item.kind === "step" && item.status === "running") && !editDiff && !outlineDiff && !characterDiff && (
                <div className="flex gap-3 justify-start">
                  <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-100 text-blue-500 animate-pulse">
                    <Bot className="h-3.5 w-3.5" />
                  </div>
                  <div className="rounded-xl bg-slate-100 px-4 py-2.5 text-sm text-slate-500">连接中…</div>
                </div>
              )}

              <div ref={chatEndRef} />
            </div>
          </div>

          {/* Input area */}
          <div className="shrink-0 px-4 py-3">
            <div className="mx-auto flex max-w-3xl items-end gap-2 pr-2">
              <Textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder={running ? "Agent 运行中..." : "输入指令... (如「修改大纲」「写第1章」「修改第1章的...」)"}
                className="min-h-[48px] max-h-[140px] resize-none text-sm"
                rows={1}
                disabled={running}
                onKeyDown={handleKeyDown}
              />
              <Button
                size="icon"
                className="h-11 w-11 shrink-0 rounded-full"
                disabled={running || !input.trim()}
                onClick={handleSend}
                aria-label="发送消息"
              >
                {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
