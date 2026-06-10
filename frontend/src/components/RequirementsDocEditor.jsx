import { useState } from "react";
import CodeMirror from "@uiw/react-codemirror";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Eye, Columns2, PenLine } from "lucide-react";
import { buildRequirementsDocExtensions } from "./requirementsDocEditorExtensions";
import { cn } from "../lib/utils";

const extensions = buildRequirementsDocExtensions();

export function RequirementsDocEditor({ value, onChange, disabled = false, className }) {
  const [mode, setMode] = useState("preview");

  const showEditor = mode === "edit" || mode === "split";
  const showPreview = mode === "preview" || mode === "split";

  return (
    <div
      data-testid="requirements-doc-editor"
      className={cn(
        "flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-slate-200 bg-white",
        disabled && "pointer-events-none opacity-60",
        className,
      )}
    >
      <div className="flex shrink-0 items-center justify-end gap-1 border-b border-slate-100 px-2 py-1">
        <button
          type="button"
          onClick={() => setMode("edit")}
          className={cn(
            "inline-flex h-7 items-center gap-1 rounded-md px-2 text-[11px] font-medium transition-colors",
            mode === "edit" ? "bg-slate-800 text-white" : "text-slate-500 hover:bg-slate-100",
          )}
        >
          <PenLine className="h-3 w-3" />
          编辑
        </button>
        <button
          type="button"
          onClick={() => setMode("split")}
          className={cn(
            "inline-flex h-7 items-center gap-1 rounded-md px-2 text-[11px] font-medium transition-colors",
            mode === "split" ? "bg-amber-100 text-amber-900" : "text-slate-500 hover:bg-slate-100",
          )}
        >
          <Columns2 className="h-3 w-3" />
          分屏
        </button>
        <button
          type="button"
          onClick={() => setMode("preview")}
          className={cn(
            "inline-flex h-7 items-center gap-1 rounded-md px-2 text-[11px] font-medium transition-colors",
            mode === "preview" ? "bg-slate-800 text-white" : "text-slate-500 hover:bg-slate-100",
          )}
        >
          <Eye className="h-3 w-3" />
          预览
        </button>
      </div>

      <div
        className={cn(
          "grid min-h-0 flex-1",
          mode === "split" ? "grid-cols-2 divide-x divide-slate-100" : "grid-cols-1",
        )}
      >
        {showEditor && (
          <div className="requirements-doc-cm flex min-h-0 flex-col overflow-hidden">
            <CodeMirror
              value={value}
              height="100%"
              extensions={extensions}
              editable={!disabled}
              onChange={(doc) => onChange?.(doc)}
              basicSetup={{
                lineNumbers: false,
                foldGutter: false,
                highlightActiveLine: true,
              }}
              className="h-full min-h-[240px] flex-1 text-sm leading-relaxed [&_.cm-editor]:h-full [&_.cm-scroller]:font-sans"
            />
          </div>
        )}
        {showPreview && (
          <div
            data-testid="requirements-doc-preview"
            className="requirements-doc-preview min-h-0 overflow-auto bg-slate-50/80 p-3 text-sm leading-relaxed text-slate-800 [&_h1]:mb-2 [&_h1]:text-lg [&_h1]:font-bold [&_h2]:mb-2 [&_h2]:text-base [&_h2]:font-semibold [&_li]:ml-4 [&_li]:list-disc [&_p]:mb-2 [&_strong]:font-semibold [&_ul]:mb-2"
          >
            {value?.trim() ? (
              <Markdown remarkPlugins={[remarkGfm]}>{value}</Markdown>
            ) : (
              <p className="text-slate-400">预览为空</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
