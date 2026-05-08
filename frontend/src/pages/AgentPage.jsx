import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Sparkles,
} from "lucide-react";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { StageCard } from "../components/agent/StageCard";
import { StreamViewer } from "../components/agent/StreamViewer";
import { ConfirmBar } from "../components/agent/ConfirmBar";
import { ProposalCard } from "../components/agent/ProposalCard";

const API_BASE = "http://127.0.0.1:9001/api";

/* Extract all chapter numbers from the outline tree */
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

export function AgentPage() {
  const { workId, chapterNum } = useParams();
  const chapterNumber = parseInt(chapterNum, 10);

  const [work, setWork] = useState(null);
  const [chapters, setChapters] = useState([]);
  const [chapterNumbers, setChapterNumbers] = useState([]);
  const [loading, setLoading] = useState(true);

  /* Agent state */
  const [agentRunning, setAgentRunning] = useState(false);
  const [agentStage, setAgentStage] = useState("idle"); // idle/thinking/query/write/save/done

  /* Stage data */
  const [thinkingText, setThinkingText] = useState("");
  const [queryResults, setQueryResults] = useState([]);
  const [writeText, setWriteText] = useState("");
  const [writeTitle, setWriteTitle] = useState("");
  const [writeWordCount, setWriteWordCount] = useState(0);

  /* Confirm state */
  const [confirmType, setConfirmType] = useState(null); // thinking/outline/save/null
  const [confirmData, setConfirmData] = useState({});
  const [outlineProposal, setOutlineProposal] = useState(null);

  /* Collapse state for completed stages */
  const [collapsed, setCollapsed] = useState({});

  /* Input */
  const [startInstruction, setStartInstruction] = useState("");

  /* SSE connection ref */
  const eventSourceRef = useRef(null);

  /* Fetch work and chapters */
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

  /* Reset state when chapter changes */
  useEffect(() => {
    resetAgentState();
  }, [chapterNumber]);

  const resetAgentState = () => {
    setAgentRunning(false);
    setAgentStage("idle");
    setThinkingText("");
    setQueryResults([]);
    setWriteText("");
    setWriteTitle("");
    setWriteWordCount(0);
    setConfirmType(null);
    setConfirmData({});
    setOutlineProposal(null);
    setCollapsed({});
    setStartInstruction("");
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  };

  /* Connect to SSE stream and handle events */
  const connectSSE = (url, body) => {
    setAgentRunning(true);

    // Use fetch + ReadableStream for SSE with POST
    const controller = new AbortController();

    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
      .then((response) => {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        const processStream = async () => {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() || "";

            let currentEvent = "";
            for (const line of lines) {
              if (line.startsWith("event: ")) {
                currentEvent = line.slice(7).trim();
              } else if (line.startsWith("data: ")) {
                const dataStr = line.slice(6);
                try {
                  const data = JSON.parse(dataStr);
                  handleSSEEvent(currentEvent, data);
                } catch (e) {
                  // skip non-JSON data
                }
              }
            }
          }
          setAgentRunning(false);
        };

        processStream().catch((err) => {
          if (err.name !== "AbortError") {
            console.error("SSE stream error:", err);
            setAgentRunning(false);
          }
        });
      })
      .catch((err) => {
        if (err.name !== "AbortError") {
          console.error("Fetch error:", err);
          setAgentRunning(false);
        }
      });

    eventSourceRef.current = { close: () => controller.abort() };
  };

  const handleSSEEvent = (event, data) => {
    switch (event) {
      case "stage_start":
        setAgentStage(data.stage);
        if (data.stage === "query") {
          setCollapsed((prev) => ({ ...prev, thinking: true }));
        }
        if (data.stage === "write") {
          setCollapsed((prev) => ({ ...prev, query: true }));
        }
        break;

      case "thinking_stream":
        setThinkingText((prev) => prev + data.chunk);
        break;

      case "thinking_done":
        setCollapsed((prev) => ({ ...prev, thinking: false }));
        break;

      case "query_result":
        setQueryResults((prev) => [...prev, data]);
        break;

      case "query_done":
        break;

      case "write_stream":
        setWriteText((prev) => prev + data.chunk);
        break;

      case "write_done":
        setWriteTitle(data.title || "");
        setWriteWordCount(data.word_count || 0);
        break;

      case "outline_proposal":
        setOutlineProposal({
          reason: data.reason,
          operations: data.operations,
        });
        break;

      case "need_confirm":
        setConfirmType(data.type);
        setConfirmData(data);
        if (data.type === "save") {
          setWriteTitle(data.title || "");
          setWriteWordCount(data.word_count || 0);
        }
        setAgentRunning(false);
        break;

      case "outline_updated":
        setOutlineProposal(null);
        break;

      case "saved":
      case "done":
        setAgentStage("done");
        setConfirmType(null);
        setAgentRunning(false);
        // Refresh chapters list
        fetch(`${API_BASE}/works/${workId}/chapters`)
          .then((r) => r.json())
          .then((data) => setChapters(data))
          .catch(() => {});
        break;

      case "error":
        setAgentRunning(false);
        setConfirmType(null);
        alert(`Agent 错误：${data.message}`);
        break;

      default:
        break;
    }
  };

  const handleStart = () => {
    resetAgentState();
    setAgentRunning(true);
    connectSSE(`${API_BASE}/agent/${workId}/chapters/${chapterNumber}/start`, {
      instruction: startInstruction,
    });
  };

  const handleResume = (action, instruction = "") => {
    setConfirmType(null);
    setAgentRunning(true);
    // Clear accumulated text for re-runs
    if (action !== "confirm") {
      if (confirmType === "thinking") {
        setThinkingText("");
      }
    }
    if (confirmType === "save" && action !== "confirm") {
      setWriteText("");
    }

    connectSSE(`${API_BASE}/agent/${workId}/chapters/${chapterNumber}/resume`, {
      action,
      instruction,
    });
  };

  const getChapterTitle = (num) => {
    const ch = chapters.find((c) => c.chapter_number === num);
    return ch?.title || `第${num}章`;
  };

  /* Determine stage states */
  const thinkingStatus = agentStage === "thinking" && confirmType !== "thinking"
    ? "active"
    : confirmType === "thinking"
      ? "confirm"
      : thinkingText
        ? "done"
        : "pending";

  const queryStatus = agentStage === "query"
    ? "active"
    : queryResults.length > 0
      ? "done"
      : "pending";

  const writeStatus = agentStage === "write" && confirmType !== "save"
    ? "active"
    : confirmType === "save"
      ? "confirm"
      : writeText
        ? "done"
        : "pending";

  const saveStatus = agentStage === "done"
    ? "done"
    : agentStage === "save"
      ? "active"
      : "pending";

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
            <h1 className="text-lg font-semibold text-slate-900">
              {writeTitle || `第${chapterNumber}章`}
            </h1>
            <p className="text-xs text-slate-500">{work.title} &middot; Agent 写作</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* Chapter navigation */}
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0"
              disabled={chapterNumber <= 1}
              onClick={() => {
                const prev = chapterNumber - 1;
                if (prev >= 1) window.location.href = `/works/${workId}/agent/${prev}`;
              }}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="text-xs text-slate-500 min-w-[60px] text-center">
              {chapterNumber} / {chapterNumbers.length}
            </span>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0"
              disabled={chapterNumber >= chapterNumbers.length}
              onClick={() => {
                const next = chapterNumber + 1;
                if (next <= chapterNumbers.length) window.location.href = `/works/${workId}/agent/${next}`;
              }}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>

          {agentRunning && (
            <div className="flex items-center gap-1.5 text-xs text-blue-600">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              <span>Agent 运行中</span>
            </div>
          )}

          {agentStage === "done" && (
            <span className="text-xs text-green-600 font-medium">已完成</span>
          )}
        </div>
      </header>

      {/* Main content */}
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[760px] space-y-3 px-6 py-4">

          {/* Start section (shown when idle) */}
          {agentStage === "idle" && (
            <div className="rounded-lg border border-slate-200 bg-white p-6">
              <div className="mb-4 flex items-center gap-3">
                <div className="rounded-full bg-blue-100 p-3">
                  <Sparkles className="h-6 w-6 text-blue-600" />
                </div>
                <div>
                  <h2 className="text-base font-semibold text-slate-900">
                    Agent 写作：第{chapterNumber}章
                  </h2>
                  <p className="text-xs text-slate-500">
                    AI 将自动完成构思、查询上下文、撰写正文
                  </p>
                </div>
              </div>
              <Textarea
                value={startInstruction}
                onChange={(e) => setStartInstruction(e.target.value)}
                placeholder="可选：输入你的写作指导（如"保持悬疑风格"、"重点描写战斗场面"）"
                className="mb-4 text-sm"
                rows={3}
              />
              <Button onClick={handleStart} disabled={agentRunning}>
                <Sparkles className="mr-1.5 h-4 w-4" />
                开始写作
              </Button>
            </div>
          )}

          {/* Thinking stage */}
          {agentStage !== "idle" && (
            <StageCard
              label="构思阶段"
              status={thinkingStatus}
              summary={thinkingText ? "构思完成" : undefined}
              collapsed={collapsed.thinking && thinkingStatus === "done"}
              onToggle={() => setCollapsed((p) => ({ ...p, thinking: !p.thinking }))}
            >
              <StreamViewer
                text={thinkingText}
                isStreaming={agentStage === "thinking" && confirmType !== "thinking"}
              />
              {confirmType === "thinking" && (
                <ConfirmBar
                  type="thinking"
                  onConfirm={() => handleResume("confirm")}
                  onReject={() => handleResume("reject", "请重新构思")}
                  onGuide={(text) => handleResume("guide", text)}
                  loading={agentRunning}
                />
              )}
            </StageCard>
          )}

          {/* Query stage */}
          {queryResults.length > 0 && (
            <StageCard
              label="查询上下文"
              status={queryStatus}
              summary={`已查询 ${queryResults.length} 项`}
              collapsed={collapsed.query && queryStatus === "done"}
              onToggle={() => setCollapsed((p) => ({ ...p, query: !p.query }))}
            >
              <div className="max-h-[300px] space-y-1.5 overflow-y-auto">
                {queryResults.map((r, idx) => (
                  <div key={idx} className="rounded bg-white/60 px-3 py-2 text-xs">
                    <span className="font-medium text-slate-700">{r.source}</span>
                    <p className="mt-0.5 text-slate-500 line-clamp-2">{r.summary}</p>
                  </div>
                ))}
              </div>
            </StageCard>
          )}

          {/* Write stage */}
          {writeText && (
            <StageCard
              label="撰写正文"
              status={writeStatus}
              summary={writeWordCount ? `${writeWordCount} 字` : undefined}
              collapsed={collapsed.write && writeStatus === "done"}
              onToggle={() => setCollapsed((p) => ({ ...p, write: !p.write }))}
            >
              {outlineProposal && (
                <div className="mb-3">
                  <ProposalCard
                    reason={outlineProposal.reason}
                    operations={outlineProposal.operations}
                  />
                </div>
              )}

              {confirmType === "outline" && outlineProposal && (
                <ConfirmBar
                  type="outline"
                  onConfirm={() => handleResume("confirm")}
                  onReject={() => handleResume("reject", "不修改大纲，用现有元素继续")}
                  onGuide={(text) => handleResume("guide", text)}
                  loading={agentRunning}
                />
              )}

              <StreamViewer
                text={writeText}
                isStreaming={agentStage === "write" && confirmType !== "save"}
              />

              {confirmType === "save" && (
                <ConfirmBar
                  type="save"
                  onConfirm={() => handleResume("confirm")}
                  onReject={() => handleResume("reject", "不满意，请重写")}
                  onGuide={(text) => handleResume("guide", text)}
                  loading={agentRunning}
                />
              )}
            </StageCard>
          )}

          {/* Save stage */}
          {agentStage === "done" && (
            <StageCard
              label="保存完成"
              status="done"
              summary={writeTitle}
              collapsed={false}
            >
              <div className="flex items-center gap-4 text-sm text-slate-600">
                <BookOpen className="h-4 w-4 text-green-500" />
                <span>
                  {writeTitle} &middot; {writeWordCount} 字 &middot; 已保存
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  className="ml-auto text-xs"
                  onClick={() => {
                    const next = chapterNumber + 1;
                    if (next <= chapterNumbers.length) {
                      window.location.href = `/works/${workId}/agent/${next}`;
                    }
                  }}
                  disabled={chapterNumber >= chapterNumbers.length}
                >
                  下一章 →
                </Button>
              </div>
            </StageCard>
          )}

        </div>
      </div>
    </main>
  );
}
