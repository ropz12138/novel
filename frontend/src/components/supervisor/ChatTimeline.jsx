import { useRef, Fragment, useState, useEffect } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, Loader2, X, Bot, PenLine, ChevronDown, ChevronRight, Pencil } from "lucide-react";
import { Button } from "../ui/button";
import { ChapterContentDiffViewer } from "./ChapterContentDiffViewer";
import { RequirementsTodoCard } from "../agent/RequirementsTodoCard";

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

/** 模型连续 tool_call 时的无意义正文占位，不作为气泡展示。 */
function isPlaceholderEllipsisContent(content) {
  if (content == null) return false;
  const text = String(content).trim();
  return text === "..." || text === "…";
}

function shouldHideAssistantEllipsisBubble(item) {
  if (item?.kind !== "message" || item.role !== "assistant") return false;
  if (item.type === "requirements_todolist" && item.todoCard) return false;
  if (item.type === "chapter_content_diff_card" && item.chapterContentDiffCard) return false;
  if (item.type === "error") return false;
  if (String(item.reasoningContent || item.meta?.reasoning_content || "").trim()) return false;
  return isPlaceholderEllipsisContent(item.content);
}

const CTX_MARKER_RE = /(\[\[ctx\|[^|]+\|[^|]+\|[^\]]+\]\])/g;

function renderContextualContent(text) {
  const parts = text.split(CTX_MARKER_RE);
  return parts.map((part, i) => {
    const m = part.match(/^\[\[ctx\|([^|]+)\|([^|]+)\|([^\]]+)\]\]$/);
    if (m) {
      const [, , type, title] = m;
      return (
        <span
          key={i}
          className="inline-flex items-center rounded-full px-2 py-0.5 text-xs text-white mx-0.5 align-middle"
          style={{ backgroundColor: NODE_PILL_COLORS[type] || "#6b7280" }}
        >
          {title}
        </span>
      );
    }
    return <Fragment key={i}>{part}</Fragment>;
  });
}

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

function CollapsibleReasoning({
  content,
  collapsed,
  onToggle,
  scrollRef,
  showCursor = false,
  className = "",
}) {
  if (!content?.trim()) return null;

  return (
    <div className={className}>
      <button
        type="button"
        onClick={onToggle}
        className="mb-1 flex items-center gap-1 text-[10px] font-medium text-slate-400 hover:text-slate-500"
      >
        {collapsed ? (
          <ChevronRight className="h-3 w-3 shrink-0" />
        ) : (
          <ChevronDown className="h-3 w-3 shrink-0" />
        )}
        思考过程
      </button>
      {!collapsed && (
        <div
          ref={scrollRef}
          className="max-h-48 overflow-y-auto whitespace-pre-wrap break-words text-xs leading-relaxed text-slate-400"
        >
          {content}
          {showCursor && (
            <span className="inline-block h-2.5 w-px animate-pulse bg-slate-400 align-text-bottom ml-0.5" />
          )}
        </div>
      )}
    </div>
  );
}

function useReasoningCollapse(autoCollapsed) {
  const [manualOpen, setManualOpen] = useState(null);

  useEffect(() => {
    setManualOpen(null);
  }, [autoCollapsed]);

  const collapsed = manualOpen === null ? autoCollapsed : !manualOpen;
  const toggle = () => setManualOpen((open) => (open === null ? autoCollapsed : !open));

  return { collapsed, toggle };
}

