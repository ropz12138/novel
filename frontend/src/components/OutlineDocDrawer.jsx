import { useEffect, useState } from "react";
import { FileText, Loader2, Save, X } from "lucide-react";
import { Button } from "./ui/button";
import { RequirementsDocEditor } from "./RequirementsDocEditor";
import { cn } from "../lib/utils";

export function OutlineDocDrawer({
  open,
  onClose,
  content,
  onSave,
  saving = false,
  title = "文档",
  subtitle = "Markdown 实时预览编辑",
  placeholder = "在左侧输入内容…",
  accentColor = "emerald",
}) {
  const [draft, setDraft] = useState("");
  const saved = content ?? "";
  const dirty = draft !== saved;
  const showPlaceholder = open && !draft.trim();

  useEffect(() => {
    if (open) {
      setDraft(saved);
    }
  }, [open, saved]);

  if (!open) return null;

  const handleClose = () => {
    if (dirty && !window.confirm("有未保存的修改，确定关闭吗？")) return;
    onClose?.();
  };

  const handleSave = () => {
    if (!dirty || saving) return;
    onSave?.(draft);
  };

  const colorMap = {
    emerald: {
      iconBg: "bg-emerald-100 text-emerald-700",
      btn: "from-emerald-500 to-teal-500 hover:from-emerald-400 hover:to-teal-400",
    },
    blue: {
      iconBg: "bg-blue-100 text-blue-700",
      btn: "from-blue-500 to-indigo-500 hover:from-blue-400 hover:to-indigo-400",
    },
    amber: {
      iconBg: "bg-amber-100 text-amber-700",
      btn: "from-amber-500 to-orange-500 hover:from-amber-400 hover:to-orange-400",
    },
  };
  const colors = colorMap[accentColor] || colorMap.emerald;

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/20 backdrop-blur-sm"
        onClick={handleClose}
      />

      <div className="fixed right-0 top-0 z-50 flex h-full w-full max-w-2xl flex-col border-l border-slate-200 bg-white shadow-2xl">
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
          <div className="flex min-w-0 items-center gap-2">
            <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${colors.iconBg}`}>
              <FileText className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
              <p className="truncate text-[11px] text-slate-500">{subtitle}</p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            <button
              type="button"
              onClick={handleSave}
              disabled={!dirty || saving}
              className={cn(
                "inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-xs font-medium transition-all",
                "disabled:cursor-not-allowed disabled:opacity-45",
                dirty
                  ? `bg-gradient-to-r ${colors.btn} text-white shadow-sm`
                  : "bg-slate-100 text-slate-400",
              )}
            >
              {saving ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Save className="h-3.5 w-3.5" />
              )}
              保存
            </button>
            <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={handleClose}>
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>

        <div className="relative flex min-h-0 flex-1 flex-col p-4">
          {showPlaceholder && (
            <pre
              aria-hidden
              className="pointer-events-none absolute left-4 right-4 top-4 z-0 whitespace-pre-wrap text-sm leading-relaxed text-slate-400"
            >
              {placeholder}
            </pre>
          )}
          <RequirementsDocEditor
            value={draft}
            onChange={setDraft}
            disabled={saving}
            className="relative z-10 min-h-0 flex-1"
          />
          <p className="relative z-10 mt-2 shrink-0 text-[11px] text-slate-400">
            {dirty ? "有未保存的修改" : `全量覆盖保存`}
          </p>
        </div>
      </div>
    </>
  );
}
