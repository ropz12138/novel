import { useEffect, useLayoutEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { inlineTextSegments } from "../lib/inlineContentDiff";

function measurePopover(anchor) {
  if (!anchor || typeof window === "undefined") return null;
  const rect = anchor.getBoundingClientRect();
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const width = Math.min(320, Math.max(160, viewportWidth - 32));
  const left = Math.min(
    viewportWidth - width - 16,
    Math.max(16, rect.left + (rect.width / 2) - (width / 2)),
  );
  return {
    left,
    bottom: viewportHeight - rect.top + 8,
    width,
    maxHeight: Math.min(viewportHeight * 0.5, Math.max(0, rect.top - 16)),
  };
}

function ChangePopover({ anchor, title, text, actions }) {
  const [position, setPosition] = useState(() => measurePopover(anchor));

  useLayoutEffect(() => {
    const updatePosition = () => setPosition(measurePopover(anchor));
    updatePosition();
    window.addEventListener("resize", updatePosition);
    document.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      document.removeEventListener("scroll", updatePosition, true);
    };
  }, [anchor]);

  if (!anchor || !position || typeof document === "undefined") return null;

  return createPortal(
    <span
      role="tooltip"
      data-inline-change-popover="true"
      data-popover-placement="above-anchor"
      className="z-[80] overflow-y-auto whitespace-pre-wrap break-words rounded-md border border-slate-200 bg-white px-3 py-2 text-left text-xs font-normal leading-relaxed text-slate-800 shadow-lg"
      style={{
        position: "fixed",
        ...position,
      }}
    >
      <span className="mb-1 flex items-center justify-between gap-3"><span className="font-medium text-slate-500">{title}</span>{actions}</span>
      {text}
    </span>,
    document.body,
  );
}

function linePlan(newText, groups) {
  const plan = [];
  let cursor = 0;
  groups.forEach((group, groupIndex) => {
    if (groupIndex > 0 && newText.slice(cursor, cursor + 2) === "\n\n") {
      plan.push({ type: "text", text: "\n\n" });
      cursor += 2;
    }
    group.forEach((line, lineIndex) => {
      if (lineIndex > 0 && newText[cursor] === "\n") {
        plan.push({ type: "text", text: "\n" });
        cursor += 1;
      }
      if (newText.slice(cursor, cursor + line.display.length) !== line.display) return;
      plan.push({ type: "line", line, start: cursor, end: cursor + line.display.length });
      cursor += line.display.length;
    });
  });
  if (cursor < newText.length) plan.push({ type: "text", text: newText.slice(cursor) });
  return plan;
}

function piecesInRange(segments, start, end, seen, last) {
  let cursor = 0;
  const pieces = [];
  segments.forEach((segment, index) => {
    const text = segment.newText || "";
    const segStart = cursor;
    const segEnd = cursor + text.length;
    if (!text) {
      const inside = segStart >= start && (segStart < end || (last && segStart <= end));
      if (inside && !seen.has(index)) {
        seen.add(index);
        pieces.push({ segment, index, showActions: true });
      }
      return;
    }
    const from = Math.max(start, segStart);
    const to = Math.min(end, segEnd);
    if (from < to) {
      const showActions = !seen.has(index);
      seen.add(index);
      pieces.push({
        segment: { ...segment, newText: text.slice(from - segStart, to - segStart) },
        index,
        showActions,
      });
    }
    cursor = segEnd;
  });
  return pieces;
}

function CompareView({ oldText, newText, showOld, showNew, audiobookLineGroups = null, activeAudiobookLine = null }) {
  const rendersOld = showOld && Boolean(oldText);
  const rendersNew = showNew && Boolean(newText);
  return (
    <>
      {rendersOld ? (
        <div>
          <div data-quote-ignore className="mb-0.5 text-[11px] text-red-600">原文</div>
          <div className="whitespace-pre-wrap break-words rounded-sm bg-red-100 leading-relaxed text-red-900" data-testid="inline-diff-old" data-diff-kind="delete">{oldText}</div>
        </div>
      ) : null}
      {rendersOld && rendersNew ? <div aria-hidden="true" className="border-t border-slate-200" data-testid="inline-diff-divider" /> : null}
      {rendersNew ? (
        <div>
          <div data-quote-ignore className="mb-0.5 text-[11px] text-emerald-700">新文</div>
          <div className={`whitespace-pre-wrap break-words rounded-sm leading-relaxed ${rendersOld ? "bg-amber-100 text-amber-950" : "bg-emerald-100 text-emerald-950"}`} data-testid="inline-diff-new" data-diff-kind={rendersOld ? "replace" : "insert"}>{audiobookLineGroups ? <AudiobookLineText text={newText} groups={audiobookLineGroups} activeLineIndex={activeAudiobookLine} /> : newText}</div>
        </div>
      ) : null}
    </>
  );
}