function ExecStepRow({ item, onToggleStep }) {
  const hasStream = (item.reasoningStream && item.reasoningStream.trim()) || (item.stream && item.stream.trim());
  const hasContentStream = Boolean(item.stream?.trim());
  const reasoningAutoCollapsed = hasContentStream;
  const { collapsed: reasoningCollapsed, toggle: toggleReasoning } = useReasoningCollapse(reasoningAutoCollapsed);
  const showContent = item.status === "running" || (item.status === "done" && item.panelOpen);
  const showStepStream = showContent && item.stream?.trim();

  return (
    <div className="flex gap-2 justify-start pl-1">
      <div className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center text-slate-300">
        {item.status === "running" ? (
          <Loader2 className="h-3 w-3 animate-spin text-slate-400" />
        ) : item.status === "failed" ? (
          <X className="h-3 w-3 text-red-400" />
        ) : (
          <Check className="h-3 w-3 text-slate-300" />
        )}
      </div>
      <div className="max-w-[min(100%,42rem)] flex-1 min-w-0 py-0.5">
        <div
          className={`text-[11px] font-normal leading-snug text-slate-400 select-none ${hasStream ? "cursor-pointer hover:text-slate-600" : ""}`}
          onClick={() => hasStream && onToggleStep(item.id)}
        >
          {item.label}
        </div>
        {showContent && hasStream && (
          <div className="mt-1 whitespace-pre-wrap break-words text-[10px] font-normal leading-relaxed text-slate-400">
            {item.reasoningStream?.trim() && (
              <CollapsibleReasoning
                content={item.reasoningStream}
                collapsed={reasoningCollapsed}
                onToggle={toggleReasoning}
                scrollRef={(el) => {
                  if (el && item.status === "running" && !reasoningCollapsed) {
                    el.scrollTop = el.scrollHeight;
                  }
                }}
                showCursor={item.status === "running" && !hasContentStream}
                className={showStepStream ? "mb-1" : ""}
              />
            )}
            {showStepStream && (
              <div
                ref={(el) => {
                  if (el && item.status === "running") {
                    el.scrollTop = el.scrollHeight;
                  }
                }}
              >
                {item.stream}
                {item.status === "running" && (
                  <span className="inline-block h-2.5 w-px animate-pulse bg-slate-400 align-text-bottom" />
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function StreamingDraftBlock({ assistantReasoningDraft, assistantDraft, running }) {
  const reasoningAutoCollapsed = Boolean(assistantDraft?.trim());
  const { collapsed: reasoningCollapsed, toggle: toggleReasoning } = useReasoningCollapse(reasoningAutoCollapsed);

  return (
    <div className="flex gap-3 justify-start">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-100 text-blue-500">
        <Bot className="h-3.5 w-3.5" />
      </div>
      <div className="max-w-[85%] rounded-xl bg-slate-100 px-4 py-2.5 text-sm leading-relaxed text-slate-800">
        {assistantReasoningDraft && (
          <CollapsibleReasoning
            content={assistantReasoningDraft}
            collapsed={reasoningCollapsed}
            onToggle={toggleReasoning}
            scrollRef={(el) => {
              if (el && running && !reasoningCollapsed) {
                el.scrollTop = el.scrollHeight;
              }
            }}
            showCursor={running && !assistantDraft}
            className={assistantDraft ? "mb-2 border-b border-slate-200/70 pb-2" : ""}
          />
        )}
        {assistantDraft && (
          <Markdown remarkPlugins={[remarkGfm]}>{assistantDraft}</Markdown>
        )}
        {running && assistantDraft && (
          <span className="inline-block h-2.5 w-px animate-pulse bg-slate-400 align-text-bottom ml-0.5" />
        )}
      </div>
    </div>
  );
}

function AssistantTextMessage({ msg }) {
  const reasoning = msg.reasoningContent || msg.meta?.reasoning_content || "";
  const { collapsed: reasoningCollapsed, toggle: toggleReasoning } = useReasoningCollapse(true);

  return (
    <>
      {msg.type === "agent_phase" && msg.title && (
        <div className="mb-1.5 flex items-center gap-1.5 border-b border-slate-200/80 pb-1 text-xs font-medium text-slate-500">
          <PenLine className="h-3 w-3 shrink-0 text-violet-500" />
          {msg.title}
        </div>
      )}
      <CollapsibleReasoning
        content={reasoning}
        collapsed={reasoningCollapsed}
        onToggle={toggleReasoning}
        className={msg.content ? "mb-2 border-b border-slate-200/70 pb-2" : ""}
      />
      {msg.content && (
        <Markdown remarkPlugins={[remarkGfm]} components={mdComponents}>
          {msg.content}
        </Markdown>
      )}
    </>
  );
}

function UserMessageBubble({ msg, running, onEditMessage }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(msg.content || "");
  const isUserActionsMessage = (
    msg.type === "user_canvas_actions"
    || msg.meta?.type === "user_canvas_actions"
  );
  const canEdit = Boolean(
    msg.dbMessageId
    && onEditMessage
    && !running
    && !isUserActionsMessage
  );

  useEffect(() => {
    if (!editing) setDraft(msg.content || "");
  }, [msg.content, editing]);

  useEffect(() => {
    if (!editing) return undefined;
    const onKeyDown = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        setEditing(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [editing]);

  const cancelEdit = () => setEditing(false);

  if (editing) {
    return (
      <div className="w-full min-w-[260px] rounded-xl border border-slate-200 bg-white text-slate-800 shadow-sm">
        <div className="flex items-center justify-between border-b border-slate-100 px-3 py-2">
          <span className="text-xs font-medium text-slate-600">编辑消息</span>
          <button
            type="button"
            aria-label="取消编辑"
            onClick={cancelEdit}
            className="rounded p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
        <div className="space-y-3 p-3">
          <textarea
            autoFocus
            className="w-full resize-y rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-800 outline-none focus:border-blue-400 focus:bg-white focus:ring-2 focus:ring-blue-100"
            rows={4}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <p className="text-xs leading-relaxed text-slate-500">
            将恢复画布到该消息发送前，并截断后续对话
          </p>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={cancelEdit}
              className="inline-flex h-8 items-center rounded-md border border-slate-200 bg-white px-3 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-50"
            >
              取消
            </button>
            <Button
              type="button"
              className="h-8 px-3 text-xs"
              disabled={!draft.trim()}
              onClick={() => {
                onEditMessage(msg.dbMessageId, draft);
                setEditing(false);
              }}
            >
              重新发送
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="group relative rounded-xl bg-blue-600 px-4 py-2.5 text-sm leading-relaxed text-white">
      <div className="whitespace-pre-wrap break-words pr-6">
        {renderContextualContent(msg.content || "")}
      </div>
      {canEdit && (
        <button
          type="button"
          aria-label="编辑并重新发送"
          onClick={() => setEditing(true)}
          className="absolute bottom-1.5 right-1.5 rounded p-1 text-blue-100 opacity-70 transition-all hover:bg-blue-500/40 hover:text-white focus:opacity-100 group-hover:opacity-100"
          title="编辑并重新发送"
        >
          <Pencil className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}

/**
 * Shared message/timeline rendering component for Supervisor chat.
 * Renders execution steps, message bubbles, chapter diffs, and streaming draft.
 */
export function ChatTimeline({
  timeline,
  assistantDraft,
  assistantReasoningDraft = "",
  running,
  onToggleStep,
  onEditMessage,
}) {
  const bottomRef = useRef(null);
  const visibleTimeline = (timeline || []).filter((item) => !shouldHideAssistantEllipsisBubble(item));
  const visibleDraft = isPlaceholderEllipsisContent(assistantDraft) ? "" : (assistantDraft || "");

  const hasContent = visibleTimeline.length > 0 || assistantReasoningDraft || visibleDraft;
  if (!hasContent && !running) return null;

  return (
    <>
      {visibleTimeline.map((item) => {
        // ── Execution step ──
        if (item.kind === "step") {
          return <ExecStepRow key={`s-${item.id}`} item={item} onToggleStep={onToggleStep} />;
        }

        // ── Message ──
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
            <div className="relative max-w-[80%]">
              {msg.role === "user" ? (
                <UserMessageBubble msg={msg} running={running} onEditMessage={onEditMessage} />
              ) : (
                <div
                  className={`relative rounded-xl px-4 py-2.5 text-sm leading-relaxed ${
                    msg.type === "error"
                      ? "bg-red-50 text-red-700 border border-red-200"
                      : msg.type === "agent_phase"
                        ? "bg-slate-50 text-slate-800 border border-slate-200"
                        : "bg-slate-100 text-slate-800"
                  }`}
                >
                  {renderMessageContent(msg)}
                </div>
              )}
            </div>
            {msg.role === "user" && (
              <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-200 text-slate-500">
                <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
                  <circle cx="12" cy="7" r="4" />
                </svg>
              </div>
            )}
          </div>
        );
      })}
      {/* Streaming draft */}
      {(assistantReasoningDraft || visibleDraft) && (
        <StreamingDraftBlock
          assistantReasoningDraft={assistantReasoningDraft}
          assistantDraft={visibleDraft}
          running={running}
        />
      )}

      <div ref={bottomRef} data-chat-bottom />
    </>
  );
}

/**
 * Render the inner content of a message bubble based on its type.
 */
function renderMessageContent(msg) {
  switch (msg.type) {
    case "chapter_content_diff_card":
      return (
        <ChapterContentDiffViewer
          title={msg.chapterContentDiffCard?.title ?? ""}
          nodeType={msg.chapterContentDiffCard?.node_type}
          hunks={msg.chapterContentDiffCard?.hunks ?? []}
          summary={msg.chapterContentDiffCard?.summary ?? {}}
          textCount={msg.chapterContentDiffCard?.text_count}
          textCountDelta={msg.chapterContentDiffCard?.text_count_delta}
          wordCount={msg.chapterContentDiffCard?.word_count}
          wordCountDelta={msg.chapterContentDiffCard?.word_count_delta}
        />
      );

    case "requirements_todolist":
      return <RequirementsTodoCard todoCard={msg.todoCard} />;

    default:
      // User message or plain assistant text
      if (msg.role === "user") {
        return <p className="whitespace-pre-wrap break-words">{renderContextualContent(msg.content)}</p>;
      }
      return <AssistantTextMessage msg={msg} />;
  }
}
