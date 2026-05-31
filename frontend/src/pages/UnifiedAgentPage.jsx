import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  BookOpen,
  ChevronDown,
  Send,
  Sparkles,
  Bot,
  StopCircle,
} from "lucide-react";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { SessionSidebar } from "../components/SessionSidebar";
import { sessionApi } from "../lib/api";
import { useSupervisorChat } from "../hooks/useSupervisorChat";
import { ChatTimeline } from "../components/supervisor/ChatTimeline";
import { useSmartScroll } from "../hooks/useSmartScroll";


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

export function UnifiedAgentPage() {
  const navigate = useNavigate();
  const [workId, setWorkId] = useState(null);
  const [workTitle, setWorkTitle] = useState(null);
  const [currentIntent, setCurrentIntent] = useState(null);
  const [sessionSidebarOpen, setSessionSidebarOpen] = useState(false);

  const chat = useSupervisorChat({
    workId,
    autoMode: true,
    callbacks: {
      onWorkCreated: (data) => {
        setWorkId(data.work_id);
        setWorkTitle(data.title);
      },
    },
  });

  // Track currentIntent from timeline changes
  useEffect(() => {
    const lastUserMsg = [...chat.timeline].reverse().find((m) => m.role === "user");
    if (!lastUserMsg) return;
    // Intent is detected by the supervisor, but we can track it from stage events
  }, [chat.timeline]);

  // Smart auto-scroll
  const scrollContainerRef = useRef(null);
  const { stickToBottom, scrollToBottom } = useSmartScroll(scrollContainerRef, [
    chat.timeline, chat.assistantDraft, chat.editDiff, chat.outlineDiff, chat.characterDiff, chat.running,
  ]);

  const resetState = () => {
    chat.resetState();
    setWorkId(null);
    setWorkTitle(null);
    setCurrentIntent(null);
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
          {chat.sessionId && !chat.running && (
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
          activeId={chat.sessionId}
          onSelect={(session) => chat.handleSelectSession(session)}
          onNew={resetState}
          collapsed={!sessionSidebarOpen}
          onToggle={() => setSessionSidebarOpen(!sessionSidebarOpen)}
        />

        {/* Chat area */}
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Messages */}
          <div ref={scrollContainerRef} className="flex-1 overflow-y-auto px-4 py-4">
            <div className="mx-auto max-w-3xl space-y-4">
              {/* Empty state */}
              {chat.timeline.length === 0 && !chat.running && (
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
                          chat.setInput(ex.text);
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

              {/* Timeline: messages + steps interleaved */}
              <ChatTimeline
                timeline={chat.timeline}
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

              {/* "查看作品" link for outline_created messages */}
              {chat.timeline.filter((m) => m.workId).map((m) => (
                <div key={`link-${m.id}`} className="pt-2 border-t border-slate-200/50">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 text-[10px] text-blue-600"
                    onClick={() => navigate(`/works/${m.workId}`)}
                  >
                    查看作品
                  </Button>
                </div>
              ))}

              {chat.running && !chat.timeline.some((item) => item.kind === "step" && item.status === "running") && !chat.editDiff && !chat.outlineDiff && !chat.characterDiff && (
                <div className="flex gap-3 justify-start">
                  <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-100 text-blue-500 animate-pulse">
                    <Bot className="h-3.5 w-3.5" />
                  </div>
                  <div className="rounded-xl bg-slate-100 px-4 py-2.5 text-sm text-slate-500">连接中…</div>
                </div>
              )}
            </div>
            {!stickToBottom && (
              <button
                onClick={scrollToBottom}
                className="sticky bottom-2 left-1/2 -translate-x-1/2 flex items-center gap-1 rounded-full bg-white/90 border border-slate-200 px-3 py-1 text-xs text-slate-600 shadow-sm backdrop-blur hover:bg-white hover:border-blue-300 transition-colors"
              >
                <ChevronDown className="h-3 w-3" />
                回到底部
              </button>
            )}
          </div>
          <div className="shrink-0 px-4 py-3">
            <div className="mx-auto flex max-w-3xl items-end gap-2 pr-2">
              <Textarea
                value={chat.input}
                onChange={(e) => chat.setInput(e.target.value)}
                placeholder={chat.running ? "Agent 运行中..." : "输入指令... (如「修改大纲」「写第1章」「修改第1章的...」)"}
                className="min-h-[48px] max-h-[140px] resize-none text-sm"
                rows={1}
                disabled={chat.running}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    chat.handleSend();
                  }
                }}
              />
              <Button
                size="icon"
                className={`h-11 w-11 shrink-0 rounded-full ${chat.running ? "bg-red-500 hover:bg-red-600" : ""}`}
                disabled={!chat.running && !chat.input.trim()}
                onClick={chat.running ? chat.handleInterrupt : chat.handleSend}
                aria-label={chat.running ? "中断任务" : "发送消息"}
              >
                {chat.running ? <StopCircle className="h-4 w-4" /> : <Send className="h-4 w-4" />}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}

