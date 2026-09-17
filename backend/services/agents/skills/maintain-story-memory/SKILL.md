---
name: maintain-story-memory
description: 从完成章节提取摘要、章末状态、新角色、人物变化、关系变化和未决线索，并同步连载记忆。
---

# 维护故事记忆

## 完成标准

- 所有变化均有正文证据并引用正确角色。
- 摘要、章末状态和未决线索可供下一章直接使用。
- 正式关系和角色更新由普通代码工具提交并完成回读。

## 执行流程

1. 使用 `assemble_chapter_context` 和 `stage_existing_chapter_draft` 建立完整输入。必须传入已有 `chapter_node_id`，不得使用新建章节参数。
2. `extract_story_memory` 生成结构化记忆产物。
3. `review_artifact_quality` 检查证据、人物身份和状态一致性。
4. 通过后使用摘要提交、角色节点和关系工具同步结果。
5. 回读章节摘要、相关角色和关系，确认记忆闭环。

