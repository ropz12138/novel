import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";

const STATUS_STYLES = {
  pending: "border-slate-200 bg-slate-50 text-slate-400",
  active: "border-blue-300 bg-blue-50 text-blue-700",
  confirm: "border-amber-300 bg-amber-50 text-amber-700",
  done: "border-green-200 bg-green-50/50 text-green-700",
  error: "border-red-300 bg-red-50 text-red-700",
};

const STATUS_ICONS = {
  pending: "○",
  active: "",
  confirm: "●",
  done: "✓",
  error: "✗",
};

export function StageCard({ label, status = "pending", summary, collapsed, onToggle, children }) {
  const style = STATUS_STYLES[status] || STATUS_STYLES.pending;
  const icon = STATUS_ICONS[status];

  return (
    <div className={`rounded-lg border transition-all ${style}`}>
      {/* Header */}
      <button
        onClick={onToggle}
        className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm font-medium"
      >
        {status === "active" ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" />
        ) : (
          <span className="w-3.5 text-center shrink-0 text-xs">{icon}</span>
        )}

        <span className="flex-1">{label}</span>

        {summary && status === "done" && (
          <span className="text-xs font-normal opacity-60 truncate max-w-[300px]">{summary}</span>
        )}

        {children && (
          collapsed
            ? <ChevronRight className="h-3.5 w-3.5 opacity-50 shrink-0" />
            : <ChevronDown className="h-3.5 w-3.5 opacity-50 shrink-0" />
        )}
      </button>

      {/* Body */}
      {!collapsed && children && (
        <div className="border-t border-inherit px-4 py-3">
          {children}
        </div>
      )}
    </div>
  );
}
