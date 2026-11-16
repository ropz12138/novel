import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import InlineTextDiff from "../InlineTextDiff";
import { narrowHunksToChangedParagraphs } from "../../lib/inlineContentDiff";
import { remarkHtmlBreaks } from "../../lib/markdown";

const TYPE_LABEL = {
  replace: "替换",
  insert_after: "插入",
  delete: "删除",
};

const TYPE_COLOR = {
  replace: "bg-white text-slate-800 border-slate-200",
  insert_after: "bg-green-50 text-green-800 border-green-200",
  delete: "bg-red-50 text-red-800 border-red-200",
};

function DiffMarkdown({ text }) {
  return (
    <div
      data-testid="notes-diff-markdown"
      className="prose prose-sm min-w-0 max-w-full overflow-hidden break-words text-[13px] leading-relaxed [overflow-wrap:anywhere] [&_img]:max-w-full [&_pre]:max-w-full [&_pre]:overflow-x-auto [&_pre]:whitespace-pre-wrap [&_table]:block [&_table]:max-w-full [&_table]:overflow-x-auto"
    >
      <Markdown remarkPlugins={[remarkGfm, remarkHtmlBreaks]}>{text}</Markdown>
    </div>
  );
}

function MarkdownDiffRows({ oldText, newText, showOld, showNew }) {
  const rendersOld = showOld && Boolean(oldText);
  const rendersNew = showNew && Boolean(newText);
  return (
    <div className="min-w-0 max-w-full space-y-2">
      {rendersOld ? (
        <div className="min-w-0 max-w-full">
          <div className="mb-0.5 text-[11px] text-red-600">原文</div>
          <div className="min-w-0 max-w-full overflow-hidden rounded-sm bg-red-100 px-2 py-1 text-red-900" data-testid="inline-diff-old" data-diff-kind="delete">
            <DiffMarkdown text={oldText} />
          </div>
        </div>
      ) : null}
      {rendersOld && rendersNew ? <div aria-hidden="true" className="border-t border-slate-200" data-testid="inline-diff-divider" /> : null}
      {rendersNew ? (
        <div className="min-w-0 max-w-full">
          <div className="mb-0.5 text-[11px] text-emerald-700">新文</div>
          <div className={`min-w-0 max-w-full overflow-hidden rounded-sm px-2 py-1 ${rendersOld ? "bg-amber-100 text-amber-950" : "bg-emerald-100 text-emerald-950"}`} data-testid="inline-diff-new" data-diff-kind={rendersOld ? "replace" : "insert"}>
            <DiffMarkdown text={newText} />
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function ChapterContentDiffViewer({
  title = "",
  nodeType = "",
  hunks = [],
  summary = {},
  textCount,
  textCountDelta,
  wordCount,
  wordCountDelta,
  markdown = false,
  onExpandHunk,
}) {
  const [expanded, setExpanded] = useState({});

  const visibleHunks = narrowHunksToChangedParagraphs(hunks);
  if (!visibleHunks.length) return null;

  const toggle = (idx) => setExpanded((prev) => ({ ...prev, [idx]: !prev[idx] }));

  return (
    <div className="min-w-0 max-w-full space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
        {title ? <span className="font-medium text-slate-700">{title}</span> : null}
        {nodeType ? <span>{nodeType}</span> : null}
        <span>{visibleHunks.length} 处修改</span>
        {(summary.chars_added ?? 0) > 0 && (
          <span className="text-green-600">+{summary.chars_added} 字</span>
        )}
        {(summary.chars_removed ?? 0) > 0 && (
          <span className="text-red-500">-{summary.chars_removed} 字</span>
        )}
        {typeof wordCount === "number" && nodeType === "chapter" && (
          <span>共 {wordCount} 字{typeof wordCountDelta === "number" && wordCountDelta !== 0 ? ` (${wordCountDelta > 0 ? "+" : ""}${wordCountDelta})` : ""}</span>
        )}
        {typeof textCount === "number" && nodeType !== "chapter" && (
          <span>共 {textCount} 字符{typeof textCountDelta === "number" && textCountDelta !== 0 ? ` (${textCountDelta > 0 ? "+" : ""}${textCountDelta})` : ""}</span>
        )}
      </div>

      {visibleHunks.map((hunk, idx) => {
        const type = hunk.type || "replace";
        const isOpen = !!expanded[idx];
        return (
          <div key={idx} className={`min-w-0 max-w-full rounded-lg border ${markdown ? "overflow-hidden" : "overflow-visible"} ${TYPE_COLOR[type] || TYPE_COLOR.replace}`}>
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                if (!isOpen) onExpandHunk?.(hunk);
                toggle(idx);
              }}
              className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs font-medium"
            >
              {isOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
              <span>{TYPE_LABEL[type] || type}</span>
              <span className="opacity-70">段落 {hunk.paragraph_index}</span>
            </button>
            {isOpen && (
              <div className="border-t border-black/5 px-3 py-2 text-[13px] leading-relaxed space-y-2 bg-white/60">
                {markdown ? (
                  <MarkdownDiffRows
                    oldText={hunk.old_text || ""}
                    newText={hunk.new_text || ""}
                    showOld={type !== "insert_after"}
                    showNew={type !== "delete"}
                  />
                ) : (
                  <InlineTextDiff
                    oldText={hunk.old_text || ""}
                    newText={hunk.new_text || ""}
                    showOld={type !== "insert_after"}
                    showNew={type !== "delete"}
                    comparisonOnly
                  />
                )}
              </div>
            )}
          </div>
        );
      })}

      <div className="text-xs text-slate-500">已自动应用并保存。</div>
    </div>
  );
}
