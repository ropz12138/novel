import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  Bot,
  BookOpen,
  Calendar,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  FileText,
  LayoutList,
  Loader2,
  PenLine,
  Plus,
  Save,
  Send,
  Sparkles,
  Tag as TagIcon,
  Trash2,
  Users,
  X,
} from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { DiffViewer } from "../components/agent/DiffViewer";
import { extractChapterNumbers } from "../lib/chapterOutline";
import { parsePositiveChapterInt } from "../lib/outlineChapterInput";
import { sortTimelineNodes } from "../lib/outlineTimelineSort";
import { sessionApi } from "../lib/api";

const API_BASE = "http://127.0.0.1:9001/api";

/* ────────────────────────── Editable text helper ────────────────────────── */

function EditableText({ value, onSave, className = "", multiline = false, editable = true }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const ref = useRef(null);

  useEffect(() => {
    if (editing && ref.current) {
      ref.current.focus();
      ref.current.select();
    }
  }, [editing]);

  const commit = () => {
    const trimmed = draft.trim();
    if (trimmed && trimmed !== value) {
      onSave(trimmed);
    } else {
      setDraft(value);
    }
    setEditing(false);
  };

  if (!editing) {
    return (
      <span
        className={`rounded px-1 transition-colors ${editable ? "cursor-pointer hover:bg-slate-100" : "cursor-default"} ${className}`}
        onClick={() => {
          if (!editable) return;
          setDraft(value);
          setEditing(true);
        }}
        title={editable ? "点击编辑" : undefined}
      >
        {value}
      </span>
    );
  }

  if (multiline) {
    return (
      <Textarea
        ref={ref}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            commit();
          }
          if (e.key === "Escape") {
            setDraft(value);
            setEditing(false);
          }
        }}
        className={`min-h-[60px] ${className}`}
      />
    );
  }

  return (
    <Input
      ref={ref}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
        if (e.key === "Escape") {
          setDraft(value);
          setEditing(false);
        }
      }}
      className={className}
    />
  );
}

/* ─────────────────────────── Branch Card ─────────────────────────────── */

/** 支线卡片最大高度（约 13rem）；超出在收起态用省略号，展开/编辑时在框内滚动 */
const BRANCH_CARD_MAX_H = "max-h-52";

