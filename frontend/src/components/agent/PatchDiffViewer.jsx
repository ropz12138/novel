import { useState } from "react";
import { ChevronDown, ChevronRight, Plus, Minus, ArrowRight } from "lucide-react";

/**
 * Patch-based diff viewer with character-level highlighting and context folding.
 *
 * Props:
 * - hunks: Array of hunk objects from backend build_hunk_diff
 *   Each hunk: { type, removed, added, context_before, context_after, old_start, old_end, char_diff }
 * - summary: { applied: number, failed: number }
 */
export function PatchDiffViewer({ hunks = [], summary = {} }) {
  const [expanded, setExpanded] = useState({});

  if (!hunks || hunks.length === 0) return null;

  const toggle = (idx) => setExpanded((prev) => ({ ...prev, [idx]: !prev[idx] }));

  return (
    <div className="space-y-2">
      {/* Summary bar */}
      <div className="flex items-center gap-3 text-xs text-slate-500">
        <span>{hunks.length} 处修改</span>
        {summary.applied > 0 && <span className="text-green-600">成功 {summary.applied}</span>}
        {summary.failed > 0 && <span className="text-red-500">失败 {summary.failed}</span>}
      </div>

      {/* Hunk list */}
      {hunks.map((hunk, idx) => (
        <HunkCard key={idx} hunk={hunk} idx={idx} expanded={!!expanded[idx]} onToggle={() => toggle(idx)} />
      ))}
    </div>
  );
}

function HunkCard({ hunk, idx, expanded, onToggle }) {
  const { type, removed, added, context_before, context_after, char_diff } = hunk;

  const typeLabel = type === "replace" ? "替换" : type === "insert" ? "插入" : "删除";
  const typeColor =
    type === "replace"
      ? "bg-amber-50 text-amber-700 border-amber-200"
      : type === "insert"
        ? "bg-green-50 text-green-700 border-green-200"
        : "bg-red-50 text-red-700 border-red-200";

  return (
    <div className={`rounded-lg border ${typeColor} overflow-hidden`}>
      {/* Hunk header */}
      <button
        onClick={onToggle}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs font-medium"
      >
        {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        <span className="uppercase tracking-wide">{typeLabel}</span>
        <span className="ml-1 text-[11px] opacity-70">
          {type === "delete"
            ? `删除 ${removed.length} 字`
            : type === "insert"
              ? `新增 ${added.length} 字`
              : `${removed.length} → ${added.length} 字`}
        </span>
      </button>

      {/* Hunk detail */}
      {expanded && (
        <div className="border-t border-current/10 px-3 py-2 space-y-2 bg-white/50">
          {/* Context before */}
          {context_before && (
            <p className="text-[11px] text-slate-400 leading-relaxed">
              ...{context_before.slice(-50)}
            </p>
          )}

          {/* Removed content */}
          {(type === "replace" || type === "delete") && removed && (
            <div className="flex items-start gap-1.5 rounded bg-red-50 px-2 py-1.5">
              <Minus className="mt-0.5 h-3 w-3 shrink-0 text-red-500" />
              <div className="text-[12px] leading-relaxed text-red-800 whitespace-pre-wrap">
                {char_diff ? (
                  <CharDiffSegments segments={char_diff.removed_segments} variant="removed" />
                ) : (
                  removed
                )}
              </div>
            </div>
          )}

          {/* Arrow for replace */}
          {type === "replace" && (
            <div className="flex justify-center">
              <ArrowRight className="h-3 w-3 text-slate-400" />
            </div>
          )}

          {/* Added content */}
          {(type === "replace" || type === "insert") && added && (
            <div className="flex items-start gap-1.5 rounded bg-green-50 px-2 py-1.5">
              <Plus className="mt-0.5 h-3 w-3 shrink-0 text-green-500" />
              <div className="text-[12px] leading-relaxed text-green-800 whitespace-pre-wrap">
                {char_diff ? (
                  <CharDiffSegments segments={char_diff.added_segments} variant="added" />
                ) : (
                  added
                )}
              </div>
            </div>
          )}

          {/* Context after */}
          {context_after && (
            <p className="text-[11px] text-slate-400 leading-relaxed">
              {context_after.slice(0, 50)}...
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function CharDiffSegments({ segments = [], variant }) {
  if (!segments || segments.length === 0) return null;

  return (
    <span>
      {segments.map((seg, i) => {
        if (seg.changed) {
          return (
            <mark
              key={i}
              className={`rounded-sm px-0.5 ${
                variant === "removed"
                  ? "bg-red-200/70 text-red-900 font-medium"
                  : "bg-green-200/70 text-green-900 font-medium"
              }`}
            >
              {seg.text}
            </mark>
          );
        }
        return <span key={i}>{seg.text}</span>;
      })}
    </span>
  );
}
