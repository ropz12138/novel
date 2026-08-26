export function normalizeTodoItem(item = {}) {
  return {
    db_id: item.db_id || "",
    task_id: item.task_id || item.id || "",
    task: item.task || "",
    owner: item.owner || "supervisor",
    status: item.status || "pending",
    parent_id: item.parent_id || "",
    depth: Number(item.depth || 0),
    agent_scope: item.agent_scope || "",
    depends_on: item.depends_on || [],
    done_criteria: item.done_criteria || "",
    task_type: item.task_type || "",
    dispatch_tool: item.dispatch_tool || "",
    instruction: item.instruction || "",
    result_summary: item.result_summary || "",
    error_message: item.error_message || "",
  };
}
