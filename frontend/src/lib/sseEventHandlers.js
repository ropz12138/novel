/**
 * 纯函数：将 SSE 事件转换为 timeline 操作指令。
 * 用于从组件中抽出可测试的事件处理逻辑。
 */

/**
 * 处理 outline_edit_diff SSE 事件
 */
export function handleOutlineEditDiff(data) {
  const diff = data.diff;
  const summary = data.summary;
  const message = data.message;
  const operations = data.operations;
  const readonly = !!data.readonly;

  return {
    finalizeStep: true,
    setOutlineDiff: {
      diff,
      summary,
      message,
      operations,
      readonly,
    },
    addMessage: {
      role: "assistant",
      content: "",
      meta: {
        type: "outline_diff_card",
        outlineDiffCard: {
          diff,
          summary,
          message,
          operations,
          readonly,
        },
      },
    },
  };
}

/**
 * 处理 character_edit_diff SSE 事件
 */
export function handleCharacterEditDiff(data) {
  const diff = data.diff;
  const summary = data.summary;
  const readonly = !!data.readonly;

  return {
    addMessage: {
      role: "assistant",
      content: "",
      meta: {
        type: "character_diff_card",
        characterDiffCard: {
          diff,
          summary,
          readonly,
        },
      },
    },
  };
}

/**
 * 处理 todolist_generated SSE 事件
 */
export function handleTodolistGenerated(data) {
  return {
    finalizeStep: true,
    addMessage: {
      role: "assistant",
      content: "",
      meta: {
        type: "requirements_todolist",
        todoCard: {
          intent_summary: data.intent_summary || "",
          todolist: (data.todolist || []).map((t) => ({
            db_id: t.db_id || "",
            task_id: t.task_id || t.id || "",
            task: t.task || "",
            owner: t.owner || "supervisor",
            status: t.status || "pending",
            depends_on: t.depends_on || [],
            done_criteria: t.done_criteria || "",
          })),
          ready_to_execute: !!data.ready_to_execute,
        },
      },
    },
  };
}

/**
 * 处理 task_status_updated SSE 事件
 */
export function handleTaskStatusUpdated(data) {
  return {
    type: "task_status_update",
    task_item_id: data.task_item_id || "",
    task_id: data.task_id || "",
    old_status: data.old_status || "",
    new_status: data.new_status || "",
    result_summary: data.result_summary || "",
  };
}

/**
 * 处理 todolist_readiness_updated SSE 事件
 */
export function handleTodolistReadinessUpdated(data) {
  return {
    type: "todolist_readiness_update",
    session_id: data.session_id || "",
    ready_to_execute: !!data.ready_to_execute,
  };
}

/**
 * 工厂函数：返回事件处理方法集合（方便组件调用）
 */
export function createTimelineActions() {
  return {
    handleOutlineEditDiff,
    handleCharacterEditDiff,
    handleTodolistGenerated,
    handleTaskStatusUpdated,
    handleTodolistReadinessUpdated,
  };
}
