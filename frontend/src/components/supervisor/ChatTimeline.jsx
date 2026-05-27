import { useRef } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, Loader2, X, Bot, PenLine } from "lucide-react";
import { Button } from "../ui/button";
import { DiffViewer } from "../agent/DiffViewer";
import { OutlineDiffViewer } from "../agent/OutlineDiffViewer";
import { CharacterDiffViewer } from "../agent/CharacterDiffViewer";
import { PatchDiffViewer } from "../agent/PatchDiffViewer";
import { MetadataDiffViewer } from "../agent/MetadataDiffViewer";
import { RequirementsTodoCard } from "../agent/RequirementsTodoCard";

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

/**
 * Shared message/timeline rendering component for Supervisor chat.
 * Renders execution steps, message bubbles, diff cards, and streaming draft.
 */
export function ChatTimeline({
  timeline,
  assistantDraft,
  editDiff,
  outlineDiff,
  characterDiff,
  confirming,
  running,
  onToggleStep,
  onConfirmEdit,
  onConfirmOutline,
}) {
  const bottomRef = useRef(null);

  const hasContent = timeline.length > 0 || assistantDraft || editDiff || outlineDiff || characterDiff;
  if (!hasContent && !running) return null;

  return (
    <>
      {timeline.map((item) => {
        // ── Execution step ──
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
                  onClick={() => item.stream && item.stream.trim() && onToggleStep(item.id)}
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
              {renderMessageContent(msg, confirming, onConfirmEdit)}
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

      {/* Floating outline/character diff panel */}
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
                  onClick={() => onConfirmOutline("reject")}
                  disabled={confirming}
                >
                  <X className="mr-1.5 h-3.5 w-3.5" />
                  拒绝
                </Button>
                <Button
                  size="sm"
                  className="h-8 px-3 text-xs bg-emerald-600 hover:bg-emerald-700 text-white"
                  onClick={() => onConfirmOutline("accept")}
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

      {/* Streaming draft */}
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

      <div ref={bottomRef} data-chat-bottom />
    </>
  );
}

/**
 * Render the inner content of a message bubble based on its type.
 */
function renderMessageContent(msg, confirming, onConfirmEdit) {
  switch (msg.type) {
    case "patch_diff_card":
      return (
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
      );

    case "edit_diff_card":
      return (
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
                onClick={() => onConfirmEdit("reject", msg.diffCard)}
                disabled={confirming}
              >
                <X className="mr-1.5 h-3.5 w-3.5" />
                拒绝
              </Button>
              <Button
                size="sm"
                className="h-8 px-3 text-xs bg-emerald-600 hover:bg-emerald-700 text-white"
                onClick={() => onConfirmEdit("accept", msg.diffCard)}
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
      );

    case "requirements_todolist":
      return <RequirementsTodoCard todoCard={msg.todoCard} />;

    case "outline_diff_card":
      return (
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
      );

    case "character_diff_card":
      return (
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
      );

    case "metadata_diff_card":
      return (
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
      );

    case "chapter_meta_card":
      return (
        <div className="space-y-2">
          <p className="text-sm font-medium text-slate-700">章节结构元数据（第{msg.chapterMetaCard?.chapter_number}章）</p>
          <p className="text-xs text-slate-600 whitespace-pre-wrap">{msg.chapterMetaCard?.summary || "无摘要"}</p>
        </div>
      );

    case "consistency_report_card":
      return (
        <div className="space-y-1">
          <p className="text-sm font-medium text-slate-700">一致性检查（第{msg.consistencyReportCard?.chapter_number}章）</p>
          <p className="text-xs text-slate-600">状态：{msg.consistencyReportCard?.consistency_status || "aligned"}</p>
          <p className="text-xs text-slate-600">决策：{msg.consistencyReportCard?.decision || "none"}</p>
        </div>
      );

    default:
      // User message or plain assistant text
      if (msg.role === "user") {
        return <p>{msg.content}</p>;
      }
      return (
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
      );
  }
}
