import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";

const TYPE_LABEL = {
  replace: "替换",
  insert_after: "插入",
  delete: "删除",
};

const TYPE_COLOR = {
  replace: "bg-amber-50 text-amber-800 border-amber-200",
  insert_after: "bg-green-50 text-green-800 border-green-200",
  delete: "bg-red-50 text-red-800 border-red-200",
};

/**
 * Canvas 原生章节正文 diff 查看器（段落级，只读）。
 */
export function ChapterContentDiffViewer({
  title = "",
  hunks = [],
  summary = {},
  wordCount,
  wordCountDelta,
}) {
  const [expanded, setExpanded] = useState({});

  if (!hunks.length) return null;

  const toggle = (idx) => setExpanded((prev) => ({ ...prev, [idx]: !prev[idx] }));

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
        {title ? <span className="font-medium text-slate-700">{title}</span> : null}
        <span>{summary.paragraphs_changed ?? hunks.length} 处修改</span>
        {(summary.chars_added ?? 0) > 0 && (
          <span className="text-green-600">+{summary.chars_added} 字</span>
        )}
        {(summary.chars_removed ?? 0) > 0 && (
          <span className="text-red-500">-{summary.chars_removed} 字</span>
        )}
        {typeof wordCount === "number" && (
          <span>共 {wordCount} 字{typeof wordCountDelta === "number" && wordCountDelta !== 0 ? ` (${wordCountDelta > 0 ? "+" : ""}${wordCountDelta})` : ""}</span>
        )}
      </div>

      {hunks.map((hunk, idx) => {
        const type = hunk.type || "replace";
        const isOpen = !!expanded[idx];
        return (
          <div key={idx} className={`rounded-lg border overflow-hidden ${TYPE_COLOR[type] || TYPE_COLOR.replace}`}>
            <button
              type="button"
              onClick={() => toggle(idx)}
              className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs font-medium"
            >
              {isOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
              <span>{TYPE_LABEL[type] || type}</span>
              <span className="opacity-70">段落 {hunk.paragraph_index}</span>
            </button>
            {isOpen && (
              <div className="border-t border-black/5 px-3 py-2 text-[13px] leading-relaxed space-y-2 bg-white/60">
                {type !== "insert_after" && hunk.old_text ? (
                  <div>
                    <div className="text-[11px] text-red-600 mb-0.5">原文</div>
                    <div className="whitespace-pre-wrap text-red-800/90 line-through decoration-red-400/60">{hunk.old_text}</div>
                  </div>
                ) : null}
                {type !== "delete" && hunk.new_text ? (
                  <div>
                    <div className="text-[11px] text-green-600 mb-0.5">新文</div>
                    <div className="whitespace-pre-wrap text-green-900">{hunk.new_text}</div>
                  </div>
                ) : null}
              </div>
            )}
          </div>
        );
      })}

      <div className="text-xs text-slate-500">已自动应用并保存。</div>
    </div>
  );
}
