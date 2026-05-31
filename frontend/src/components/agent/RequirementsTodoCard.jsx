import { useState } from "react";

const STATUS_META = {
  pending: { icon: "○", text: "待处理", color: "text-slate-400", box: "border-slate-200 bg-white" },
  in_progress: { icon: "◑", text: "进行中", color: "text-blue-500", box: "border-blue-200 bg-blue-50/50" },
  completed: { icon: "✓", text: "已完成", color: "text-emerald-500", box: "border-emerald-200 bg-emerald-50/50" },
  skipped: { icon: "⊘", text: "已跳过", color: "text-slate-300", box: "border-slate-200 bg-slate-50" },
  failed: { icon: "✗", text: "失败", color: "text-red-500", box: "border-red-200 bg-red-50/50" },
};

function buildTodoTree(tasks) {
  const normalized = tasks.map((task, idx) => ({ ...task, _idx: idx, children: [] }));
  const byId = new Map();
  normalized.forEach((task) => {
    if (task.db_id) byId.set(task.db_id, task);
  });

  const roots = [];
  normalized.forEach((task) => {
    const parentId = task.parent_id || "";
    const parent = parentId ? byId.get(parentId) : null;
    if (parent) {
      parent.children.push(task);
    } else {
      roots.push(task);
    }
  });
  return roots;
}

function TodoTaskNode({ task, fallbackId, level = 0 }) {
  const status = task.status || "pending";
  const meta = STATUS_META[status] || STATUS_META.pending;
  const isChild = level > 0;
  const hasChildren = task.children?.length > 0;
  const [expanded, setExpanded] = useState(false);

  return (
    <div className={isChild ? "ml-4 border-l border-slate-200 pl-3" : ""}>
      <div className={`rounded-lg border p-2.5 ${meta.box}`}>
        <div className="flex items-center gap-2 text-xs">
          <span className={`text-sm ${meta.color}`}>{meta.icon}</span>
          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-600">
            {task.task_id || fallbackId}
          </span>
          <span className={`font-medium ${status === "completed" ? "text-slate-400 line-through" : "text-slate-700"}`}>
            {task.task || "未命名任务"}
          </span>
          {hasChildren && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="ml-auto flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors"
            >
              {expanded ? "收起" : `${task.children.length}个子步骤`}
              <svg
                className={`h-3 w-3 transition-transform ${expanded ? "rotate-180" : ""}`}
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </button>
          )}
        </div>
        <div className="mt-1 space-y-1 text-[11px] text-slate-500">
          <p>负责人：{task.owner || task.agent_scope || "supervisor"}</p>
          <p>状态：{meta.text}</p>
          {task.dispatch_tool && task.dispatch_tool !== "none" && (
            <p>工具：{task.dispatch_tool}</p>
          )}
          {Array.isArray(task.depends_on) && task.depends_on.length > 0 && (
            <p>依赖：{task.depends_on.join(", ")}</p>
          )}
          {task.done_criteria && <p>验收：{task.done_criteria}</p>}
          {task.error_message && <p className="text-red-600">错误：{task.error_message}</p>}
        </div>
      </div>
      {hasChildren && expanded && (
        <div className="mt-2 space-y-2">
          {task.children.map((child, idx) => (
            <TodoTaskNode
              key={`${child.db_id || child.task_id || "child"}-${idx}`}
              task={child}
              fallbackId={`${task.task_id || "T"}.${idx + 1}`}
              level={level + 1}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function RequirementsTodoCard({ todoCard }) {
  const tasks = todoCard?.todolist || [];
  const tree = buildTodoTree(tasks);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-slate-700">需求任务清单</p>
        <span
          className={`rounded-full px-2 py-0.5 text-[10px] ${
            todoCard?.ready_to_execute
              ? "bg-emerald-100 text-emerald-700"
              : "bg-amber-100 text-amber-700"
          }`}
        >
          {todoCard?.ready_to_execute ? "可执行" : "待澄清"}
        </span>
      </div>
      {todoCard?.intent_summary && (
        <p className="text-xs text-slate-600">目标：{todoCard.intent_summary}</p>
      )}
      {tasks.length > 0 ? (
        <div className="space-y-2">
          {tree.map((task, idx) => (
            <TodoTaskNode
              key={`${task.db_id || task.task_id || "T"}-${idx}`}
              task={task}
              fallbackId={`T${idx + 1}`}
            />
          ))}
        </div>
      ) : (
        <p className="text-xs text-slate-500">暂无任务项。</p>
      )}
    </div>
  );
}
