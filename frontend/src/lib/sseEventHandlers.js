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
          todolist: data.todolist || [],
          ready_to_execute: !!data.ready_to_execute,
        },
      },
    },
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
  };
}
