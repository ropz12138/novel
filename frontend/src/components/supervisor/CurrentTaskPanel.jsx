import { useState } from "react";
import { ChevronDown, ListChecks } from "lucide-react";
import { RequirementsTodoCard } from "../agent/RequirementsTodoCard";

export function CurrentTaskPanel({ timeline }) {
  const latest = [...timeline].reverse().find(item => item.type === "requirements_todolist" && item.todoCard);
  if (!latest) return null;
  return <TaskProgress key={latest.id} item={latest} />;
}

function TaskProgress({ item }) {
  const [expanded, setExpanded] = useState(false);
  const card = item.todoCard;
  const tasks = card.todolist || [];
  const completed = tasks.filter(task => task.status === "completed").length;
  const unfinished = tasks.filter(task => !["completed", "skipped"].includes(task.status));
  const waiting = card.delivery_status === "needs_user"
    || unfinished.some(task => task.waiting_for_decision)
    || card.ready_to_execute === false;
  const status = tasks.length && !unfinished.length ? "全部完成"
    : waiting ? "等待你确认"
    : card.delivery_status === "needs_revision" || unfinished.some(task => task.status === "failed") ? "需要处理"
    : unfinished.some(task => task.status === "in_progress") ? "进行中" : "待处理";
  return (
    <section aria-label="当前任务" className="relative shrink-0 border-b border-blue-100 bg-blue-50/60">
      <button type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-slate-700">
        <ListChecks className="h-4 w-4 shrink-0 text-blue-500" />
        <span className="min-w-0 flex-1 truncate">{card.intent_summary || "当前任务"}</span>
        <span className="shrink-0">已完成 {completed}/{tasks.length} · {status}</span>
        <ChevronDown className={`h-3.5 w-3.5 shrink-0 ${expanded ? "rotate-180" : ""}`} />
      </button>
      {expanded && (
        <div className="max-h-[45vh] overflow-y-auto overscroll-contain border-t border-blue-100 bg-white p-3">
          <RequirementsTodoCard todoCard={card} />
        </div>
      )}
    </section>
  );
}
