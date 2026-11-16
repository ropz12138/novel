# 需求分析、任务清单与动态评审

本次运行目录为 `/root/Novel`。需求分析由 Supervisor 在本轮上下文中完成，不再登记分析产物，也不再要求快照 ID。保留 Supervisor / Writer / Reviewer 的现有分工。无数据库迁移。

## 执行流程

1. 事实询问用现有读取工具查看相关最新内容后直接回答。创作和修改先明确目标、范围和关键分歧；方向明确时用 `write_todolist` 建立自然语言任务。继续既有工作时先 `read_todolist`，再用 `update_todolist` 调整。
2. 长期文风、审美、创作限制和评审规则先作为清单第一项，再由 `create_node` 或 `update_node` 写入 `note` / `reviewer_note`。一次性修改留在当轮任务中。章节笔记继续记录事实和连续性信息。
3. 写入后回读最新内容，并按现有 Writer / Reviewer 流程核对。普通任务完成由 Supervisor 根据实际工具结果更新清单。
4. 规划关键情节时，Supervisor 在本轮说明角色行动理由，并写入交给 Writer 的任务说明。作品身份来自当前运行上下文。
5. 本轮调用过任务清单后，`respond_to_user(outcome="completed")` 要求清单中没有 pending。`needs_user` 与 `needs_revision` 可以留下未完成任务。未参与清单的事实回答不受历史未完成任务阻塞。

已取消的能力：分析产物强制验收、结构化任务依赖图、`request_intent` 写入门禁，以及用分析 ID 完成任务。这些能力没有用空产物或默认成功伪装保留。

## 评审笔记

每次 `run_review_agent` 直接加载当前普通笔记、章节笔记和专用评审笔记。章节笔记带所属章节、标题、类型和适用范围。评审期间这些笔记或目标正文发生变化时返回冲突，下一轮读取最新原文。内部评审不再生成派生准则产物。

劳累读者和 AI 味 Reviewer 阅读同一份当前笔记。评审期间的作品变化会返回冲突，避免把旧报告当成当前结果。

中、高强度评审和修订不限循环次数；低强度保留原有流程。页面使用项目的 Todolist 事件与历史卡片，关闭 Deep Agents 内部待办工具。

## 开发环境

由用户在开发工作树执行。准备脚本保留已有开发配置；启动脚本会安装依赖，并处理开发端口上的旧进程。

```bash
cd /root/Novel
python3 scripts/prepare_canvas_dev.py
./scripts/start_canvas_dev.sh
```

不要用生产启动脚本代替开发验收。
