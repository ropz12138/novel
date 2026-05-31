import { FileText, X } from "lucide-react";
import { Button } from "./ui/button";

export function RequirementsDocDrawer({ open, onClose, content }) {
  if (!open) return null;

  return (
    <>
      {/* 背景遮罩 */}
      <div
        className="fixed inset-0 z-40 bg-black/20 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* 侧边栏 */}
      <div className="fixed right-0 top-0 z-50 flex h-full w-full max-w-md flex-col border-l border-slate-200 bg-white shadow-xl">
        {/* 头部 */}
        <div className="flex shrink-0 items-center justify-between border-b border-slate-200 px-4 py-3">
          <div className="flex items-center gap-2">
            <FileText className="h-4 w-4 text-slate-500" />
            <h2 className="text-sm font-semibold text-slate-800">用户需求文档</h2>
          </div>
          <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        {/* 内容 */}
        <div className="flex-1 overflow-y-auto p-4">
          {content ? (
            <pre className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
              {content}
            </pre>
          ) : (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <FileText className="mb-3 h-10 w-10 text-slate-300" />
              <p className="text-sm text-slate-400">暂无需求记录</p>
              <p className="mt-1 text-xs text-slate-400">
                在 AI 对话中表达写作需求后，文档会自动更新
              </p>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
