import { useEffect, useState } from "react";
import { FileText, Loader2, Save, X } from "lucide-react";
import { Button } from "./ui/button";
import { RequirementsDocEditor } from "./RequirementsDocEditor";
import { REQUIREMENTS_DOC_PLACEHOLDER } from "./requirementsDocEditorExtensions";
import { cn } from "../lib/utils";

export function RequirementsDocDrawer({
  open,
  onClose,
  content,
  onSave,
  saving = false,
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

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/20 backdrop-blur-sm"
        onClick={handleClose}
      />

      <div className="fixed right-0 top-0 z-50 flex h-full w-full max-w-2xl flex-col border-l border-slate-200 bg-white shadow-2xl">
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
          <div className="flex min-w-0 items-center gap-2">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-amber-100 text-amber-700">
              <FileText className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-slate-800">用户需求文档</h2>
              <p className="truncate text-[11px] text-slate-500">
                Markdown 实时预览编辑，保存后 AI 写作时会读取全文
              </p>
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
                  ? "bg-gradient-to-r from-amber-500 to-orange-500 text-white shadow-sm hover:from-amber-400 hover:to-orange-400"
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
              {REQUIREMENTS_DOC_PLACEHOLDER}
            </pre>
          )}
          <RequirementsDocEditor
            value={draft}
            onChange={setDraft}
            disabled={saving}
            className="relative z-10 min-h-0 flex-1"
          />
          <p className="relative z-10 mt-2 shrink-0 text-[11px] text-slate-400">
            {dirty ? "有未保存的修改" : "内容与 AI 对话中的 update_requirements_doc 同步，全量覆盖保存"}
          </p>
        </div>
      </div>
    </>
  );
}
