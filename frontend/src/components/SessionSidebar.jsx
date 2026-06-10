import { useEffect, useRef, useState } from "react";
import {
  MessageSquare,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import { sessionApi } from "../lib/api";

/**
 * Supervisor 会话侧边栏。
 */
export function SessionSidebar({
  workId,
  activeId,
  onSelect,
  onNew,
  collapsed,
  onToggle,
}) {
  const [sessions, setSessions] = useState([]);

  const loadSessions = async () => {
    try {
      const list = await sessionApi.listSupervisor(workId);
      setSessions(list);
    } catch (e) {
      console.error("loadSessions:", e);
    }
  };

  useEffect(() => {
    loadSessions();
  }, [workId]);

  const handleDelete = async (id) => {
    if (!confirm("确定删除这个对话？")) return;
    try {
      await sessionApi.deleteSupervisor(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (activeId === id && onNew) onNew();
    } catch (e) {
      console.error("delete:", e);
    }
  };

  const formatTime = (dateStr) => {
    if (!dateStr) return "";
    const d = new Date(dateStr);
    const now = new Date();
    const isToday =
      d.toDateString() === now.toDateString();
    if (isToday) {
      return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    }
    return d.toLocaleDateString("zh-CN", { month: "short", day: "numeric" });
  };

  if (collapsed) {
    return (
      <div className="flex w-[44px] shrink-0 flex-col items-center border-r border-slate-200 bg-slate-50 py-3 gap-2">
        <button
          onClick={onToggle}
          className="flex h-8 w-8 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-200 hover:text-slate-600"
          title="展开对话列表"
        >
          <MessageSquare className="h-4 w-4" />
        </button>
        <button
          onClick={onNew}
          className="flex h-8 w-8 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-blue-100 hover:text-blue-600"
          title="新对话"
        >
          <Plus className="h-4 w-4" />
        </button>
      </div>
    );
  }

  return (
    <div className="flex w-[220px] shrink-0 flex-col border-r border-slate-200 bg-slate-50">
      <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2">
        <span className="text-xs font-medium text-slate-600">对话</span>
        <div className="flex items-center gap-1">
          <button
            onClick={onNew}
            className="flex h-6 w-6 items-center justify-center rounded text-slate-400 hover:bg-blue-100 hover:text-blue-600"
            title="新对话"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={onToggle}
            className="flex h-6 w-6 items-center justify-center rounded text-slate-400 hover:bg-slate-200 hover:text-slate-600"
            title="收起"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-1.5">
        {sessions.length === 0 ? (
          <p className="px-2 py-4 text-center text-[10px] text-slate-400">
            暂无对话
          </p>
        ) : (
          sessions.map((s) => (
            <div
              key={s.id}
              className={`group mb-0.5 flex items-center rounded-md px-2 py-1.5 cursor-pointer transition-colors ${
                activeId === s.id
                  ? "bg-blue-100 text-blue-800"
                  : "text-slate-600 hover:bg-slate-100"
              }`}
              onClick={() => onSelect(s)}
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-[11px] font-medium leading-4">
                  {s.title}
                </p>
                <p className="text-[9px] text-slate-400">
                  {formatTime(s.updated_at || s.created_at)}
                </p>
              </div>
              <div className="hidden shrink-0 items-center gap-0.5 group-hover:flex">
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDelete(s.id);
                  }}
                  className="rounded p-0.5 text-slate-400 hover:bg-red-50 hover:text-red-500"
                  title="删除"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
