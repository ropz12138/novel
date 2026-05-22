import { API_BASE } from "../lib/runtime-config";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  BookOpen,
  ChevronDown,
  ChevronUp,
  Loader2,
  Menu,
  PanelLeftClose,
  Send,
  Sparkles,
  Zap,
} from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { ConfirmBar } from "../components/agent/ConfirmBar";
import { ProposalCard } from "../components/agent/ProposalCard";


function extractChapterNumbers(outlineTree) {
  if (!outlineTree) return [];
  const allNodes = [...(outlineTree.timeline || []), ...(outlineTree.branches || [])];
  if (allNodes.length === 0) return [];
  let max = 0;
  for (const n of allNodes) { if ((n.chapter_end || 0) > max) max = n.chapter_end; }
  return Array.from({ length: max }, (_, i) => i + 1);
}

function statusBadge(s) {
  if (s === "草稿") return "bg-green-100 text-green-700";
  if (s === "已保存") return "bg-blue-100 text-blue-700";
  return "bg-slate-100 text-slate-500";
}

function dotColor(s) {
  if (s === "active") return "bg-blue-500";
  if (s === "confirm") return "bg-amber-500";
  if (s === "done") return "bg-green-500";
  return "bg-slate-300";
}

const mdComponents = {
  h1: ({node, ...props}) => <h1 className="text-sm font-bold text-slate-800 mt-2 mb-1" {...props} />,
  h2: ({node, ...props}) => <h2 className="text-xs font-bold text-slate-800 mt-2 mb-1" {...props} />,
  h3: ({node, ...props}) => <h3 className="text-xs font-semibold text-slate-700 mt-1.5 mb-0.5" {...props} />,
  ul: ({node, ...props}) => <ul className="list-disc pl-4 my-1 space-y-0.5" {...props} />,
  ol: ({node, ...props}) => <ol className="list-decimal pl-4 my-1 space-y-0.5" {...props} />,
  li: ({node, ...props}) => <li className="text-xs" {...props} />,
  p: ({node, ...props}) => <p className="my-1" {...props} />,
  strong: ({node, ...props}) => <strong className="font-semibold text-slate-800" {...props} />,
  code: ({node, inline, ...props}) => inline
    ? <code className="rounded bg-slate-100 px-1 py-0.5 text-[10px] text-violet-700" {...props} />
    : <code className="block rounded bg-slate-50 p-2 text-[10px] text-slate-600 overflow-x-auto" {...props} />,
  hr: ({node, ...props}) => <hr className="my-2 border-slate-200" {...props} />,
};

