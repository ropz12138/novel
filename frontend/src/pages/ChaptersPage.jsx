import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft,
  BookOpen,
  Check,
  Loader2,
  MessageSquare,
  PenLine,
  Save,
  Send,
  Sparkles,
  X,
} from "lucide-react";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Input } from "../components/ui/input";

const API_BASE = "http://127.0.0.1:9001/api";

/* Derive all chapter numbers from the outline tree */
function extractChapterNumbers(outlineTree) {
  if (!outlineTree) return [];
  const timeline = outlineTree.timeline || [];
  const branches = outlineTree.branches || [];
  const allNodes = [...timeline, ...branches];

  if (allNodes.length === 0) return [];

  let maxChapter = 0;
  for (const node of allNodes) {
    const end = node.chapter_end || 0;
    if (end > maxChapter) maxChapter = end;
  }

  return Array.from({ length: maxChapter }, (_, i) => i + 1);
}

/* Status badge color */
function statusBadge(status) {
  switch (status) {
    case "已生成":
      return "bg-green-100 text-green-700";
    case "已编辑":
      return "bg-blue-100 text-blue-700";
    default:
      return "bg-slate-100 text-slate-500";
  }
}

export function ChaptersPage() {
  const { workId } = useParams();
  const [work, setWork] = useState(null);
  const [chapters, setChapters] = useState([]);
  const [chapterNumbers, setChapterNumbers] = useState([]);
  const [selectedNum, setSelectedNum] = useState(null);
  const [selectedChapter, setSelectedChapter] = useState(null);
  const [titleDraft, setTitleDraft] = useState("");
  const [contentDraft, setContentDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);

  /* Chat state */
  const [chatOpen, setChatOpen] = useState(false);
  const [chatMessages, setChatMessages] = useState([]);
  const [chatInput, setChatInput] = useState("");
  const [chatSending, setChatSending] = useState(false);
  const [proposal, setProposal] = useState(null); // { proposed_content, proposed_title, assistant_message }
  const chatEndRef = useRef(null);

  /* Fetch work + chapters on mount */
  useEffect(() => {
    const load = async () => {
      try {
        const [workRes, chaptersRes] = await Promise.all([
          fetch(`${API_BASE}/works/${workId}`),
          fetch(`${API_BASE}/works/${workId}/chapters`),
        ]);
        if (!workRes.ok) throw new Error("加载作品失败");
        if (!chaptersRes.ok) throw new Error("加载章节失败");

        const workData = await workRes.json();
        const chaptersData = await chaptersRes.json();

        setWork(workData);
        setChapters(chaptersData);
        setChapterNumbers(extractChapterNumbers(workData.outline_tree));
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [workId]);

  /* Auto-select first chapter if none selected */
  useEffect(() => {
    if (chapterNumbers.length > 0 && selectedNum === null) {
      setSelectedNum(chapterNumbers[0]);
    }
  }, [chapterNumbers, selectedNum]);

  /* Update selected chapter data when selectedNum or chapters change */
  useEffect(() => {
    if (selectedNum === null) return;
    const existing = chapters.find((c) => c.chapter_number === selectedNum);
    if (existing) {
      setSelectedChapter(existing);
      setTitleDraft(existing.title);
      setContentDraft(existing.content);
    } else {
      setSelectedChapter(null);
      setTitleDraft("");
      setContentDraft("");
    }
    // Reset chat when switching chapters
    setChatMessages([]);
    setProposal(null);
  }, [selectedNum, chapters]);

  /* Auto-scroll chat to bottom */
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages, proposal]);

  const handleSelectChapter = (num) => {
    setSelectedNum(num);
  };

  const handleGenerate = async () => {
    if (!selectedNum || generating) return;
    setGenerating(true);
    try {
      const res = await fetch(`${API_BASE}/works/${workId}/chapters/${selectedNum}/generate`, {
        method: "POST",
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "生成失败" }));
        throw new Error(err.detail || "生成失败");
      }
      const data = await res.json();
      const newChapter = data.chapter;

      setChapters((prev) => {
        const idx = prev.findIndex((c) => c.chapter_number === newChapter.chapter_number);
        if (idx >= 0) {
          const next = [...prev];
          next[idx] = newChapter;
          return next;
        }
        return [...prev, newChapter].sort((a, b) => a.chapter_number - b.chapter_number);
      });
      setTitleDraft(newChapter.title);
      setContentDraft(newChapter.content);
      setSelectedChapter(newChapter);
    } catch (err) {
      alert(`生成失败：${err.message}`);
    } finally {
      setGenerating(false);
    }
  };

  const handleSave = async () => {
    if (!selectedNum || saving) return;
    setSaving(true);
    try {
      const res = await fetch(`${API_BASE}/works/${workId}/chapters/${selectedNum}`, {
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
      setSaving(false);
    }
  };

  const handleChatSend = async () => {
    if (!chatInput.trim() || chatSending || !selectedNum) return;
    const userMsg = chatInput.trim();
    setChatInput("");
    setProposal(null);

    const newMessages = [...chatMessages, { role: "user", content: userMsg }];
    setChatMessages(newMessages);
    setChatSending(true);

    try {
      const res = await fetch(`${API_BASE}/works/${workId}/chapters/${selectedNum}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: userMsg,
          history: chatMessages,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "对话失败" }));
        throw new Error(err.detail || "对话失败");
      }
      const data = await res.json();

      setChatMessages((prev) => [
        ...prev,
        { role: "assistant", content: data.assistant_message },
      ]);

      if (data.proposed_content && data.proposed_content !== contentDraft) {
        setProposal({
          proposed_content: data.proposed_content,
          proposed_title: data.proposed_title,
          assistant_message: data.assistant_message,
        });
      }
    } catch (err) {
      setChatMessages((prev) => [
        ...prev,
        { role: "assistant", content: `出错了：${err.message}` },
      ]);
    } finally {
      setChatSending(false);
    }
  };

  const handleAcceptProposal = () => {
    if (!proposal) return;
    setContentDraft(proposal.proposed_content);
    if (proposal.proposed_title) {
      setTitleDraft(proposal.proposed_title);
    }
    setProposal(null);
  };

  const handleRejectProposal = () => {
    setProposal(null);
  };

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
      </main>
    );
  }

  if (!work) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <p className="text-red-500">作品不存在</p>
      </main>
    );
  }

  const getChapterStatus = (num) => {
    const ch = chapters.find((c) => c.chapter_number === num);
    return ch?.status || "待生成";
  };

  const getChapterTitle = (num) => {
    const ch = chapters.find((c) => c.chapter_number === num);
    return ch?.title || `第${num}章`;
  };

  const wordCount = contentDraft ? contentDraft.replace(/\s/g, "").length : 0;

  return (
    <main className="flex h-screen flex-col bg-slate-50">
      {/* Top bar */}
      <header className="flex shrink-0 items-center justify-between border-b border-slate-200 bg-white px-6 py-3">
        <div className="flex items-center gap-4">
          <Button asChild variant="ghost" size="sm">
            <Link to={`/works/${workId}`}>
              <ArrowLeft className="mr-1 h-4 w-4" /> 返回大纲
            </Link>
          </Button>
          <div>
            <h1 className="text-lg font-semibold text-slate-900">{work.title}</h1>
            <p className="text-xs text-slate-500">{work.genre} &middot; 章节正文</p>
          </div>
        </div>
        <div className="flex items-center gap-3 text-xs text-slate-500">
          <span>{chapters.filter((c) => c.status !== "待生成").length} / {chapterNumbers.length} 章已生成</span>
        </div>
      </header>

      {/* Main area: sidebar + editor + optional chat */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left sidebar: chapter list */}
        <aside className="w-[240px] shrink-0 overflow-y-auto border-r border-slate-200 bg-white py-2">
          {chapterNumbers.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-slate-400">大纲中暂无章节信息</p>
          ) : (
            <nav className="space-y-0.5 px-2">
              {chapterNumbers.map((num) => {
                const status = getChapterStatus(num);
                const isActive = num === selectedNum;
                return (
                  <button
                    key={num}
                    onClick={() => handleSelectChapter(num)}
                    className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                      isActive
                        ? "bg-blue-50 text-blue-700 font-medium"
                        : "text-slate-600 hover:bg-slate-100"
                    }`}
                  >
                    <BookOpen className={`h-3.5 w-3.5 shrink-0 ${isActive ? "text-blue-500" : "text-slate-400"}`} />
                    <span className="flex-1 truncate">{getChapterTitle(num)}</span>
                    <span className={`shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium ${statusBadge(status)}`}>
                      {status === "待生成" ? "" : status.replace("已", "")}
                    </span>
                  </button>
                );
              })}
            </nav>
          )}
        </aside>

        {/* Center: editor */}
        <div className="flex flex-1 flex-col overflow-hidden">
          {selectedNum === null ? (
            <div className="flex flex-1 items-center justify-center text-slate-400">
              <p>请从左侧选择一个章节</p>
            </div>
          ) : (
            <>
              {/* Editor toolbar */}
              <div className="flex shrink-0 items-center justify-between border-b border-slate-200 bg-white px-6 py-3">
                <div className="flex items-center gap-3">
                  <Input
                    value={titleDraft}
                    onChange={(e) => setTitleDraft(e.target.value)}
                    placeholder={`第${selectedNum}章 标题`}
                    className="w-[300px] text-sm font-medium"
                  />
                  <span className="text-xs text-slate-400">{wordCount} 字</span>
                  {selectedChapter && (
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${statusBadge(selectedChapter.status)}`}>
                      {selectedChapter.status}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleSave}
                    disabled={saving || (!titleDraft && !contentDraft)}
                  >
                    {saving ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <Save className="mr-1 h-3.5 w-3.5" />}
                    保存
                  </Button>
                  <Button
                    size="sm"
                    onClick={handleGenerate}
                    disabled={generating}
                  >
                    {generating ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <Sparkles className="mr-1 h-3.5 w-3.5" />}
                    {selectedChapter ? "重新生成" : "生成正文"}
                  </Button>
                  <Button
                    variant={chatOpen ? "default" : "outline"}
                    size="sm"
                    onClick={() => setChatOpen(!chatOpen)}
                  >
                    <MessageSquare className="mr-1 h-3.5 w-3.5" />
                    {chatOpen ? "关闭对话" : "AI 对话"}
                  </Button>
                </div>
              </div>

              {/* Content area: editor + optional chat */}
              <div className="flex flex-1 overflow-hidden">
                {/* Editor content */}
                <div className="flex-1 overflow-auto p-6">
                  {generating ? (
                    <div className="flex h-full flex-col items-center justify-center gap-3 text-slate-400">
                      <Loader2 className="h-8 w-8 animate-spin" />
                      <p className="text-sm">AI 正在撰写第 {selectedNum} 章正文...</p>
                      <p className="text-xs text-slate-300">这可能需要 30-60 秒</p>
                    </div>
                  ) : contentDraft ? (
                    <div className="mx-auto max-w-[680px]">
                      <Textarea
                        value={contentDraft}
                        onChange={(e) => setContentDraft(e.target.value)}
                        className="min-h-[500px] resize-none border-0 bg-transparent p-0 text-[15px] leading-[1.8] text-slate-800 shadow-none focus-visible:ring-0"
                        placeholder="开始写作..."
                      />
                    </div>
                  ) : (
                    <div className="flex h-full flex-col items-center justify-center gap-4">
                      <div className="rounded-full bg-slate-100 p-4">
                        <PenLine className="h-8 w-8 text-slate-400" />
                      </div>
                      <p className="text-sm text-slate-500">第 {selectedNum} 章尚未生成正文</p>
                      <Button onClick={handleGenerate} disabled={generating}>
                        <Sparkles className="mr-1 h-4 w-4" />
                        生成正文
                      </Button>
                    </div>
                  )}
                </div>

                {/* Chat panel */}
                {chatOpen && (
                  <div className="flex w-[360px] shrink-0 flex-col border-l border-slate-200 bg-white">
                    {/* Chat header */}
                    <div className="flex shrink-0 items-center justify-between border-b border-slate-200 px-4 py-3">
                      <div className="flex items-center gap-2">
                        <MessageSquare className="h-4 w-4 text-blue-500" />
                        <span className="text-sm font-medium text-slate-700">AI 对话修改</span>
                      </div>
                      <Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={() => setChatOpen(false)}>
                        <X className="h-4 w-4" />
                      </Button>
                    </div>

                    {/* Messages */}
                    <div className="flex-1 overflow-y-auto px-4 py-3">
                      {chatMessages.length === 0 && !proposal && (
                        <div className="flex flex-col items-center justify-center py-12 text-center text-slate-400">
                          <MessageSquare className="mb-3 h-8 w-8" />
                          <p className="text-sm">告诉 AI 如何修改本章正文</p>
                          <p className="mt-1 text-xs text-slate-300">例如：&ldquo;把战斗场面写得更详细&rdquo;</p>
                        </div>
                      )}

                      <div className="space-y-3">
                        {chatMessages.map((msg, idx) => (
                          <div key={idx} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                            <div
                              className={`max-w-[90%] rounded-xl px-3 py-2 text-sm ${
                                msg.role === "user"
                                  ? "bg-blue-500 text-white"
                                  : "bg-slate-100 text-slate-700"
                              }`}
                            >
                              <p className="whitespace-pre-wrap">{msg.content}</p>
                            </div>
                          </div>
                        ))}

                        {/* Proposal card */}
                        {proposal && (
                          <div className="rounded-lg border border-blue-200 bg-blue-50 p-3">
                            <p className="mb-2 text-xs font-medium text-blue-700">AI 修改建议</p>
                            <p className="mb-3 text-xs text-slate-600">{proposal.assistant_message}</p>
                            <div className="mb-3 max-h-[200px] overflow-y-auto rounded bg-white p-2 text-xs text-slate-700">
                              <p className="whitespace-pre-wrap line-clamp-[12]">
                                {proposal.proposed_content.slice(0, 800)}
                                {proposal.proposed_content.length > 800 ? "..." : ""}
                              </p>
                              {proposal.proposed_content.length > 800 && (
                                <p className="mt-1 text-slate-400">（共 {proposal.proposed_content.replace(/\s/g, "").length} 字，接受后显示全文）</p>
                              )}
                            </div>
                            {proposal.proposed_title && (
                              <p className="mb-3 text-xs text-slate-500">
                                标题修改为：<span className="font-medium">{proposal.proposed_title}</span>
                              </p>
                            )}
                            <div className="flex gap-2">
                              <Button size="sm" className="h-7 text-xs" onClick={handleAcceptProposal}>
                                <Check className="mr-1 h-3 w-3" />
                                接受修改
                              </Button>
                              <Button variant="outline" size="sm" className="h-7 text-xs" onClick={handleRejectProposal}>
                                <X className="mr-1 h-3 w-3" />
                                拒绝
                              </Button>
                            </div>
                          </div>
                        )}

                        {chatSending && (
                          <div className="flex justify-start">
                            <div className="flex items-center gap-2 rounded-xl bg-slate-100 px-3 py-2 text-sm text-slate-500">
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              AI 思考中...
                            </div>
                          </div>
                        )}
                      </div>
                      <div ref={chatEndRef} />
                    </div>

                    {/* Input */}
                    <div className="shrink-0 border-t border-slate-200 px-4 py-3">
                      <div className="flex items-end gap-2">
                        <Textarea
                          value={chatInput}
                          onChange={(e) => setChatInput(e.target.value)}
                          placeholder="输入修改指令..."
                          className="min-h-[40px] max-h-[120px] resize-none text-sm"
                          rows={1}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" && !e.shiftKey) {
                              e.preventDefault();
                              handleChatSend();
                            }
                          }}
                        />
                        <Button
                          size="sm"
                          className="h-10 shrink-0"
                          onClick={handleChatSend}
                          disabled={chatSending || !chatInput.trim()}
                        >
                          {chatSending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                        </Button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </main>
  );
}
