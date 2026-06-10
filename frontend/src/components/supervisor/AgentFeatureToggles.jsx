export function AgentFeatureToggles({
  enableTodolist,
  enableEvaluation,
  onEnableTodolistChange,
  onEnableEvaluationChange,
  disabled = false,
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <label
        className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors ${
          enableTodolist
            ? "border-amber-200 bg-amber-50 text-amber-800"
            : "border-slate-200 bg-white text-slate-500"
        } ${disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer hover:border-amber-300"}`}
      >
        <input
          type="checkbox"
          className="sr-only"
          checked={enableTodolist}
          disabled={disabled}
          onChange={(e) => onEnableTodolistChange(e.target.checked)}
        />
        任务清单
      </label>
      <label
        className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors ${
          enableEvaluation
            ? "border-violet-200 bg-violet-50 text-violet-800"
            : "border-slate-200 bg-white text-slate-500"
        } ${disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer hover:border-violet-300"}`}
      >
        <input
          type="checkbox"
          className="sr-only"
          checked={enableEvaluation}
          disabled={disabled}
          onChange={(e) => onEnableEvaluationChange(e.target.checked)}
        />
        章节评估
      </label>
    </div>
  );
}
