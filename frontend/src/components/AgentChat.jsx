import { useRef, useState, useCallback, useEffect, useMemo } from "react";
import { Bot, Send, Sparkles, Plus, ChevronDown, Trash2 } from "lucide-react";
import { useSupervisorChat } from "../hooks/useSupervisorChat";
import { ChatTimeline } from "./supervisor/ChatTimeline";
import { useSmartScroll } from "../hooks/useSmartScroll";
import { sessionApi } from "../lib/api";
import { getLatestSupervisorSession } from "../lib/supervisorSession";

const NODE_PILL_COLORS = {
  outline: "#3b82f6",
  volume: "#6366f1",
  plot: "#f97316",
  chapter: "#22c55e",
  character: "#ec4899",
  worldbuilding: "#8b5cf6",
  note: "#a855f7",
  element: "#d97706",
};

export default function AgentChat({ workId, onNodesUpdate, insertPillRef }) {
  const chat = useSupervisorChat({
    workId,
    callbacks: {
      onChapterUpdated: () => onNodesUpdate?.(),
      onNodesUpdate: () => onNodesUpdate?.(),
    },
  });

  const inputRef = useRef(null);
  const [hasInput, setHasInput] = useState(false);

  const serializeContentEditable = useCallback((el) => {
    let result = "";
    el.childNodes.forEach((node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        result += node.textContent;
      } else if (node.nodeType === Node.ELEMENT_NODE) {
        if (node.dataset.uuid) {
          result += `[[ctx|${node.dataset.uuid}|${node.dataset.type}|${node.dataset.title}]]`;
        } else if (node.tagName === "BR") {
          result += "\n";
        } else {
          result += node.textContent || "";
        }
      }
    });
    return result;
  }, []);

  const insertPill = useCallback((uuid, type, title, selectedText = "") => {
    const el = inputRef.current;
    if (!el) return;
    const quote = (selectedText || "").trim();

    const pill = document.createElement("span");
    pill.contentEditable = false;
    pill.className = "inline-flex items-center rounded-full px-2 py-0.5 text-xs text-white mx-0.5 align-middle";
    pill.style.backgroundColor = NODE_PILL_COLORS[type] || "#6b7280";
    pill.textContent = title;
    pill.dataset.uuid = uuid;
    pill.dataset.type = type;
    pill.dataset.title = title;

    const sel = window.getSelection();
    if (sel && sel.rangeCount > 0 && el.contains(sel.anchorNode)) {
      const range = sel.getRangeAt(0);
      range.deleteContents();
      range.insertNode(pill);
      range.setStartAfter(pill);
      if (quote) {
        const quoteNode = document.createTextNode(`\n“${quote}”`);
        range.insertNode(quoteNode);
        range.setStartAfter(quoteNode);
      }
      range.collapse(true);
      sel.removeAllRanges();
      sel.addRange(range);
    } else {
      el.appendChild(pill);
      let quoteNode = null;
      if (quote) {
        quoteNode = document.createTextNode(`\n“${quote}”`);
        el.appendChild(quoteNode);
      }
      const range = document.createRange();
      range.setStartAfter(quoteNode || pill);
      range.collapse(true);
      sel.removeAllRanges();
      sel.addRange(range);
    }
    el.removeAttribute("data-empty");
    setHasInput(true);
  }, []);

  useEffect(() => {
    if (insertPillRef) {
      insertPillRef.current = insertPill;
    }
    return () => {
      if (insertPillRef) {
        insertPillRef.current = null;
      }
    };
  }, [insertPillRef, insertPill]);

  const handleContentEditableSend = useCallback(() => {
    const el = inputRef.current;
    if (!el || chat.running) return;
    const serialized = serializeContentEditable(el);
    if (!serialized.trim()) return;
    el.innerHTML = "";
    el.setAttribute("data-empty", "");
    setHasInput(false);
    chat.handleSend(serialized);
  }, [chat.running, chat.handleSend, serializeContentEditable]);

  const onInput = useCallback(() => {
    const el = inputRef.current;
    const empty = !el || el.textContent.trim().length === 0;
    setHasInput(!empty);
    if (el) {
      if (empty) el.setAttribute("data-empty", "");
      else el.removeAttribute("data-empty");
    }
  }, []);

  const scrollContainerRef = useRef(null);
  const { stickToBottom, scrollToBottom } = useSmartScroll(scrollContainerRef, [
    chat.timeline, chat.assistantReasoningDraft, chat.assistantDraft,
    chat.running,
  ]);

  // Session 下拉框状态
  const [sessions, setSessions] = useState([]);
  const [sessionError, setSessionError] = useState("");
  const [sessionListOpen, setSessionListOpen] = useState(false);
  const dropdownRef = useRef(null);
  const latestSessionLoadedForWorkRef = useRef(null);

  const loadSessions = useCallback(async () => {
    setSessionError("");
    try {
      const list = await sessionApi.listSupervisor(workId);
      setSessions(list || []);
      return list || [];
    } catch (error) {
      setSessionError(error?.message || "加载对话列表失败");
      return null;
    }
  }, [workId]);

  // 进入/切换作品时，自动加载该作品最新一次对话
  useEffect(() => {
    if (!workId || chat.running) return;
    if (latestSessionLoadedForWorkRef.current === workId) return;

    let cancelled = false;
    (async () => {
      const list = await loadSessions();
      if (cancelled) return;
      if (list === null) return;

      latestSessionLoadedForWorkRef.current = workId;
      const latest = getLatestSupervisorSession(list);
      if (latest) {
        await chat.handleSelectSession(latest);
      } else {
        chat.resetState();
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [workId, chat.running]);

  // session 创建后刷新列表
  useEffect(() => {
    if (chat.sessionId) loadSessions();
  }, [chat.sessionId, loadSessions]);

  // 点击外部关闭下拉框
  useEffect(() => {
    const handleClick = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setSessionListOpen(false);
      }
    };
    if (sessionListOpen) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [sessionListOpen]);

  const currentSessionTitle = useMemo(() => {
    if (!chat.sessionId) return "新对话";
    const s = sessions.find((s) => s.id === chat.sessionId);
    return s?.title || "新对话";
  }, [chat.sessionId, sessions]);

  const handleNewSession = useCallback(() => {
    if (chat.running) return;
    chat.resetState();
    setSessionListOpen(false);
  }, [chat]);

  const handleSelectSession = useCallback(async (session) => {
    setSessionListOpen(false);
    await chat.handleSelectSession(session);
  }, [chat]);

  const handleDeleteSession = useCallback(async (e, id) => {
    e.stopPropagation();
    if (chat.running) return;
    if (!confirm("确定删除这个对话？")) return;
    try {
      await sessionApi.deleteSupervisor(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (chat.sessionId === id) handleNewSession();
      setSessionError("");
    } catch (error) {
      setSessionError(error?.message || "删除对话失败");
    }
  }, [chat, handleNewSession]);

  return (
    <div className="flex flex-col h-full bg-white border-l border-gray-200">
      {/* Header — 下拉选择器 */}
      <div ref={dropdownRef} className="relative shrink-0 border-b border-gray-200">
        <div className="flex items-center justify-between px-3 py-2">
          <button
            type="button"
            onClick={() => !chat.running && setSessionListOpen(!sessionListOpen)}
            className="flex min-w-0 flex-1 items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-sm text-slate-700 transition-colors hover:bg-slate-100 disabled:opacity-50"
            disabled={chat.running}
          >
            <Bot className="h-4 w-4 text-blue-500 shrink-0" />
            <span className="truncate">{currentSessionTitle}</span>
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-slate-400" />
          </button>
          <button
            type="button"
            onClick={handleNewSession}
            disabled={chat.running}
            className="flex h-7 w-7 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-blue-50 hover:text-blue-500 disabled:opacity-50"
            title="新建对话"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
        </div>

        {/* 下拉列表 */}
        {sessionListOpen && (
          <div className="absolute left-0 top-full z-50 w-full max-h-[280px] overflow-y-auto rounded-b-lg border border-t-0 border-slate-200 bg-white shadow-lg">
            {sessionError ? (
              <p className="px-3 py-4 text-center text-xs text-red-500">{sessionError}</p>
            ) : sessions.length === 0 ? (
              <p className="px-3 py-4 text-center text-xs text-slate-400">暂无对话</p>
            ) : (
              sessions.map((s) => (
                <div
                  key={s.id}
                  className={`group flex items-center px-3 py-2 cursor-pointer transition-colors ${
                    chat.sessionId === s.id
                      ? "bg-blue-50 text-blue-800"
                      : "text-slate-600 hover:bg-slate-50"
                  }`}
                  onClick={() => handleSelectSession(s)}
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-medium">{s.title}</p>
                    <p className="text-[10px] text-slate-400">
                      {s.updated_at ? new Date(s.updated_at).toLocaleDateString("zh-CN") : ""}
                    </p>
                  </div>
                  <button
                    onClick={(e) => handleDeleteSession(e, s.id)}
                    className="hidden group-hover:flex shrink-0 items-center justify-center rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-500"
                    title="删除"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              ))
            )}
          </div>
        )}
      </div>

      {/* 消息列表 */}
      <div ref={scrollContainerRef} className="flex-1 overflow-y-auto p-4">
        <div className="space-y-4">
          {chat.timeline.length === 0 && !chat.running && (
            <div className="text-center text-gray-400 mt-12">
              <div className="flex justify-center mb-4">
                <div className="rounded-full bg-blue-100 p-3">
                  <Sparkles className="h-6 w-6 text-blue-500" />
                </div>
              </div>
              <p className="text-sm font-medium mb-2">AI 写作助手</p>
              <p className="text-xs text-gray-400 mb-4">
                输入你的创作需求，AI 会自动识别并执行
              </p>
              <div className="space-y-2">
                {[
                  "帮我写一个科幻大纲",
                  "写第1章",
                  "查看当前画布状态",
                ].map((example) => (
                  <button
                    key={example}
                    onClick={() => {
                      const el = inputRef.current;
                      if (el) {
                        el.textContent = example;
                        el.removeAttribute("data-empty");
                        setHasInput(true);
                      }
                    }}
                    className="block w-full text-left px-3 py-2 text-xs text-gray-500 hover:text-gray-700 hover:bg-gray-50 rounded-lg transition-colors border border-gray-100"
                  >
                    {example}
                  </button>
                ))}
              </div>
            </div>
          )}

          <ChatTimeline
            timeline={chat.timeline}
            assistantReasoningDraft={chat.assistantReasoningDraft}
            assistantDraft={chat.assistantDraft}
            running={chat.running}
            onToggleStep={chat.toggleStepPanel}
            onEditMessage={chat.handleEditResend}
          />

          {chat.running && !chat.timeline.some((item) => item.kind === "step" && item.status === "running") && !chat.assistantDraft && !chat.assistantReasoningDraft && (
            <div className="flex gap-3 justify-start">
              <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-100 text-blue-500 animate-pulse">
                <Bot className="h-3.5 w-3.5" />
              </div>
              <div className="rounded-xl bg-slate-100 px-4 py-2.5 text-sm text-slate-500">连接中…</div>
            </div>
          )}
        </div>

        {!stickToBottom && chat.timeline.length > 3 && (
          <button
            onClick={scrollToBottom}
            className="sticky bottom-2 left-1/2 -translate-x-1/2 flex items-center gap-1 rounded-full bg-white/90 border border-slate-200 px-3 py-1 text-xs text-slate-600 shadow-sm backdrop-blur hover:bg-white hover:border-blue-300 transition-colors"
          >
            回到底部
          </button>
        )}
      </div>

      {/* 输入框 */}
      <div className="shrink-0 px-3 py-3 border-t border-gray-200 bg-gray-50">
        <div className="flex items-end gap-2">
          <div
            ref={inputRef}
            contentEditable={!chat.running}
            onInput={onInput}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleContentEditableSend();
              }
            }}
            onPaste={(e) => {
              e.preventDefault();
              const text = e.clipboardData.getData("text/plain");
              document.execCommand("insertText", false, text);
            }}
            data-placeholder="输入指令..."
            className={`ce-input flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm whitespace-pre-wrap break-words min-h-[2.5rem] max-h-32 overflow-y-auto ${
              chat.running ? "bg-gray-100 cursor-not-allowed" : "bg-white"
            }`}
          />
          <button
            onClick={handleContentEditableSend}
            disabled={chat.running || !hasInput}
            className="h-10 w-10 shrink-0 rounded-full flex items-center justify-center bg-blue-500 text-white transition-colors hover:bg-blue-600 disabled:cursor-not-allowed disabled:bg-gray-300"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
        <div className="mt-2 text-[10px] text-gray-400 text-center">
          按 Enter 发送，Shift + Enter 换行
        </div>
      </div>
    </div>
  );
}