function BranchCard({ branch, onUpdate, onDelete, editing = false, onToggleEdit }) {
  const [expanded, setExpanded] = useState(false);
  const isOpen = editing || expanded;
  const isLeft = branch.side === "left";
  const borderColor = isLeft ? "border-amber-300" : "border-violet-300";
  const bgColor = isLeft ? "bg-amber-50" : "bg-violet-50";
  const badgeColor = isLeft ? "bg-amber-100 text-amber-800" : "bg-violet-100 text-violet-800";

  return (
    <article
      onClick={(e) => {
        if (editing) return;
        if (e.target.closest("button, input, textarea")) return;
        setExpanded((v) => !v);
      }}
      className={`group flex w-[220px] min-h-0 flex-col overflow-hidden rounded-xl border ${borderColor} ${BRANCH_CARD_MAX_H} ${editing ? "border-emerald-400 bg-white" : `${bgColor} cursor-pointer`} px-3 py-2 shadow-sm transition-colors`}
    >
      <div className="mb-1 flex shrink-0 items-center justify-between">
        <span className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold ${badgeColor}`}>支线</span>
        <div className="flex items-center gap-0.5">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onToggleEdit();
            }}
            className={`rounded p-0.5 transition-colors ${editing ? "text-emerald-600 hover:bg-emerald-100" : "text-slate-500 hover:bg-slate-100 opacity-80 md:opacity-0 md:group-hover:opacity-100"}`}
            title={editing ? "完成编辑" : "编辑支线"}
          >
            {editing ? <Check className="h-3 w-3" /> : <PenLine className="h-3 w-3" />}
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
            className="rounded p-0.5 text-slate-500 opacity-80 hover:bg-red-50 hover:text-red-500 md:opacity-0 md:group-hover:opacity-100"
            title="删除支线"
          >
            <Trash2 className="h-3 w-3" />
          </button>
        </div>
      </div>
      <div
        className={`flex min-h-0 flex-1 flex-col ${isOpen ? "overflow-y-auto overflow-x-hidden" : "overflow-hidden"}`}
      >
        <EditableText
          value={branch.name}
          onSave={(val) => onUpdate("name", val)}
          className={`shrink-0 text-[11px] font-medium leading-4 text-slate-800 ${editing ? "" : isOpen ? "" : "line-clamp-2 break-words"}`}
          editable={editing}
        />
        <div className="mt-1 min-h-0 flex-1 text-[10px] leading-4 text-slate-600">
          {branch.summary ? (
            <EditableText
              value={branch.summary}
              onSave={(val) => onUpdate("summary", val)}
              className={`block break-words text-[10px] leading-4 text-slate-600 ${editing ? "whitespace-pre-wrap" : isOpen ? "" : "line-clamp-4"}`}
              multiline
              editable={editing}
            />
          ) : (
            <span
              className={`block break-words text-[10px] leading-4 ${editing ? "cursor-pointer rounded px-1 hover:bg-slate-100" : isOpen ? "text-slate-400" : "line-clamp-4 text-slate-400"}`}
            >
              {editing ? "点击添加支线摘要" : "（暂无支线摘要）"}
            </span>
          )}
        </div>
      </div>
      <p className="mt-1 shrink-0 text-[10px] text-slate-500">
        第{branch.chapter_start}-{branch.chapter_end}章
      </p>
    </article>
  );
}

/* ─────────────────────────── Outline Tree ─────────────────────────────── */

function InlineTree({ tree, onUpdateNode, onDeleteNode, onAddBranch }) {
  const timeline = tree?.timeline || [];
  const branches = tree?.branches || [];

  const [editingNodeId, setEditingNodeId] = useState(null);
  const [editingBranchId, setEditingBranchId] = useState(null);
  const [expandedTimelineIds, setExpandedTimelineIds] = useState(() => new Set());
  /** 相邻主线卡片底→顶间距（px），在 items-center + 支线撑高行高时无法用固定 rem 表示 */
  const [mainSpinePx, setMainSpinePx] = useState({});
  const timelineColumnRef = useRef(null);
  const mainArticleRef = useRef({});

  const toggleTimelineExpanded = (id) => {
    setExpandedTimelineIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const orderedTimeline = useMemo(() => sortTimelineNodes(timeline || []), [timeline]);

  const expandedKey = useMemo(() => Array.from(expandedTimelineIds).sort().join(","), [expandedTimelineIds]);

  useLayoutEffect(() => {
    if (orderedTimeline.length < 2) {
      setMainSpinePx({});
      return;
    }

    const measure = () => {
      const next = {};
      for (let i = 0; i < orderedTimeline.length - 1; i++) {
        const a = mainArticleRef.current[i];
        const b = mainArticleRef.current[i + 1];
        if (a && b) {
          const ra = a.getBoundingClientRect();
          const rb = b.getBoundingClientRect();
          next[i] = Math.max(12, Math.round(rb.top - ra.bottom));
        }
      }
      setMainSpinePx((prev) => {
        const pk = Object.keys(prev);
        const nk = Object.keys(next);
        if (pk.length !== nk.length) return next;
        for (const k of nk) {
          if (prev[k] !== next[k]) return next;
        }
        return prev;
      });
    };

    measure();
    const ro = new ResizeObserver(measure);
    if (timelineColumnRef.current) ro.observe(timelineColumnRef.current);
    for (let i = 0; i < orderedTimeline.length; i++) {
      const el = mainArticleRef.current[i];
      if (el) ro.observe(el);
    }
    window.addEventListener("resize", measure);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [orderedTimeline, branches, editingNodeId, editingBranchId, expandedKey]);

  if (!timeline.length) {
    return <p className="text-sm text-slate-600">暂无大纲数据。</p>;
  }

  return (
    <div className="relative mx-auto w-full max-w-[1220px] rounded-2xl border border-slate-200 bg-white px-10 pb-4 pt-6 shadow-[0_18px_45px_rgba(15,23,42,0.08)]">
      <div className="relative z-[2] mt-10">
        <div ref={timelineColumnRef} className="relative z-[1] flex flex-col gap-4">
          {orderedTimeline.map((node, idx) => {
            const leftBranches = branches.filter((s) => s.attach_to === node.id && s.side === "left");
            const rightBranches = branches.filter((s) => s.attach_to === node.id && s.side === "right");
            const mainOpen = editingNodeId === node.id || expandedTimelineIds.has(node.id);
            const hasNext = idx < orderedTimeline.length - 1;

            return (
              <section key={node.id} className="group/row relative z-[1] flex min-h-[88px] items-center">
                <div className="flex min-w-0 flex-1 items-center">
                  {leftBranches.length > 0 && (
                    <>
                      <div className="flex shrink-0 flex-col items-end gap-1">
                        {leftBranches.map((b) => (
                          <BranchCard
                            key={b.id}
                            branch={b}
                            onUpdate={(field, val) => onUpdateNode(b.id, { [field]: val })}
                            onDelete={() => onDeleteNode(b.id)}
                            editing={editingBranchId === b.id}
                            onToggleEdit={() => setEditingBranchId(editingBranchId === b.id ? null : b.id)}
                          />
                        ))}
                      </div>
                      <span className="block h-[2px] flex-1 bg-slate-200" />
                    </>
                  )}
                </div>

                <div className="relative flex shrink-0 items-center">
                  <div className="relative shrink-0">
                  <button
                    type="button"
                    onClick={() => onAddBranch(node.id, "left")}
                    className="group/addbranch absolute left-0 top-1/2 z-[5] flex h-[22px] w-[11px] -translate-x-full -translate-y-1/2 items-center justify-center overflow-hidden rounded-l-full border border-amber-300 bg-amber-50 text-amber-600 shadow-sm transition-[width,transform,border-radius,background-color] duration-200 ease-out hover:w-[22px] hover:-translate-x-1/2 hover:rounded-full hover:bg-amber-200"
                    title="添加左侧支线"
                  >
                    <Plus className="h-3 w-3 shrink-0 opacity-0 scale-75 transition-[opacity,transform] duration-150 ease-out group-hover/addbranch:opacity-100 group-hover/addbranch:scale-100" />
                  </button>

                  <article
                    ref={(el) => {
                      if (el) mainArticleRef.current[idx] = el;
                      else delete mainArticleRef.current[idx];
                    }}
                    onClick={(e) => {
                      if (editingNodeId === node.id) return;
                      if (e.target.closest("button, input, textarea")) return;
                      toggleTimelineExpanded(node.id);
                    }}
                    className={`group relative z-[3] flex w-[260px] flex-col rounded-xl border-2 px-3 py-2 shadow-[0_8px_20px_rgba(15,23,42,0.08)] transition-colors ${editingNodeId === node.id ? "border-emerald-500 bg-emerald-50/30" : "cursor-pointer border-blue-600 bg-white"}`}
                  >
                    <div className="mb-1 flex shrink-0 items-center justify-between">
                      <span className="inline-block rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-semibold text-blue-700">
                        主线 {String(idx + 1).padStart(2, "0")}
                      </span>
                      <div className="flex items-center gap-0.5">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setEditingNodeId(editingNodeId === node.id ? null : node.id);
                          }}
                          className={`block rounded p-0.5 transition-colors ${editingNodeId === node.id ? "text-emerald-600 hover:bg-emerald-100" : "text-slate-500 opacity-80 hover:bg-slate-100 md:opacity-0 md:group-hover:opacity-100"}`}
                          title={editingNodeId === node.id ? "完成编辑" : "编辑节点"}
                        >
                          {editingNodeId === node.id ? <Check className="h-3 w-3" /> : <PenLine className="h-3 w-3" />}
                        </button>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onDeleteNode(node.id);
                          }}
                          className="block rounded p-0.5 text-slate-500 opacity-80 hover:bg-red-50 hover:text-red-500 md:opacity-0 md:group-hover:opacity-100"
                          title="删除节点"
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      </div>
                    </div>
                    <div className="min-h-0 text-[11px] font-semibold leading-[18px] text-slate-800">
                      <EditableText
                        value={node.development_node}
                        onSave={(val) => onUpdateNode(node.id, { development_node: val })}
                        className={`block break-words text-[11px] font-semibold leading-4 text-slate-800 ${editingNodeId === node.id ? "whitespace-pre-wrap" : mainOpen ? "" : "line-clamp-2"}`}
                        multiline
                        editable={editingNodeId === node.id}
                      />
                    </div>
                    <div className="mt-1 min-h-0 text-[10px] leading-4 text-slate-600">
                      {node.summary || (typeof node.mainline === "string" && node.mainline) ? (
                        <EditableText
                          value={node.summary || (typeof node.mainline === "string" ? node.mainline : "")}
                          onSave={(val) => onUpdateNode(node.id, { summary: val })}
                          className={`block break-words text-[10px] leading-4 text-slate-600 ${editingNodeId === node.id ? "whitespace-pre-wrap" : mainOpen ? "" : "line-clamp-2"}`}
                          multiline
                          editable={editingNodeId === node.id}
                        />
                      ) : (
                        <span
                          className={`block whitespace-pre-wrap break-words text-[10px] leading-4 ${editingNodeId === node.id ? "cursor-pointer rounded px-1 text-slate-400 hover:bg-slate-100" : mainOpen ? "text-slate-400" : "line-clamp-2 text-slate-400"}`}
                        >
                          {editingNodeId === node.id ? "点击添加主线说明" : "（暂无主线说明）"}
                        </span>
                      )}
                    </div>
                    <div
                      className={`mt-1 flex shrink-0 items-center gap-1 text-[10px] text-slate-500 ${mainOpen || editingNodeId === node.id ? "min-w-0 flex-wrap" : "min-w-0 flex-nowrap"}`}
                    >
                      <EditableText
                        value={node.time_node}
                        onSave={(val) => onUpdateNode(node.id, { time_node: val })}
                        className={`min-w-0 text-[10px] text-slate-500 ${mainOpen || editingNodeId === node.id ? "" : "block flex-1 truncate"}`}
                        editable={editingNodeId === node.id}
                      />
                      <span className="shrink-0">· 第</span>
                      <EditableText
                        value={`${node.chapter_start}`}
                        onSave={(val) => {
                          const n = parsePositiveChapterInt(val);
                          if (n == null) return;
                          const end = Number(node.chapter_end);
                          onUpdateNode(node.id, { chapter_start: n, chapter_end: Number.isFinite(end) && end < n ? n : node.chapter_end });
                        }}
                        className="w-8 shrink-0 text-[10px] text-slate-500"
                        editable={editingNodeId === node.id}
                      />
                      <span className="shrink-0">-</span>
                      <EditableText
                        value={`${node.chapter_end}`}
                        onSave={(val) => {
                          const n = parsePositiveChapterInt(val);
                          if (n == null) return;
                          const start = Number(node.chapter_start);
                          if (Number.isFinite(start) && n < start) return;
                          onUpdateNode(node.id, { chapter_end: n });
                        }}
                        className="w-8 shrink-0 text-[10px] text-slate-500"
                        editable={editingNodeId === node.id}
                      />
                      <span className="shrink-0">章</span>
                    </div>
                  </article>

                  <button
                    type="button"
                    onClick={() => onAddBranch(node.id, "right")}
                    className="group/addbranch absolute right-0 top-1/2 z-[5] flex h-[22px] w-[11px] translate-x-full -translate-y-1/2 items-center justify-center overflow-hidden rounded-r-full border border-violet-300 bg-violet-50 text-violet-600 shadow-sm transition-[width,transform,border-radius,background-color] duration-200 ease-out hover:w-[22px] hover:translate-x-1/2 hover:rounded-full hover:bg-violet-200"
                    title="添加右侧支线"
                  >
                    <Plus className="h-3 w-3 shrink-0 opacity-0 scale-75 transition-[opacity,transform] duration-150 ease-out group-hover/addbranch:opacity-100 group-hover/addbranch:scale-100" />
                  </button>
                  </div>

                  {hasNext ? (
                    <div className="pointer-events-none absolute left-1/2 top-full z-0 -translate-x-1/2" aria-hidden>
                      <div
                        className="w-1 shrink-0 rounded-b-sm rounded-t-none bg-gradient-to-b from-blue-600 to-violet-600 shadow-sm"
                        style={{ height: `${mainSpinePx[idx] ?? 56}px` }}
                      />
                    </div>
                  ) : null}
                </div>

                <div className="flex min-w-0 flex-1 items-center">
                  {rightBranches.length > 0 && (
                    <>
                      <span className="block h-[2px] flex-1 bg-slate-200" />
                      <div className="flex shrink-0 flex-col items-start gap-1">
                        {rightBranches.map((b) => (
                          <BranchCard
                            key={b.id}
                            branch={b}
                            onUpdate={(field, val) => onUpdateNode(b.id, { [field]: val })}
                            onDelete={() => onDeleteNode(b.id)}
                            editing={editingBranchId === b.id}
                            onToggleEdit={() => setEditingBranchId(editingBranchId === b.id ? null : b.id)}
                          />
                        ))}
                      </div>
                    </>
                  )}
                </div>
              </section>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────── Supervisor Chat Panel ──────────────────────── */

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
};

function formatOutlineProgress(d) {
  if (!d?.section || !d?.node) return "";
  const n = d.node;
  if (d.section === "story") return `📘 作品：${n.title || "未命名"}｜${n.genre || "未分类"}｜${n.volume || ""}\n`;
  if (d.section === "timeline") return `🧭 主线：${n.development_node || ""}｜${n.summary || n.time_node || ""}\n`;
  if (d.section === "branches") return `🌿 支线：${n.name || ""} - ${n.summary || ""}\n`;
  if (d.section === "foreshadowing") return `🪝 伏笔：${n.content || ""}\n`;
  return "";
}

/** 执行过程一步：独立气泡 + 可选小流式区（结束后收起） */
function SupervisorChatPanel({ workId, onOutlineUpdated, onChapterUpdated }) {
  const [timeline, setTimeline] = useState([]);
  const [input, setInput] = useState("");
  const [running, setRunning] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const activeSessionIdRef = useRef(null);
  /** 当前正在流式累加的文字，冻结后变为 timeline 中的 assistant 气泡 */
  const [assistantDraft, setAssistantDraft] = useState("");
  const timelineIdRef = useRef(0);
  const [editDiff, setEditDiff] = useState(null); // { diff, summary, new_content, chapter_number, readonly }
  const [confirming, setConfirming] = useState(false);
  const bottomRef = useRef(null);
  const sseRef = useRef(null);
  const assistantDraftRef = useRef("");

  // 会话列表
  const [sessions, setSessions] = useState([]);
  const [sessionListOpen, setSessionListOpen] = useState(false);
  const dropdownRef = useRef(null);

  const syncSessionId = (id) => {
    activeSessionIdRef.current = id;
    setSessionId(id);
  };

  // 加载会话列表
  const loadSessions = async () => {
    try {
      const list = await sessionApi.listSupervisor(workId);
      setSessions(list || []);
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    if (workId) loadSessions();
  }, [workId]);

  // 点击外部关闭下拉
  useEffect(() => {
    const handleClick = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setSessionListOpen(false);
      }
    };
    if (sessionListOpen) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [sessionListOpen]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [timeline, assistantDraft, editDiff, running]);

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

  const addMessage = (role, content, meta = {}) => {
    const id = ++timelineIdRef.current;
    setTimeline((prev) => [...prev, { kind: "message", id, role, content, ...meta, timestamp: Date.now() }]);
  };

  // 冻结当前 assistantDraft 为一个独立的 assistant 气泡
  const freezeDraft = () => {
    const draft = assistantDraftRef.current;
    if (draft && draft.trim()) {
      const id = ++timelineIdRef.current;
      setTimeline((prev) => [...prev, { kind: "message", id, role: "assistant", content: draft, timestamp: Date.now() }]);
    }
    setAssistantDraft("");
    assistantDraftRef.current = "";
  };

  // 选择已有会话
  const handleSelectSession = async (session) => {
    if (running) return;
    // 重置状态
    setTimeline([]);
    setInput("");
    setAssistantDraft("");
    setEditDiff(null);
    setConfirming(false);
    timelineIdRef.current = 0;

    syncSessionId(session.id);
    setSessionListOpen(false);

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

            return {
              kind: "message",
              id,
              role: m.role,
              content: m.content,
              type: m.meta?.type,
              title: m.meta?.title,
              diffCard: m.meta?.diffCard,
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

  // 新建会话
  const handleNewSession = () => {
    if (running) return;
    setTimeline([]);
    setInput("");
    syncSessionId(null);
    setAssistantDraft("");
    setEditDiff(null);
    setConfirming(false);
    timelineIdRef.current = 0;
    setSessionListOpen(false);
  };

  // 删除会话
  const handleDeleteSession = async (id) => {
    if (running) return;
    if (!confirm("确定删除这个对话？")) return;
    try {
      await sessionApi.deleteSupervisor(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (sessionId === id) {
        handleNewSession();
      }
    } catch {
      // ignore
    }
  };

  // 当前会话标题
  const currentSessionTitle = useMemo(() => {
    if (!sessionId) return "新对话";
    const s = sessions.find((s) => s.id === sessionId);
    return s?.title || "新对话";
  }, [sessionId, sessions]);

  const connectSSE = (url, body) => {
    setRunning(true);
    setAssistantDraft("");
    timelineIdRef.current = 0;

    const ctl = new AbortController();
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: ctl.signal,
    })
      .then(async (res) => {
        if (!res.ok) {
          let msg = `HTTP ${res.status}`;
          try { const e = await res.json(); msg = e.detail || e.message || msg; } catch { /* ignore */ }
          setRunning(false);
          addMessage("system", `错误: ${msg}`, { type: "error" });
          return;
        }
        if (!res.body) { setRunning(false); return; }
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
              if (ln.startsWith("event: ")) ev = ln.slice(7).trim();
              else if (ln.startsWith("data: ")) {
                try { onSSE(ev, JSON.parse(ln.slice(6))); } catch { /* ignore */ }
              }
            }
          }
          setRunning(false);
        })().catch(() => setRunning(false));
      })
      .catch((e) => {
        setRunning(false);
        if (e?.name !== "AbortError") addMessage("system", `网络错误: ${e?.message || "无法连接"}`, { type: "error" });
      });
    sseRef.current = { close: () => ctl.abort() };
  };

  const onSSE = (ev, d) => {
    switch (ev) {
      case "session_created":
        syncSessionId(d.session_id);
        loadSessions();
        break;
      case "tool_calls": {
        // 冻结当前 draft 为独立气泡
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
        setRunning(false);
        break;
      }
      case "stage_start": {
        const label = d.label || d.stage || "进行中";
        // 如果是新的 thinking/tool_calling 阶段，先冻结当前 draft
        if (d.stage === "thinking" || d.stage === "tool_calling") {
          freezeDraft();
        }
        pushExecStep(label);
        break;
      }
      case "outline_stream":
        break;
      case "outline_status":
        if (d?.message) appendLastRunningStream(`${d.message}\n`);
        break;
      case "outline_tree_progress": {
        const line = formatOutlineProgress(d);
        if (line) appendLastRunningStream(line);
        break;
      }
      case "outline_done": {
        finalizeLastRunningStep();
        if (d.work_id && onOutlineUpdated) {
          fetch(`${API_BASE}/works/${d.work_id}`)
            .then((r) => r.json())
            .then((w) => {
              if (w.outline_tree) onOutlineUpdated(w.outline_tree);
            })
            .catch(() => {});
        }
        addMessage("assistant", `已创建作品「${d.title}」的大纲。`, { type: "outline_created" });
        break;
      }
      case "outline_edit_done":
        finalizeLastRunningStep();
        addMessage("assistant", d.message || "大纲已编辑。", { type: "outline_edited" });
        if (workId) {
          fetch(`${API_BASE}/works/${workId}`)
            .then((r) => r.json())
            .then((w) => {
              if (w.outline_tree) onOutlineUpdated(w.outline_tree);
            })
            .catch(() => {});
        }
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
      case "saved":
        finalizeLastRunningStep();
        addMessage("assistant", `第${d.chapter_number}章「${d.title}」已保存，共 ${d.word_count} 字。`, { type: "chapter_saved" });
        if (onChapterUpdated) onChapterUpdated(d.chapter_number);
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
        addMessage("assistant", `第${d.chapter_number}章「${d.title}」已自动优化并保存，共 ${d.word_count} 字。`, { type: "chapter_edited" });
        if (onChapterUpdated) onChapterUpdated(d.chapter_number);
        break;
      case "edit_chapter_accepted":
        setEditDiff(null);
        setRunning(false);
        addMessage("assistant", `第${d.chapter_number}章「${d.title}」修改已保存，共 ${d.word_count} 字。`, { type: "chapter_edited" });
        if (onChapterUpdated) onChapterUpdated(d.chapter_number);
        break;
      case "error":
        finalizeLastRunningStep();
        setAssistantDraft("");
        addMessage("system", `错误: ${d.message}`, { type: "error" });
        setRunning(false);
        break;
      case "characters_updated":
        if (d?.message) pushExecStepDone(d.message);
        break;
      case "query_result":
        pushExecStepDone(`查询 ${d.source || "资料"}: ${String(d.summary || "").slice(0, 100)}`);
        break;
      case "title_proposed":
        if (d?.title) pushExecStepDone(`拟定标题: ${d.title}`);
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
      connectSSE(`${API_BASE}/supervisor/start`, { message: msg, work_id: workId });
    } else {
      connectSSE(`${API_BASE}/supervisor/resume`, { session_id: sid, message: msg });
    }
  };

  const handleConfirmEdit = async (accept, targetDiff = null) => {
    const diffTarget = targetDiff || editDiff;
    if (!diffTarget || !sessionId || confirming) return;
    setConfirming(true);
    try {
      const body = { session_id: sessionId, action: accept ? "accept" : "reject" };
      if (accept && diffTarget.new_content) body.new_content = diffTarget.new_content;
      const res = await fetch(`${API_BASE}/supervisor/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || data.message || `HTTP ${res.status}`);
      }
      if (data.error) {
        throw new Error(data.error);
      }
      if (!accept) {
        setEditDiff(null);
        setRunning(false);
        addMessage("assistant", "已拒绝修改。");
      } else {
        setEditDiff(null);
        setRunning(false);
        const ch = data.chapter_number;
        if (ch && onChapterUpdated) onChapterUpdated(ch);
        addMessage("assistant", data.status === "accepted" ? `第${ch || diffTarget.chapter_number}章修改已保存。` : "操作完成。");
      }
    } catch (err) {
      addMessage("system", `确认失败: ${err.message}`, { type: "error" });
    } finally {
      setConfirming(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      {/* 会话选择器 */}
      <div ref={dropdownRef} className="relative flex items-center gap-1 border-b border-slate-200 px-3 py-2">
        <button
          type="button"
          onClick={() => !running && setSessionListOpen(!sessionListOpen)}
          className="flex min-w-0 flex-1 items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-sm text-slate-700 transition-colors hover:bg-slate-100 disabled:opacity-50"
          disabled={running}
        >
          <span className="truncate">{currentSessionTitle}</span>
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-slate-400" />
        </button>
        <button
          type="button"
          onClick={handleNewSession}
          disabled={running}
          className="flex h-7 w-7 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-blue-50 hover:text-blue-500 disabled:opacity-50"
          title="新建对话"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
        {sessionId && (
          <button
            type="button"
            onClick={() => handleDeleteSession(sessionId)}
            disabled={running}
            className="flex h-7 w-7 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-red-50 hover:text-red-500 disabled:opacity-50"
            title="删除对话"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        )}

        {/* 下拉列表 */}
        {sessionListOpen && (
          <div className="absolute left-0 right-0 top-full z-50 max-h-[280px] overflow-y-auto rounded-b-lg border border-t-0 border-slate-200 bg-white shadow-lg">
            {sessions.length === 0 ? (
              <p className="px-3 py-3 text-center text-xs text-slate-400">暂无对话</p>
            ) : (
              sessions.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => handleSelectSession(s)}
                  className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors ${
                    s.id === sessionId
                      ? "bg-blue-50 text-blue-700"
                      : "text-slate-600 hover:bg-slate-50"
                  }`}
                >
                  <span className="min-w-0 flex-1 truncate">{s.title || "新对话"}</span>
                  {s.updated_at && (
                    <span className="shrink-0 text-[10px] text-slate-400">
                      {new Date(s.updated_at).toLocaleDateString("zh-CN", { month: "short", day: "numeric" })}
                    </span>
                  )}
                </button>
              ))
            )}
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3">
        <div className="space-y-3">
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
                        className="mt-1 max-h-32 overflow-y-auto whitespace-pre-wrap break-words text-[10px] font-normal leading-relaxed text-slate-400/90"
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
              <div key={`m-${item.id}`} className={`flex gap-2 ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                {msg.role !== "user" && (
                  <div className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${
                    msg.type === "error" ? "bg-red-100 text-red-500" : "bg-blue-100 text-blue-500"
                  }`}>
                    {msg.type === "error" ? "!" : <Bot className="h-3 w-3" />}
                  </div>
                )}
                <div className={`max-w-[85%] rounded-xl px-3 py-2 text-sm leading-relaxed ${
                  msg.role === "user"
                    ? "bg-blue-600 text-white"
                    : msg.type === "error"
                      ? "bg-red-50 text-red-700 border border-red-200"
                      : msg.type === "agent_phase"
                        ? "bg-slate-50 text-slate-800 border border-slate-200"
                        : "bg-slate-100 text-slate-800"
                }`}>
                  {msg.type === "edit_diff_card" ? (
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-sm text-slate-700">
                          第{msg.diffCard?.chapter_number}章修改建议
                          <span className="ml-2 text-xs text-slate-400">
                            +{msg.diffCard?.summary?.lines_added ?? 0}行 / -{msg.diffCard?.summary?.lines_removed ?? 0}行
                          </span>
                        </span>
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
                            className="h-7 px-2.5 text-xs text-slate-500 hover:text-red-600 hover:bg-red-50"
                            disabled={confirming}
                            onClick={() => handleConfirmEdit(false, msg.diffCard)}
                          >
                            <X className="mr-1 h-3 w-3" /> 拒绝
                          </Button>
                          <Button
                            size="sm"
                            className="h-7 px-2.5 text-xs bg-emerald-600 hover:bg-emerald-700 text-white gap-1"
                            disabled={confirming}
                            onClick={() => handleConfirmEdit(true, msg.diffCard)}
                          >
                            <Check className="h-3 w-3" /> 接受
                          </Button>
                        </div>
                      )}
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
                      <Markdown remarkPlugins={[remarkGfm]} components={mdComponents}>{msg.content}</Markdown>
                    </>
                  )}
                </div>
              </div>
            );
          })}
          {assistantDraft && (
            <div className="flex gap-2 justify-start">
              <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-100 text-blue-500">
                <Bot className="h-3 w-3" />
              </div>
              <div className="max-w-[85%] rounded-xl bg-slate-100 px-3 py-2 text-sm leading-relaxed text-slate-800">
                <Markdown remarkPlugins={[remarkGfm]} components={mdComponents}>{assistantDraft}</Markdown>
                {running && (
                  <span className="inline-block h-2.5 w-px animate-pulse bg-slate-400 align-text-bottom ml-0.5" />
                )}
              </div>
            </div>
          )}
          {running && !timeline.some((item) => item.kind === "step" && item.status === "running") && !editDiff && (
            <div className="flex gap-2 justify-start">
              <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-100 text-blue-500 animate-pulse">
                <Bot className="h-3 w-3" />
              </div>
              <div className="rounded-xl bg-slate-100 px-3 py-2 text-sm text-slate-500">思考中...</div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>
      <div className="shrink-0 border-t border-slate-200 px-4 py-3">
        <div className="flex items-end gap-2">
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="输入指令... (如「修改大纲」「写第1章」「修改第1章的...」)"
            className="min-h-[40px] max-h-[120px] resize-none text-sm"
            rows={1}
            disabled={running}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
          />
          <Button size="sm" className="h-10 shrink-0" onClick={handleSend} disabled={!input.trim() || running}>
            {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </Button>
        </div>
      </div>
    </div>
  );
}

function statusBadge(status) {
  switch (status) {
    case "草稿":
      return "bg-green-100 text-green-700";
    case "已保存":
      return "bg-blue-100 text-blue-700";
    default:
      return "bg-slate-100 text-slate-500";
  }
}

/* ─────────────────────────── Main Page ────────────────────────────────── */

export function WorkDetailPage() {
  const { workId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();

  const [work, setWork] = useState(null);
  const [chapters, setChapters] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [outlineTree, setOutlineTree] = useState(null);
  const [saving, setSaving] = useState(false);
  const [chatOpen, setChatOpen] = useState(true);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const [titleDraft, setTitleDraft] = useState("");
  const [contentDraft, setContentDraft] = useState("");
  const [selectedChapter, setSelectedChapter] = useState(null);
  const [savingChapter, setSavingChapter] = useState(false);
  const [evaluatingChapter, setEvaluatingChapter] = useState(false);
  const [evaluationResult, setEvaluationResult] = useState(null);
  const [evaluationError, setEvaluationError] = useState("");
  const chapterTextareaRef = useRef(null);

  const mainTab = searchParams.get("tab") === "chapter" ? "chapter" : "outline";
  const chRaw = searchParams.get("ch");
  const selectedChapterNum =
    chRaw != null && chRaw !== "" ? parseInt(chRaw, 10) : null;

  const chapterNumbers = useMemo(() => extractChapterNumbers(outlineTree), [outlineTree]);

  const filledChapters = useMemo(
    () =>
      [...chapters]
        .filter((c) => c.status !== "生成中")
        .sort((a, b) => a.chapter_number - b.chapter_number),
    [chapters],
  );
  const filledChapterNums = useMemo(() => filledChapters.map((c) => c.chapter_number), [filledChapters]);
  const hasFilledChapters = filledChapterNums.length > 0;

  const effectiveChapterNum = useMemo(() => {
    if (chapterNumbers.length === 0) return null;
    if (selectedChapterNum == null || Number.isNaN(selectedChapterNum)) return null;
    if (hasFilledChapters) {
      return filledChapterNums.includes(selectedChapterNum) ? selectedChapterNum : null;
    }
    return chapterNumbers.includes(selectedChapterNum) ? selectedChapterNum : null;
  }, [chapterNumbers, selectedChapterNum, hasFilledChapters, filledChapterNums]);

  useEffect(() => {
    const fetchWork = async () => {
      try {
        const [workRes, chaptersRes] = await Promise.all([
          fetch(`${API_BASE}/works/${workId}`),
          fetch(`${API_BASE}/works/${workId}/chapters`),
        ]);
        if (!workRes.ok) throw new Error("加载失败");
        if (!chaptersRes.ok) throw new Error("加载章节失败");
        const data = await workRes.json();
        const chaptersData = await chaptersRes.json();
        setWork(data);
        setOutlineTree(data.outline_tree);
        setChapters(chaptersData);
      } catch (err) {
        setError(err.message || "加载失败");
      } finally {
        setLoading(false);
      }
    };
    fetchWork();
  }, [workId]);

  useEffect(() => {
    if (loading || mainTab !== "chapter" || chapterNumbers.length === 0) return;

    const fromUrl =
      selectedChapterNum != null && !Number.isNaN(selectedChapterNum) ? selectedChapterNum : null;

    if (hasFilledChapters) {
      if (fromUrl != null && filledChapterNums.includes(fromUrl)) return;
      const first = filledChapterNums[0];
      setSearchParams(
        (prev) => {
          const n = new URLSearchParams(prev);
          n.set("tab", "chapter");
          n.set("ch", String(first));
          return n;
        },
        { replace: true },
      );
      return;
    }

    if (fromUrl != null && chapterNumbers.includes(fromUrl)) return;
    const first = chapterNumbers[0];
    setSearchParams(
      (prev) => {
        const n = new URLSearchParams(prev);
        n.set("tab", "chapter");
        n.set("ch", String(first));
        return n;
      },
      { replace: true },
    );
  }, [
    loading,
    mainTab,
    chapterNumbers,
    hasFilledChapters,
    filledChapterNums,
    selectedChapterNum,
    setSearchParams,
  ]);

  useEffect(() => {
    if (mainTab !== "chapter" || effectiveChapterNum == null) return;
    const existing = chapters.find((c) => c.chapter_number === effectiveChapterNum);
    if (existing) {
      setSelectedChapter(existing);
      setTitleDraft(existing.title);
      setContentDraft(existing.content);
    } else {
      setSelectedChapter(null);
      setTitleDraft("");
      setContentDraft("");
    }
    setEvaluationResult(null);
    setEvaluationError("");
  }, [mainTab, effectiveChapterNum, chapters]);

  /** 正文高度随字数变化，避免固定 min-height 在文末留出大块空白 */
  useLayoutEffect(() => {
    if (mainTab !== "chapter") return;
    const el = chapterTextareaRef.current;
    if (!el || !contentDraft) return;
    el.style.height = "auto";
    el.style.height = `${Math.max(el.scrollHeight, 120)}px`;
  }, [mainTab, contentDraft, effectiveChapterNum]);

  const saveOutline = async (tree) => {
    setSaving(true);
    try {
      const res = await fetch(`${API_BASE}/works/${workId}/outline`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ outline_tree: tree }),
      });
      if (res.ok) {
        const data = await res.json();
        setWork(data);
      }
    } catch {
      /* silently fail */
    } finally {
      setSaving(false);
    }
  };

  const handleUpdateNode = (nodeId, fields) => {
    setOutlineTree((prev) => {
      const next = structuredClone(prev);
      for (const list of [next.timeline, next.branches, next.foreshadowing]) {
        const node = list?.find((n) => n.id === nodeId);
        if (node) {
          Object.assign(node, fields);
          break;
        }
      }
      saveOutline(next);
      return next;
    });
  };

  const handleDeleteNode = (nodeId) => {
    setOutlineTree((prev) => {
      const next = structuredClone(prev);
      next.timeline = (next.timeline || []).filter((n) => n.id !== nodeId);
      next.branches = (next.branches || []).filter((n) => n.id !== nodeId);
      next.foreshadowing = (next.foreshadowing || []).filter((n) => n.id !== nodeId);
      saveOutline(next);
      return next;
    });
  };

  const handleAddBranch = (attachTo, side) => {
    setOutlineTree((prev) => {
      const next = structuredClone(prev);
      const host = (next.timeline || []).find((n) => n.id === attachTo);
      const cs = parsePositiveChapterInt(host?.chapter_start) ?? 1;
      const ceRaw = parsePositiveChapterInt(host?.chapter_end);
      const ce = ceRaw != null && ceRaw >= cs ? ceRaw : cs;
      next.branches = [
        ...(next.branches || []),
        {
          id: `B${Date.now()}`,
          attach_to: attachTo,
          side,
          name: "新支线",
          summary: "",
          chapter_start: cs,
          chapter_end: ce,
        },
      ];
      saveOutline(next);
      return next;
    });
  };

  const handleUpdateStory = (field, value) => {
    setOutlineTree((prev) => {
      const next = structuredClone(prev);
      next.story = next.story || {};
      next.story[field] = value;
      saveOutline(next);
      return next;
    });
  };

  const setTabOutline = () => {
    setSearchParams(
      (prev) => {
        const n = new URLSearchParams(prev);
        n.set("tab", "outline");
        return n;
      },
      { replace: true },
    );
  };

  const setTabChapter = () => {
    setSearchParams(
      (prev) => {
        const n = new URLSearchParams(prev);
        n.set("tab", "chapter");
        const cur = n.get("ch");
        const parsed = cur != null && cur !== "" ? parseInt(cur, 10) : NaN;
        const needDefault =
          cur == null ||
          cur === "" ||
          Number.isNaN(parsed) ||
          (filledChapterNums.length > 0 && !filledChapterNums.includes(parsed)) ||
          (filledChapterNums.length === 0 && !chapterNumbers.includes(parsed));

        if (needDefault) {
          const pick = filledChapterNums.length > 0 ? filledChapterNums[0] : chapterNumbers[0];
          if (pick != null) n.set("ch", String(pick));
        }
        return n;
      },
      { replace: true },
    );
  };

  const selectChapter = (num) => {
    setSearchParams(
      (prev) => {
        const n = new URLSearchParams(prev);
        n.set("tab", "chapter");
        n.set("ch", String(num));
        return n;
      },
      { replace: true },
    );
  };

  const refreshChapters = async () => {
    try {
      const chaptersRes = await fetch(`${API_BASE}/works/${workId}/chapters`);
      if (chaptersRes.ok) {
        const chaptersData = await chaptersRes.json();
        setChapters(chaptersData);
        // Update selected chapter content if viewing a chapter
        if (effectiveChapterNum) {
          const updated = chaptersData.find((c) => c.chapter_number === effectiveChapterNum);
          if (updated) {
            setSelectedChapter(updated);
            setTitleDraft(updated.title);
            setContentDraft(updated.content || "");
          }
        }
      }
    } catch { /* ignore */ }
  };

  const handleSaveChapter = async () => {
    if (!effectiveChapterNum || savingChapter) return;
    setSavingChapter(true);
    try {
      const res = await fetch(`${API_BASE}/works/${workId}/chapters/${effectiveChapterNum}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: titleDraft, content: contentDraft }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "保存失败" }));
        throw new Error(err.detail || "保存失败");
      }
      const updated = await res.json();
      setChapters((prev) => {
        const idx = prev.findIndex((c) => c.chapter_number === updated.chapter_number);
        if (idx >= 0) {
          const next = [...prev];
          next[idx] = updated;
          return next;
        }
        return [...prev, updated];
      });
      setSelectedChapter(updated);
    } catch (err) {
      alert(`保存失败：${err.message}`);
    } finally {
      setSavingChapter(false);
    }
  };

  const handleEvaluateChapter = async () => {
    if (!effectiveChapterNum || evaluatingChapter) return;
    if (!contentDraft.trim()) {
      setEvaluationError("当前章节正文为空，无法评估。");
      setEvaluationResult(null);
      return;
    }
    setEvaluatingChapter(true);
    setEvaluationError("");
    try {
      const res = await fetch(`${API_BASE}/evaluation/works/${workId}/chapters/${effectiveChapterNum}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chapter_content: contentDraft }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || `评估失败（HTTP ${res.status}）`);
      }
      setEvaluationResult(data);
    } catch (err) {
      setEvaluationResult(null);
      setEvaluationError(err.message || "评估失败");
    } finally {
      setEvaluatingChapter(false);
    }
  };

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
      </main>
    );
  }

  if (error || !work) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <div className="space-y-4 text-center">
          <p className="text-red-500">{error || "作品不存在"}</p>
          <Button asChild variant="outline">
            <Link to="/dashboard">返回首页</Link>
          </Button>
        </div>
      </main>
    );
  }

  const story = outlineTree?.story || {};
  const tags = work.tags || [];
  const createdDate = work.created_at ? new Date(work.created_at).toLocaleDateString("zh-CN") : "";

  const wordCount = contentDraft ? contentDraft.replace(/\s/g, "").length : 0;
  const generatedCount = chapters.filter((c) => c.status !== "生成中").length;

  return (
    <main className="flex h-screen flex-col bg-[linear-gradient(145deg,_#f8fafc_0%,_#ecfeff_45%,_#e2e8f0_100%)]">
      <section className="flex shrink-0 items-center justify-between border-b border-slate-200 bg-white/80 px-4 py-3 backdrop-blur sm:px-6">
        <div className="flex min-w-0 flex-1 items-center gap-3 sm:gap-4">
          <Button asChild variant="ghost" size="sm" className="shrink-0">
            <Link to="/dashboard">
              <ArrowLeft className="mr-1 h-4 w-4" /> 返回
            </Link>
          </Button>
          <div className="min-w-0">
            <h1 className="truncate text-lg font-semibold text-slate-900">
              <EditableText
                value={story.title || work.title}
                onSave={(val) => handleUpdateStory("title", val)}
                className="text-lg font-semibold text-slate-900"
              />
            </h1>
            <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
              <EditableText
                value={story.genre || work.genre}
                onSave={(val) => handleUpdateStory("genre", val)}
                className="text-xs text-slate-500"
              />
              {story.volume && <span>· {story.volume}</span>}
              {createdDate && (
                <span className="flex items-center gap-1">
                  <Calendar className="h-3 w-3" /> {createdDate}
                </span>
              )}
              {chapterNumbers.length > 0 && (
                <span className="text-slate-400">
                  · {generatedCount}/{chapterNumbers.length} 章已有正文
                </span>
              )}
              {saving && <span className="text-slate-400">大纲保存中...</span>}
            </div>
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
          <div className="flex rounded-lg border border-slate-200 bg-slate-50 p-0.5">
            <Button
              variant={mainTab === "outline" ? "secondary" : "ghost"}
              size="sm"
              className="h-8 gap-1 px-2 sm:px-3"
              onClick={setTabOutline}
            >
              <LayoutList className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">大纲</span>
            </Button>
            <Button
              variant={mainTab === "chapter" ? "secondary" : "ghost"}
              size="sm"
              className="h-8 gap-1 px-2 sm:px-3"
              onClick={setTabChapter}
            >
              <FileText className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">正文</span>
            </Button>
          </div>

          {tags.length > 0 && (
            <div className="hidden items-center gap-1 md:flex">
              <TagIcon className="h-3 w-3 text-purple-500" />
              {tags.slice(0, 3).map((tag) => (
                <span key={tag} className="rounded-full bg-purple-100 px-2 py-0.5 text-[10px] font-medium text-purple-700">
                  {tag}
                </span>
              ))}
            </div>
          )}

          <Button variant={chatOpen ? "default" : "outline"} size="sm" onClick={() => setChatOpen(!chatOpen)}>
            <Bot className="mr-1 h-4 w-4" />
            {chatOpen ? "关闭" : "AI 助手"}
          </Button>
        </div>
      </section>

      <div className="flex flex-1 overflow-hidden">
        <aside
          className={`flex shrink-0 flex-col border-r border-slate-200 bg-white transition-[width] duration-200 ${
            sidebarCollapsed ? "w-12" : "w-[200px] sm:w-[220px]"
          }`}
        >
          <div className="flex items-center justify-end border-b border-slate-100 px-1 py-1">
            <Button variant="ghost" size="sm" className="h-8 w-8 shrink-0 p-0" onClick={() => setSidebarCollapsed((c) => !c)}>
              {sidebarCollapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
            </Button>
          </div>

          {!sidebarCollapsed ? (
            <>
              <div className="px-3 pb-2 pt-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">章节</div>
              <nav className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-2">
                {chapterNumbers.length === 0 ? (
                  <p className="px-2 py-4 text-center text-xs text-slate-400">大纲中暂无章节区间</p>
                ) : filledChapters.length === 0 ? (
                  <p className="px-2 py-4 text-center text-xs text-slate-400">暂无草稿章节</p>
                ) : (
                  filledChapters.map((ch) => {
                    const num = ch.chapter_number;
                    const status = ch.status;
                    const isActive = mainTab === "chapter" && num === effectiveChapterNum;
                    return (
                      <button
                        key={num}
                        type="button"
                        onClick={() => selectChapter(num)}
                        className={`flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm transition-colors ${
                          isActive ? "bg-blue-50 font-medium text-blue-700" : "text-slate-600 hover:bg-slate-100"
                        }`}
                      >
                        <BookOpen className={`h-3.5 w-3.5 shrink-0 ${isActive ? "text-blue-500" : "text-slate-400"}`} />
                        <span className="min-w-0 flex-1 truncate">{ch.title || `第${num}章`}</span>
                        <span
                          className={`shrink-0 rounded-full px-1 py-0.5 text-[9px] font-medium ${statusBadge(status)}`}
                          title={status}
                        >
                          {status.replace("已", "")}
                        </span>
                      </button>
                    );
                  })
                )}
              </nav>
              <div className="border-t border-slate-100 p-2">
                <Button asChild variant="ghost" size="sm" className="h-8 w-full justify-start gap-2 px-2 text-xs text-slate-600">
                  <Link to={`/works/${workId}/characters`}>
                    <Users className="h-3.5 w-3.5" /> 角色
                  </Link>
                </Button>
              </div>
            </>
          ) : (
            <div className="flex flex-1 flex-col items-center gap-1 overflow-y-auto py-2">
              {filledChapters.map((ch) => {
                const num = ch.chapter_number;
                const isActive = mainTab === "chapter" && num === effectiveChapterNum;
                return (
                  <button
                    key={num}
                    type="button"
                    title={ch.title || `第${num}章`}
                    onClick={() => selectChapter(num)}
                    className={`flex h-8 w-8 items-center justify-center rounded-md text-xs font-medium ${
                      isActive ? "bg-blue-600 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                    }`}
                  >
                    {num}
                  </button>
                );
              })}
            </div>
          )}
        </aside>

        <div className="flex min-w-0 flex-1 overflow-hidden">
          <div className="min-w-0 flex-1 overflow-auto px-4 pb-4 pt-4 sm:px-6 sm:pb-4 sm:pt-6">
            {mainTab === "outline" && (
              <>
                {work.idea && (
                  <div className="mb-4 rounded-lg border border-slate-200 bg-white/80 p-3 text-sm text-slate-600">
                    <span className="font-medium text-slate-800">灵感：</span>
                    {work.idea}
                  </div>
                )}
                <InlineTree
                  tree={outlineTree}
                  onUpdateNode={handleUpdateNode}
                  onDeleteNode={handleDeleteNode}
                  onAddBranch={handleAddBranch}
                />
              </>
            )}

            {mainTab === "chapter" && (
              <div className="mx-auto flex w-full max-w-[880px] flex-col">
                {chapterNumbers.length === 0 ? (
                  <div className="flex flex-1 flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-white/60 p-8 text-center text-slate-500">
                    <p className="text-sm">请先在「大纲」中为时间线配置章节区间</p>
                    <Button variant="outline" size="sm" className="mt-4" onClick={setTabOutline}>
                      去编辑大纲
                    </Button>
                  </div>
                ) : effectiveChapterNum == null ? (
                  <div className="flex flex-1 items-center justify-center text-slate-400">
                    <Loader2 className="h-6 w-6 animate-spin" />
                  </div>
                ) : (
                  <>
                    <div className="mb-4 flex flex-col gap-3 rounded-xl border border-slate-200 bg-white/90 p-4 shadow-sm sm:flex-row sm:items-center sm:justify-between">
                      <div className="flex min-w-0 flex-1 flex-col gap-2 sm:flex-row sm:items-center">
                        <Input
                          value={titleDraft}
                          onChange={(e) => setTitleDraft(e.target.value)}
                          placeholder={`第${effectiveChapterNum}章 标题`}
                          className="w-full text-sm font-medium sm:max-w-[320px]"
                        />
                        <span className="text-xs text-slate-400">{wordCount} 字</span>
                        {selectedChapter && (
                          <span className={`w-fit rounded-full px-2 py-0.5 text-[10px] font-medium ${statusBadge(selectedChapter.status)}`}>
                            {selectedChapter.status}
                          </span>
                        )}
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={handleSaveChapter}
                          disabled={savingChapter || (!titleDraft && !contentDraft)}
                        >
                          {savingChapter ? (
                            <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <Save className="mr-1 h-3.5 w-3.5" />
                          )}
                          保存
                        </Button>
                      </div>
                    </div>

                    <div className="rounded-xl border border-slate-200 bg-white/90 p-4 shadow-sm">
                      {contentDraft ? (
                        <Textarea
                          ref={chapterTextareaRef}
                          value={contentDraft}
                          onChange={(e) => setContentDraft(e.target.value)}
                          className="min-h-[120px] resize-none overflow-hidden border-0 bg-transparent p-0 text-[15px] leading-[1.8] text-slate-800 shadow-none focus-visible:ring-0"
                          placeholder="开始写作..."
                        />
                      ) : (
                        <div className="flex flex-col items-center justify-center gap-4 py-10">
                          <div className="rounded-full bg-slate-100 p-4">
                            <PenLine className="h-8 w-8 text-slate-400" />
                          </div>
                          <p className="text-sm text-slate-500">第 {effectiveChapterNum} 章尚未生成正文</p>
                          <Button variant="outline" onClick={() => setChatOpen(true)}>
                            <Sparkles className="mr-1 h-4 w-4" />
                            在 AI 对话中生成
                          </Button>
                        </div>
                      )}
                    </div>

                    {(evaluationError || evaluationResult) && (
                      <div className="mt-4 rounded-xl border border-slate-200 bg-white/90 p-4 shadow-sm">
                        <div className="mb-3 flex items-center justify-between">
                          <h3 className="text-sm font-semibold text-slate-800">章节评估</h3>
                          {evaluationResult?.chapter_title && (
                            <span className="text-xs text-slate-500">{evaluationResult.chapter_title}</span>
                          )}
                        </div>

                        {evaluationError ? (
                          <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{evaluationError}</p>
                        ) : (
                          <div className="grid gap-3 md:grid-cols-2">
                            {[
                              { key: "editor", label: "编辑视角" },
                              { key: "reader", label: "读者视角" },
                            ].map((item) => {
                              const r = evaluationResult?.[item.key];
                              if (!r) return null;
                              return (
                                <article key={item.key} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                                  <div className="mb-2 flex items-center justify-between">
                                    <span className="text-sm font-medium text-slate-800">{item.label}</span>
                                    <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-semibold text-blue-700">
                                      {r.total_score}/60
                                    </span>
                                  </div>
                                  <p className="mb-1 text-xs font-medium text-slate-600">问题</p>
                                  <ul className="mb-2 list-disc space-y-0.5 pl-4 text-xs text-slate-600">
                                    {(r.issues || []).slice(0, 3).map((v, i) => <li key={`${item.key}-issue-${i}`}>{v}</li>)}
                                  </ul>
                                  <p className="mb-1 text-xs font-medium text-slate-600">建议</p>
                                  <ul className="list-disc space-y-0.5 pl-4 text-xs text-slate-600">
                                    {(r.suggestions || []).slice(0, 3).map((v, i) => <li key={`${item.key}-sugg-${i}`}>{v}</li>)}
                                  </ul>
                                </article>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </div>

          {chatOpen && (
            <div className="hidden w-[380px] shrink-0 border-l border-slate-200 bg-white md:flex md:flex-col lg:w-[440px]">
              <SupervisorChatPanel
                workId={workId}
                onOutlineUpdated={(newTree) => setOutlineTree(newTree)}
                onChapterUpdated={() => refreshChapters()}
              />
            </div>
          )}
        </div>
      </div>

      {chatOpen && (
        <div className="flex max-h-[40vh] shrink-0 flex-col border-t border-slate-200 bg-white md:hidden">
          <div className="border-b border-slate-100 px-3 py-2 text-center text-xs text-slate-500">AI 对话（小屏）</div>
          <div className="min-h-[200px] flex-1 overflow-hidden">
            <SupervisorChatPanel
              workId={workId}
              onOutlineUpdated={(newTree) => setOutlineTree(newTree)}
              onChapterUpdated={() => refreshChapters()}
            />
          </div>
        </div>
      )}
    </main>
  );
}
