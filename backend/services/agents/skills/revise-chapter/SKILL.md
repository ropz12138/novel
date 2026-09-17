---
name: revise-chapter
description: 按作者要求局部修改、扩写、删改或重写已有章节，并保留未授权变化之外的故事事实。
---

# 修改章节

## 完成标准

- 修改范围与作者要求一致，真实章节正文更新并形成可追踪版本。
- 相关连续性、对白和综合质量检查通过。
- 用户修改并发冲突得到明确处理，最终版本已提交和回读。

## 执行流程

1. `assemble_chapter_context` 装配完整上下文，`stage_existing_chapter_draft` 保存原文版本。必须传入已有 `chapter_node_id`，不得使用新建章节参数。
2. `revise_existing_chapter_draft` 根据用户完整要求直接更新真实章节节点，并记录新版本。
3. 按修改类型调用 `review_chapter_continuity`、`review_chapter_dialogue` 或 `review_fiction_quality`。
4. 未通过时使用审查产物再次定向修订并复检最新版本。
5. `summarize_chapter_draft` 更新状态摘要，`commit_chapter_workflow_result` 固化摘要和状态并回读。
