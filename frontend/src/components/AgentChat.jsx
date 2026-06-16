import { useRef, useState, useCallback, useEffect, useMemo } from "react";
import { Bot, Send, StopCircle, Sparkles, Plus, ChevronDown, Trash2 } from "lucide-react";
import { useSupervisorChat } from "../hooks/useSupervisorChat";
import { ChatTimeline } from "./supervisor/ChatTimeline";
import { useSmartScroll } from "../hooks/useSmartScroll";
import { sessionApi } from "../lib/api";

export default function AgentChat({ workId, onNodesUpdate }) {
  const chat = useSupervisorChat({
    workId,
    autoMode: true,
    callbacks: {
      onWorkCreated: () => onNodesUpdate?.(),
      onChapterUpdated: () => onNodesUpdate?.(),
      onOutlineUpdated: () => onNodesUpdate?.(),
      onCharactersUpdated: () => onNodesUpdate?.(),
      onNodesUpdate: () => onNodesUpdate?.(),
    },
  });

  const scrollContainerRef = useRef(null);
  const { stickToBottom, scrollToBottom } = useSmartScroll(scrollContainerRef, [
    chat.timeline, chat.assistantReasoningDraft, chat.assistantDraft,
    chat.editDiff, chat.outlineDiff, chat.characterDiff, chat.running,
  ]);

  // Session 下拉框状态
  const [sessions, setSessions] = useState([]);
  const [sessionListOpen, setSessionListOpen] = useState(false);
  const dropdownRef = useRef(null);

  const loadSessions = useCallback(async () => {
    try {
      const list = await sessionApi.listSupervisor(workId);
      setSessions(list || []);
    } catch {
      // ignore
    }
  }, [workId]);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

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
    } catch {
      // ignore
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
            {sessions.length === 0 ? (
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
                    onClick={() => chat.setInput(example)}
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
            editDiff={chat.editDiff}
            outlineDiff={chat.outlineDiff}
            characterDiff={chat.characterDiff}
            confirming={chat.confirming}
            running={chat.running}
            onToggleStep={chat.toggleStepPanel}
            onConfirmEdit={chat.handleConfirmEdit}
            onConfirmOutline={chat.handleConfirmOutline}
          />

          {chat.running && !chat.timeline.some((item) => item.kind === "step" && item.status === "running") && !chat.editDiff && !chat.outlineDiff && !chat.characterDiff && (
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
          <textarea
            value={chat.input}
            onChange={(e) => chat.setInput(e.target.value)}
            placeholder={chat.running ? "Agent 运行中..." : "输入指令..."}
            className="flex-1 px-3 py-2 border border-gray-300 rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm disabled:bg-gray-100"
            rows={2}
            disabled={chat.running}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                chat.handleSend();
              }
            }}
          />
          <button
            onClick={chat.running ? chat.handleInterrupt : chat.handleSend}
            disabled={!chat.running && !chat.input.trim()}
            className={`h-10 w-10 shrink-0 rounded-full flex items-center justify-center transition-colors ${
              chat.running
                ? "bg-red-500 hover:bg-red-600 text-white"
                : "bg-blue-500 hover:bg-blue-600 text-white disabled:bg-gray-300 disabled:cursor-not-allowed"
            }`}
          >
            {chat.running ? <StopCircle className="h-4 w-4" /> : <Send className="h-4 w-4" />}
          </button>
        </div>
        <div className="mt-2 text-[10px] text-gray-400 text-center">
          按 Enter 发送，Shift + Enter 换行
        </div>
      </div>
    </div>
  );
}