function AudiobookLineText({ text, groups, activeLineIndex, renderPiece }) {
  const plan = linePlan(text, groups);
  const seen = new Set();
  const lastLine = [...plan].reverse().find((part) => part.type === "line");
  return plan.map((part, index) => {
    if (part.type === "text") return <span key={`gap-${index}`}>{part.text}</span>;
    const active = activeLineIndex === part.line.index;
    const pieces = renderPiece
      ? piecesInRange(renderPiece.segments, part.start, part.end, seen, part === lastLine).map((piece) => renderPiece.render(piece))
      : part.line.display;
    return (
      <span key={part.line.index}>
        <span
          data-audiobook-line={part.line.index}
          data-audiobook-active={active ? "true" : "false"}
          className={active ? "rounded bg-amber-200/80 [&_[data-diff-kind]]:bg-amber-200/80" : ""}
        >
          {pieces}
        </span>
      </span>
    );
  });
}

export default function InlineTextDiff({ oldText = "", newText = "", showOld = true, showNew = true, comparisonOnly = false, headerActions = null, onResolveChange, audiobookLineGroups = null, activeAudiobookLine = null }) {
  const [compareMode, setCompareMode] = useState(comparisonOnly);
  const [deletedOpen, setDeletedOpen] = useState(false);
  const [deletedAnchor, setDeletedAnchor] = useState(null);
  const [activeChange, setActiveChange] = useState(null);
  const [resolving, setResolving] = useState(false);
  const segments = useMemo(() => inlineTextSegments(showOld ? oldText : "", showNew ? newText : ""), [oldText, newText, showOld, showNew]);
  const isReplacement = showOld && showNew && Boolean(oldText) && Boolean(newText);
  useEffect(() => {
    if (!deletedOpen && !activeChange) return undefined;
    const closeOnOutside = (event) => {
      if (event.target.closest?.('[data-inline-change-trigger="true"], [data-inline-change-popover="true"]')) return;
      setDeletedOpen(false);
      setDeletedAnchor(null);
      setActiveChange(null);
    };
    const closeOnEscape = (event) => {
      if (event.key === "Escape") { setDeletedOpen(false); setActiveChange(null); }
    };
    document.addEventListener("keydown", closeOnEscape);
    document.addEventListener("pointerdown", closeOnOutside);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [deletedOpen, activeChange]);

  useEffect(() => {
    setActiveChange(null);
    setDeletedOpen(false);
  }, [oldText, newText]);

  const resolveChange = async (index, action) => {
    const resolved = segments.map((segment, segmentIndex) => {
      if (segmentIndex !== index) return segment;
      const text = action === "restore" ? segment.oldText : segment.newText;
      return { oldText: text, newText: text };
    });
    setResolving(true);
    try {
      const saved = await onResolveChange({
        oldText: resolved.map((segment) => segment.oldText).join(""),
        newText: resolved.map((segment) => segment.newText).join(""),
      });
      if (saved !== false) { setActiveChange(null); setDeletedOpen(false); }
    } finally {
      setResolving(false);
    }
  };
  const originalActions = (index) => onResolveChange ? (
    <span className="inline-flex shrink-0 gap-2">
      <button type="button" disabled={resolving} onClick={() => resolveChange(index, "restore")} className="rounded px-1.5 py-0.5 text-emerald-700 hover:bg-emerald-50 disabled:opacity-50">恢复</button>
      <button type="button" disabled={resolving} onClick={() => resolveChange(index, "delete")} className="rounded px-1.5 py-0.5 text-red-600 hover:bg-red-50 disabled:opacity-50">删除</button>
    </span>
  ) : null;
  const renderSegment = (segment, index, showActions = true) => {
    if (segment.kind === "equal") return <span key={`${index}-${segment.newText}`}>{segment.newText}</span>;
    const deleted = !segment.newText;
    if (!segment.oldText && segment.newText) {
      return (
        <span
          key={`${index}-${segment.newText}`}
          data-diff-kind="insert"
          data-inline-change-trigger="true"
          className="group/inline-insert relative inline whitespace-pre-wrap break-words rounded-sm bg-emerald-100 text-emerald-950"
          onClick={(event) => { event.stopPropagation(); setActiveChange(null); setDeletedOpen(false); }}
        >
          {segment.newText}
          {showActions && onResolveChange ? (
            <button
              type="button"
              aria-label="删除新增文本"
              title="删除新增文本"
              disabled={resolving}
              className="absolute right-0 top-0 z-10 inline-flex h-4 w-4 -translate-y-1/2 translate-x-1/2 items-center justify-center rounded-full border border-emerald-300 bg-white text-emerald-800 opacity-0 shadow-sm transition-opacity hover:bg-emerald-50 group-hover/inline-insert:opacity-100 group-focus-within/inline-insert:opacity-100 focus-visible:opacity-100 disabled:cursor-wait disabled:opacity-50"
              onClick={(event) => { event.stopPropagation(); resolveChange(index, "restore"); }}
            >
              <X className="h-3 w-3" aria-hidden="true" />
            </button>
          ) : null}
        </span>
      );
    }
    return (
      <span
        key={`${index}-${segment.newText}`}
        role="button"
        tabIndex={0}
        aria-label={deleted ? "查看已删除文本" : "查看修改原文"}
        aria-expanded={activeChange?.index === index}
        data-inline-change-trigger="true"
        data-diff-kind={deleted ? "delete" : segment.oldText ? "replace" : "insert"}
        className={`inline cursor-pointer box-decoration-clone whitespace-pre-wrap break-words rounded-sm text-left [font:inherit] ${deleted ? "bg-red-100 text-red-800" : "bg-amber-100 text-amber-950"}`}
        onClick={(event) => setActiveChange(activeChange?.index === index ? null : { index, anchor: event.currentTarget, text: segment.oldText, deleted })}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            event.currentTarget.click();
          }
        }}
      >
        {deleted ? <span aria-hidden="true">⌫</span> : segment.newText}
      </span>
    );
  };

  if (compareMode) {
    return (
      <div className="space-y-2">
        {(headerActions || (isReplacement && !comparisonOnly)) ? <div className="flex items-center justify-end gap-1 rounded-t-lg bg-slate-100 px-2 py-1">{headerActions}{isReplacement && !comparisonOnly ? <button type="button" onClick={() => setCompareMode(false)} className="rounded px-2 py-1 text-[11px] text-slate-500 hover:bg-slate-200 hover:text-slate-700">结果</button> : null}</div> : null}
        <CompareView oldText={oldText} newText={newText} showOld={showOld} showNew={showNew} audiobookLineGroups={audiobookLineGroups} activeAudiobookLine={activeAudiobookLine} />
      </div>
    );
  }

  if (showOld && !showNew && oldText) {
    return (
      <div className="space-y-1">
        {headerActions ? <div className="flex items-center justify-end gap-1 rounded-t-lg bg-slate-100 px-2 py-1">{headerActions}</div> : null}
        <span className="relative inline-block">
          <button type="button" aria-label="查看已删除段落" data-inline-change-trigger="true" onClick={(event) => { setDeletedAnchor(event.currentTarget); setDeletedOpen((open) => !open); }} className="rounded-md border border-red-200 bg-red-50 px-2 py-1 text-xs font-medium text-red-700">
            已删除一段 · 点击查看
          </button>
          {deletedOpen ? <ChangePopover anchor={deletedAnchor} title="已删除段落" text={oldText} actions={originalActions(0)} /> : null}
        </span>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {(headerActions || isReplacement) ? <div className="flex items-center justify-end gap-1 rounded-t-lg bg-slate-100 px-2 py-1">{headerActions}{isReplacement ? <button type="button" onClick={() => setCompareMode(true)} className="rounded px-2 py-1 text-[11px] text-slate-500 hover:bg-slate-200 hover:text-slate-700">对照</button> : null}</div> : null}
      {showNew && newText ? (
        <div className="whitespace-pre-wrap break-words leading-relaxed text-slate-800" data-testid="inline-diff-new">
          {audiobookLineGroups ? (
            <AudiobookLineText
              text={newText}
              groups={audiobookLineGroups}
              activeLineIndex={activeAudiobookLine}
              renderPiece={{
                segments,
                render: (piece) => renderSegment(piece.segment, piece.index, piece.showActions),
              }}
            />
          ) : segments.map((segment, index) => renderSegment(segment, index))}
          {activeChange ? <ChangePopover anchor={activeChange.anchor} title={activeChange.deleted ? "已删除文本" : "原文"} text={activeChange.text} actions={activeChange.text ? originalActions(activeChange.index) : null} /> : null}
        </div>
      ) : null}
    </div>
  );
}
