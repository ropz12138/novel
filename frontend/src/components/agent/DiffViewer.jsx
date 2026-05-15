import { useState } from "react";
import { ChevronDown, ChevronUp, FileDiff, Minus, Plus, Equal } from "lucide-react";

/**
 * Git-style diff viewer component.
 *
 * Props:
 * - diff: Array of { type: "context"|"added"|"removed", line: string, old_no?: number, new_no?: number }
 * - summary: { lines_added: number, lines_removed: number }
 * - collapsed: boolean (initial collapsed state)
 */
export function DiffViewer({ diff = [], summary = {}, collapsed: initialCollapsed = false }) {
  const [collapsed, setCollapsed] = useState(initialCollapsed);
  const [showContext, setShowContext] = useState(true);

  if (!diff || diff.length === 0) return null;

  const added = summary.lines_added ?? 0;
  const removed = summary.lines_removed ?? 0;

  return (
    <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setCollapsed((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 bg-slate-50 border-b border-slate-200 text-left"
      >
        <FileDiff className="h-3.5 w-3.5 text-slate-500" />
        <span className="text-xs font-medium text-slate-700">文件变更</span>
        <span className="ml-auto flex items-center gap-2 text-[11px]">
          <span className="flex items-center gap-0.5 text-green-600">
            <Plus className="h-3 w-3" /> {added}
          </span>
          <span className="flex items-center gap-0.5 text-red-600">
            <Minus className="h-3 w-3" /> {removed}
          </span>
        </span>
        {collapsed ? (
          <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
        ) : (
          <ChevronUp className="h-3.5 w-3.5 text-slate-400" />
        )}
      </button>

      {/* Diff content */}
      {!collapsed && (
        <div className="max-h-[500px] overflow-y-auto overscroll-contain">
          <table className="w-full text-[12px] leading-[1.6] font-mono border-collapse">
            <tbody>
              {diff.map((entry, i) => {
                const bg =
                  entry.type === "added"
                    ? "bg-green-50"
                    : entry.type === "removed"
                      ? "bg-red-50"
                      : "bg-white";
                const lineNoBg =
                  entry.type === "added"
                    ? "bg-green-100/60"
                    : entry.type === "removed"
                      ? "bg-red-100/60"
                      : "bg-slate-50";

                const sign =
                  entry.type === "added" ? "+" : entry.type === "removed" ? "-" : " ";
                const signColor =
                  entry.type === "added"
                    ? "text-green-600"
                    : entry.type === "removed"
                      ? "text-red-600"
                      : "text-slate-400";

                return (
                  <tr key={i} className={`${bg} border-0`}>
                    {/* Old line number */}
                    <td
                      className={`w-[40px] select-none px-1.5 text-right text-[11px] text-slate-400 ${lineNoBg} border-0`}
                    >
                      {entry.type !== "added" ? entry.old_no : ""}
                    </td>
                    {/* New line number */}
                    <td
                      className={`w-[40px] select-none px-1.5 text-right text-[11px] text-slate-400 ${lineNoBg} border-0`}
                    >
                      {entry.type !== "removed" ? entry.new_no : ""}
                    </td>
                    {/* Sign */}
                    <td className={`w-[16px] px-0.5 text-center ${signColor} border-0`}>
                      {sign}
                    </td>
                    {/* Content */}
                    <td className="px-2 py-0 whitespace-pre text-slate-800 border-0">
                      {entry.line || "\u00a0"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