export function AgentPage() {
  const { workId, chapterNum } = useParams();
  const chapterNumber = parseInt(chapterNum, 10);
  const navigate = useNavigate();

  const [work, setWork] = useState(null);
  const [chapters, setChapters] = useState([]);
  const [chapterNumbers, setChapterNumbers] = useState([]);
  const [loading, setLoading] = useState(true);

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [agentRunning, setAgentRunning] = useState(false);
  const [agentStage, setAgentStage] = useState("idle");

  // Plan stage
  const [planText, setPlanText] = useState("");
  const [planCollapsed, setPlanCollapsed] = useState(false);

  // Thinking stage
  const [thinkingText, setThinkingText] = useState("");
  const [thinkingCollapsed, setThinkingCollapsed] = useState(false);

  // Query stage
  const [queryResults, setQueryResults] = useState([]);
  const [queryCollapsed, setQueryCollapsed] = useState(false);

  // Write stage
  const [writeText, setWriteText] = useState("");
  const [writeTitle, setWriteTitle] = useState("");
  const [writeWordCount, setWriteWordCount] = useState(0);
  const [writeCollapsed, setWriteCollapsed] = useState(false);

  const [confirmType, setConfirmType] = useState(null);
  const [outlineProposal, setOutlineProposal] = useState(null);
  const [chatInput, setChatInput] = useState("");
  const [autoMode, setAutoMode] = useState(true);

  const chatEndRef = useRef(null);
  const sseRef = useRef(null);

  // The next chapter number that can be written
  const nextChapterNum = chapters.length + 1;
  const isNewChapter = chapterNumber === nextChapterNum;
  const isExistingChapter = chapters.some((c) => c.chapter_number === chapterNumber);

  useEffect(() => {
    (async () => {
      try {
        const [wr, cr] = await Promise.all([
          fetch(`${API_BASE}/works/${workId}`),
          fetch(`${API_BASE}/works/${workId}/chapters`),
        ]);
        const wd = await wr.json();
        const cd = await cr.json();
        setWork(wd);
        setChapters(cd);
        setChapterNumbers(extractChapterNumbers(wd.outline_tree));
      } catch (e) { console.error(e); }
      finally { setLoading(false); }
    })();
  }, [workId]);

  useEffect(() => { resetState(); }, [chapterNumber]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [planText, thinkingText, queryResults, writeText, confirmType, outlineProposal]);

  const resetState = () => {
    setAgentRunning(false);
    setAgentStage("idle");
    setPlanText("");
    setPlanCollapsed(false);
    setThinkingText("");
    setThinkingCollapsed(false);
    setQueryResults([]);
    setQueryCollapsed(false);
    setWriteText("");
    setWriteTitle("");
    setWriteWordCount(0);
    setWriteCollapsed(false);
    setConfirmType(null);
    setOutlineProposal(null);
    setChatInput("");
    if (sseRef.current) { sseRef.current.close(); sseRef.current = null; }
  };

  const goTo = (num) => {
    if (num === chapterNumber || agentRunning) return;
    navigate(`/works/${workId}/agent/${num}`);
  };

  const getCh = (n) => chapters.find((c) => c.chapter_number === n);
  const chTitle = (n) => getCh(n)?.title || `第${n}章`;
  const chStatus = (n) => getCh(n)?.status || "生成中";
  const chContent = (n) => getCh(n)?.content || "";

  const existingContent = chContent(chapterNumber);
  const displayContent = writeText || existingContent;
  const displayTitle = writeTitle || chTitle(chapterNumber);
  const wordCount = (writeText || existingContent || "").replace(/\s/g, "").length;

  const planSt = agentStage === "plan"
    ? "active" : planText ? "done" : "pending";
  const thinkingSt = agentStage === "thinking" && confirmType !== "thinking"
    ? "active" : confirmType === "thinking" ? "confirm" : thinkingText ? "done" : "pending";
  const querySt = agentStage === "query" ? "active" : queryResults.length > 0 ? "done" : "pending";
  const writeSt = agentStage === "write" && confirmType !== "save"
    ? "active" : confirmType === "save" ? "confirm" : writeText ? "done" : "pending";

  /* SSE helper */
  const connectSSE = (url, body) => {
    setAgentRunning(true);
    const ctl = new AbortController();
    fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: ctl.signal })
      .then(async (res) => {
        if (!res.ok) {
          let msg = `HTTP ${res.status}`;
          try {
            const errBody = await res.json();
            msg = errBody.detail || errBody.message || msg;
          } catch {
            try {
              msg = (await res.text()).slice(0, 200) || msg;
            } catch { /* ignore */ }
          }
          setAgentRunning(false);
          alert(`请求失败：${msg}`);
          return;
        }
        if (!res.body) {
          setAgentRunning(false);
          alert("请求失败：响应体为空");
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
              if (ln.startsWith("event: ")) { ev = ln.slice(7).trim(); }
              else if (ln.startsWith("data: ")) {
                try { onSSE(ev, JSON.parse(ln.slice(6))); } catch {}
              }
            }
          }
          setAgentRunning(false);
        })().catch(() => setAgentRunning(false));
      })
      .catch((e) => {
        setAgentRunning(false);
        if (e?.name !== "AbortError") {
          alert(`网络错误：${e?.message || "无法连接后端（请确认 9001 已启动且未被浏览器拦截）"}`);
        }
      });
    sseRef.current = { close: () => ctl.abort() };
  };

  const onSSE = (ev, d) => {
    switch (ev) {
      case "stage_start": setAgentStage(d.stage); break;
      case "plan_stream": setPlanText((p) => p + d.chunk); break;
      case "plan_done": setPlanText(d.plan || ""); break;
      case "thinking_stream": setThinkingText((p) => p + d.chunk); break;
      case "thinking_done": setThinkingText(d.notes || ""); break;
      case "title_proposed": setWriteTitle(d.title || ""); break;
      case "query_result": setQueryResults((p) => [...p, d]); break;
      case "write_stream": setWriteText((p) => p + d.chunk); break;
      case "write_done": setWriteTitle(d.title || ""); setWriteWordCount(d.word_count || 0); break;
      case "outline_proposal": setOutlineProposal({ reason: d.reason, operations: d.operations }); break;
      case "need_confirm":
        setConfirmType(d.type);
        if (d.type === "save") { setWriteTitle(d.title || ""); setWriteWordCount(d.word_count || 0); }
        if (d.title) setWriteTitle(d.title);
        setAgentRunning(false);
        break;
      case "outline_updated": setOutlineProposal(null); break;
      case "saved": case "done":
        setAgentStage("done"); setConfirmType(null); setAgentRunning(false);
        fetch(`${API_BASE}/works/${workId}/chapters`).then((r) => r.json()).then(setChapters).catch(() => {});
        break;
      case "error": setAgentRunning(false); setConfirmType(null); alert(`Agent 错误：${d.message}`); break;
    }
  };

  const handleStart = () => {
    resetState();
    setAgentRunning(true);
    connectSSE(`${API_BASE}/agent/${workId}/chapters/${chapterNumber}/start`, { instruction: chatInput, auto_mode: autoMode });
    setChatInput("");
  };

  const handleResume = (action, inst = "") => {
    setConfirmType(null);
    setAgentRunning(true);
    if (action !== "confirm" && confirmType === "thinking") {
      setThinkingText("");
      setPlanText("");
    }
    if (confirmType === "save" && action !== "confirm") setWriteText("");
    connectSSE(`${API_BASE}/agent/${workId}/chapters/${chapterNumber}/resume`, { action, instruction: inst });
  };

  const handleSend = () => {
    if (agentRunning) return;
    // 新一轮写作：空闲或上一章已写完（done）时走 start
    if ((agentStage === "idle" || agentStage === "done") && !confirmType) {
      if (!chatInput.trim()) return;
      handleStart();
      return;
    }
    if (confirmType) {
      handleResume("guide", chatInput || "确认，继续");
      setChatInput("");
    }
  };

  if (loading) return <main className="flex min-h-screen items-center justify-center"><Loader2 className="h-8 w-8 animate-spin text-slate-400" /></main>;
  if (!work) return <main className="flex min-h-screen items-center justify-center"><p className="text-red-500">作品不存在</p></main>;

  return (
    <main className="flex h-screen flex-col bg-white">
      {/* ─── Top bar ─── */}
      <header className="flex shrink-0 items-center justify-between border-b border-slate-200 px-4 py-2">
        <div className="flex items-center gap-3">
          <Button asChild variant="ghost" size="sm" className="h-7 px-2">
            <Link to={`/works/${workId}`}><ArrowLeft className="h-4 w-4" /></Link>
          </Button>
          <div className="h-4 w-px bg-slate-200" />
          <span className="text-sm font-semibold text-slate-800">{work.title}</span>
          <span className="text-xs text-slate-400">/</span>
          <span className="text-sm text-slate-600">{displayTitle}</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => { if (!agentRunning) setAutoMode((v) => !v); }}
            disabled={agentRunning}
            className={`flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium transition-colors ${autoMode ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-500 hover:bg-slate-200"} ${agentRunning ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
            title={autoMode ? "全自动模式：点击切换为手动确认模式" : "手动确认模式：点击切换为全自动模式"}
          >
            <Zap className="h-3 w-3" />
            {autoMode ? "全自动" : "手动"}
          </button>
          {agentRunning && <span className="flex items-center gap-1.5 rounded-full bg-blue-50 px-2.5 py-1 text-xs text-blue-600"><Loader2 className="h-3 w-3 animate-spin" />运行中</span>}
          {agentStage === "done" && !agentRunning && <span className="flex items-center gap-1.5 rounded-full bg-green-50 px-2.5 py-1 text-xs text-green-600"><span className="h-1.5 w-1.5 rounded-full bg-green-500" />已完成</span>}
        </div>
      </header>

      {/* ─── Body: sidebar + content ─── */}
      <div className="flex flex-1 overflow-hidden">

        {/* Column 1: Collapsible chapter sidebar */}
        <aside className={`shrink-0 border-r border-slate-200 bg-slate-50 transition-all duration-200 overflow-hidden ${sidebarOpen ? "w-[200px]" : "w-[42px]"}`}>
          <div className="flex h-9 items-center border-b border-slate-200 px-1">
            <button onClick={() => setSidebarOpen(!sidebarOpen)} className="flex h-7 w-7 items-center justify-center rounded text-slate-400 hover:bg-slate-200 hover:text-slate-600" title={sidebarOpen ? "收起" : "展开"}>
              {sidebarOpen ? <PanelLeftClose className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
            </button>
            {sidebarOpen && <span className="ml-1.5 text-xs font-medium text-slate-500">章节</span>}
          </div>
          <nav className="flex flex-col overflow-y-auto py-1" style={{ height: "calc(100% - 36px)" }}>
            <div className="flex-1">
              {chapters.map((ch) => {
                const num = ch.chapter_number;
                const active = num === chapterNumber;
                const st = ch.status || "生成中";
                const dotSt = active && agentStage !== "idle" ? (agentStage === "done" ? "done" : "active") : (st !== "生成中" ? "done" : "pending");
                if (sidebarOpen) {
                  return (
                    <button key={num} onClick={() => goTo(num)} disabled={agentRunning && !active}
                      className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs transition-colors ${active ? "bg-blue-100 text-blue-700 font-medium" : "text-slate-500 hover:bg-slate-100"} ${agentRunning && !active ? "opacity-40 cursor-not-allowed" : ""}`}>
                      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dotColor(dotSt)}`} />
                      <span className="flex-1 truncate">{ch.title || `第${num}章`}</span>
                      {st !== "生成中" && <span className="text-[10px] text-slate-400">{st}</span>}
                    </button>
                  );
                }
                return (
                  <button key={num} onClick={() => goTo(num)} disabled={agentRunning && !active} title={ch.title || `第${num}章`}
                    className={`flex w-full items-center justify-center py-1.5 text-xs transition-colors ${active ? "bg-blue-100 text-blue-700 font-bold" : "text-slate-400 hover:bg-slate-100 hover:text-slate-600"} ${agentRunning && !active ? "opacity-40 cursor-not-allowed" : ""}`}>
                    {num}
                  </button>
                );
              })}
            </div>

            {nextChapterNum <= chapterNumbers.length && (
              <div className={`border-t border-slate-200 pt-1 ${sidebarOpen ? "px-2" : ""}`}>
                {sidebarOpen ? (
                  <button
                    onClick={() => goTo(nextChapterNum)}
                    disabled={agentRunning}
                    className={`flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-left text-xs transition-colors ${isNewChapter ? "bg-blue-100 text-blue-700 font-medium" : "text-blue-600 hover:bg-blue-50"} ${agentRunning ? "opacity-40 cursor-not-allowed" : ""}`}
                  >
                    <span className="flex h-4 w-4 items-center justify-center rounded-full border border-blue-400 text-[10px] text-blue-500">+</span>
                    <span className="flex-1">新章节</span>
                  </button>
                ) : (
                  <button
                    onClick={() => goTo(nextChapterNum)}
                    disabled={agentRunning}
                    title="写新章节"
                    className={`flex w-full items-center justify-center py-1.5 text-xs transition-colors ${isNewChapter ? "bg-blue-100 text-blue-700 font-bold" : "text-blue-500 hover:bg-blue-50"} ${agentRunning ? "opacity-40 cursor-not-allowed" : ""}`}
                  >
                    +
                  </button>
                )}
              </div>
            )}
          </nav>
        </aside>

        {/* Column 2: Chapter content (2/3) */}
        <div className="flex flex-[2] flex-col overflow-hidden border-r border-slate-200">
          <div className="flex shrink-0 items-center justify-between border-b border-slate-100 bg-white px-5 py-2">
            <div className="flex items-center gap-2">
              <BookOpen className="h-3.5 w-3.5 text-slate-400" />
              <span className="text-sm font-medium text-slate-700">{displayTitle}</span>
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${statusBadge(chStatus(chapterNumber))}`}>{chStatus(chapterNumber)}</span>
            </div>
            <span className="text-xs text-slate-400">{wordCount} 字</span>
          </div>
          <div className="flex-1 overflow-y-auto bg-white px-6 py-5">
            {displayContent ? (
              <pre className="whitespace-pre-wrap font-sans text-sm leading-[1.9] text-slate-800">
                {displayContent}
              </pre>
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-3 text-slate-400">
                <Sparkles className="h-8 w-8" />
                <p className="text-sm">第{chapterNumber}章暂无正文</p>
                <p className="text-xs text-slate-300">在右侧输入指令开始写作</p>
              </div>
            )}
          </div>
        </div>

        {/* Column 3: Agent chat panel (1/3) */}
        <div className="flex flex-1 flex-col overflow-hidden bg-slate-50">
          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-4 py-3">
            <div className="space-y-3">

              {/* Idle prompt */}
              {agentStage === "idle" && !planText && !thinkingText && !queryResults.length && !writeText && (
                <div className="flex flex-col items-center justify-center py-16 text-center">
                  <div className="rounded-full bg-blue-100 p-3 mb-3"><Sparkles className="h-5 w-5 text-blue-500" /></div>
                  <p className="text-sm font-medium text-slate-600">Agent 写作助手</p>
                  {isNewChapter ? (
                    <p className="mt-1 text-xs text-slate-400">输入写作指导，AI 自动完成<br />规划、构思、查询、撰写、评估全流程</p>
                  ) : isExistingChapter ? (
                    <p className="mt-1 text-xs text-slate-400">输入修改指令，AI 将基于现有内容<br />进行修改或重新撰写</p>
                  ) : (
                    <p className="mt-1 text-xs text-slate-400">请先在左侧选择章节</p>
                  )}
                </div>
              )}

              {/* Plan */}
              {planText && (
                <div className="rounded-lg border border-slate-200 bg-white">
                  <button
                    type="button"
                    onClick={() => setPlanCollapsed((v) => !v)}
                    className="flex w-full items-center gap-2 border-b border-slate-100 px-3 py-2 hover:bg-slate-50"
                  >
                    <span className={`h-2 w-2 rounded-full ${dotColor(planSt)}`} />
                    <span className="text-xs font-medium text-slate-600">写作规划</span>
                    {planSt === "active" && <Loader2 className="ml-auto h-3 w-3 animate-spin text-blue-500" />}
                    {planSt === "done" && <span className="ml-auto text-[10px] text-green-600">完成</span>}
                    {planSt !== "active" && (planCollapsed ? <ChevronDown className="ml-auto h-3 w-3 text-slate-400" /> : <ChevronUp className="ml-auto h-3 w-3 text-slate-400" />)}
                  </button>
                  {!planCollapsed && (
                    <div className="max-h-[200px] overflow-y-auto px-3 py-2">
                      <div className="text-xs leading-relaxed text-slate-700">
                        <Markdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                          {planText}
                        </Markdown>
                      </div>
                      {planSt === "active" && <span className="inline-block h-3 w-0.5 animate-pulse bg-blue-500 align-text-bottom" />}
                    </div>
                  )}
                </div>
              )}

              {/* Thinking */}
              {thinkingText && (
                <div className="rounded-lg border border-slate-200 bg-white">
                  <button
                    type="button"
                    onClick={() => setThinkingCollapsed((v) => !v)}
                    className="flex w-full items-center gap-2 border-b border-slate-100 px-3 py-2 hover:bg-slate-50"
                  >
                    <span className={`h-2 w-2 rounded-full ${dotColor(thinkingSt)}`} />
                    <span className="text-xs font-medium text-slate-600">构思笔记</span>
                    {thinkingSt === "active" && <Loader2 className="ml-auto h-3 w-3 animate-spin text-blue-500" />}
                    {thinkingSt === "done" && <span className="ml-auto text-[10px] text-green-600">完成</span>}
                    {thinkingSt !== "active" && (thinkingCollapsed ? <ChevronDown className="ml-auto h-3 w-3 text-slate-400" /> : <ChevronUp className="ml-auto h-3 w-3 text-slate-400" />)}
                  </button>
                  {!thinkingCollapsed && (
                    <div className="max-h-[300px] overflow-y-auto px-3 py-2">
                      <div className="thinking-md text-xs leading-relaxed text-slate-700">
                        <Markdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                          {thinkingText}
                        </Markdown>
                      </div>
                      {thinkingSt === "active" && <span className="inline-block h-3 w-0.5 animate-pulse bg-blue-500 align-text-bottom" />}
                    </div>
                  )}
                  {confirmType === "thinking" && (
                    <div className="border-t border-slate-100 px-3 py-2">
                      <ConfirmBar type="thinking" onConfirm={() => handleResume("confirm")} onReject={() => handleResume("reject", "请重新构思")} onGuide={(t) => handleResume("guide", t)} loading={agentRunning} />
                    </div>
                  )}
                </div>
              )}

              {/* Query results */}
              {queryResults.length > 0 && (
                <div className="rounded-lg border border-slate-200 bg-white">
                  <button
                    type="button"
                    onClick={() => setQueryCollapsed((v) => !v)}
                    className="flex w-full items-center gap-2 border-b border-slate-100 px-3 py-2 hover:bg-slate-50"
                  >
                    <span className={`h-2 w-2 rounded-full ${dotColor(querySt)}`} />
                    <span className="text-xs font-medium text-slate-600">查询上下文</span>
                    <span className="ml-auto mr-1 text-[10px] text-slate-400">{queryResults.length} 项</span>
                    {queryCollapsed ? <ChevronDown className="h-3 w-3 text-slate-400" /> : <ChevronUp className="h-3 w-3 text-slate-400" />}
                  </button>
                  {!queryCollapsed && (
                    <div className="max-h-[150px] space-y-1 overflow-y-auto px-3 py-2">
                      {queryResults.map((r, i) => (
                        <div key={i} className="text-[11px] leading-snug">
                          <span className="font-medium text-slate-600">{r.source}</span>
                          <span className="ml-1 text-slate-400 line-clamp-1">{r.summary}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Outline proposal */}
              {outlineProposal && (
                <div>
                  <ProposalCard reason={outlineProposal.reason} operations={outlineProposal.operations} />
                  {confirmType === "outline" && (
                    <div className="mt-2">
                      <ConfirmBar type="outline" onConfirm={() => handleResume("confirm")} onReject={() => handleResume("reject", "不修改大纲")} onGuide={(t) => handleResume("guide", t)} loading={agentRunning} />
                    </div>
                  )}
                </div>
              )}

              {/* Save confirm */}
              {confirmType === "save" && (
                <div className="rounded-lg border border-green-200 bg-green-50 p-3">
                  <p className="mb-2 text-xs font-medium text-green-700">正文撰写完成</p>
                  <p className="mb-1 text-xs text-slate-600">{displayTitle} &middot; {writeWordCount} 字</p>
                  <ConfirmBar type="save" onConfirm={() => handleResume("confirm")} onReject={() => handleResume("reject", "不满意，请重写")} onGuide={(t) => handleResume("guide", t)} loading={agentRunning} />
                </div>
              )}

              {/* Done */}
              {agentStage === "done" && !agentRunning && (
                <div className="rounded-lg border border-green-200 bg-green-50 p-3">
                  <p className="text-xs font-medium text-green-700">{displayTitle} &middot; {wordCount} 字 &middot; 已保存</p>
                  {nextChapterNum <= chapterNumbers.length && (
                    <Button variant="outline" size="sm" className="mt-2 h-7 text-xs" onClick={() => goTo(nextChapterNum)}>下一章</Button>
                  )}
                </div>
              )}

              <div ref={chatEndRef} />
            </div>
          </div>

          {/* Chat input */}
          <div className="shrink-0 border-t border-slate-200 bg-white px-4 py-3">
            <div className="flex items-end gap-2">
              <Textarea
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                placeholder={agentRunning ? "Agent 运行中..." : agentStage === "idle" ? "输入写作指导..." : confirmType ? "输入指导意见..." : "输入指令..."}
                className="min-h-[40px] max-h-[100px] resize-none text-sm"
                rows={1}
                disabled={agentRunning}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
              />
              <Button
                size="sm"
                className="h-10 shrink-0"
                disabled={
                  agentRunning
                  || ((agentStage === "idle" || agentStage === "done") && !confirmType && !chatInput.trim())
                }
                onClick={handleSend}
              >
                {agentRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
