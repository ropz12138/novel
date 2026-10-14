import { useEffect, useLayoutEffect, useState } from "react";
import { createPortal } from "react-dom";

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

function ChangePopover({ anchor, title, text }) {
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
      <span className="mb-1 block font-medium text-slate-500">{title}</span>
      {text}
    </span>,
    document.body,
  );
}

function CompareView({ oldText, newText, showOld, showNew }) {
  const rendersOld = showOld && Boolean(oldText);
  const rendersNew = showNew && Boolean(newText);
  return (
    <>
      {rendersOld ? (
        <div>
          <div className="mb-0.5 text-[11px] text-red-600">原文</div>
          <div className="whitespace-pre-wrap break-words rounded-sm bg-red-100 leading-relaxed text-red-900" data-testid="inline-diff-old" data-diff-kind="delete">{oldText}</div>
        </div>
      ) : null}
      {rendersOld && rendersNew ? <div aria-hidden="true" className="border-t border-slate-200" data-testid="inline-diff-divider" /> : null}
      {rendersNew ? (
        <div>
          <div className="mb-0.5 text-[11px] text-emerald-700">新文</div>
          <div className="whitespace-pre-wrap break-words rounded-sm bg-emerald-100 leading-relaxed text-emerald-950" data-testid="inline-diff-new" data-diff-kind="insert">{newText}</div>
        </div>
      ) : null}
    </>
  );
}

export default function InlineTextDiff({ oldText = "", newText = "", showOld = true, showNew = true, comparisonOnly = false, headerActions = null }) {
  const [compareMode, setCompareMode] = useState(comparisonOnly);
  const [deletedOpen, setDeletedOpen] = useState(false);
  const [deletedAnchor, setDeletedAnchor] = useState(null);
  const isReplacement = showOld && showNew && Boolean(oldText) && Boolean(newText);
  useEffect(() => {
    if (!deletedOpen) return undefined;
    const closeOnOutside = (event) => {
      if (event.target.closest?.('[data-inline-change-trigger="true"], [data-inline-change-popover="true"]')) return;
      setDeletedOpen(false);
      setDeletedAnchor(null);
    };
    document.addEventListener("pointerdown", closeOnOutside);
    return () => document.removeEventListener("pointerdown", closeOnOutside);
  }, [deletedOpen]);

  if (compareMode) {
    return (
      <div className="space-y-2">
        {(headerActions || (isReplacement && !comparisonOnly)) ? <div className="flex items-center justify-end gap-1 rounded-t-lg bg-slate-100 px-2 py-1">{headerActions}{isReplacement && !comparisonOnly ? <button type="button" onClick={() => setCompareMode(false)} className="rounded px-2 py-1 text-[11px] text-slate-500 hover:bg-slate-200 hover:text-slate-700">结果</button> : null}</div> : null}
        <CompareView oldText={oldText} newText={newText} showOld={showOld} showNew={showNew} />
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
          {deletedOpen ? <ChangePopover anchor={deletedAnchor} title="已删除段落" text={oldText} /> : null}
        </span>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {(headerActions || isReplacement) ? <div className="flex items-center justify-end gap-1 rounded-t-lg bg-slate-100 px-2 py-1">{headerActions}{isReplacement ? <button type="button" onClick={() => setCompareMode(true)} className="rounded px-2 py-1 text-[11px] text-slate-500 hover:bg-slate-200 hover:text-slate-700">对照</button> : null}</div> : null}
      {showNew && newText ? (
        <div className="whitespace-pre-wrap break-words leading-relaxed text-slate-800" data-testid="inline-diff-new">
          <span data-diff-kind={isReplacement ? "replace" : "insert"} className={`rounded-sm ${isReplacement ? "bg-amber-100 text-amber-950" : "bg-emerald-100 text-emerald-950"}`}>{newText}</span>
        </div>
      ) : null}
    </div>
  );
}
