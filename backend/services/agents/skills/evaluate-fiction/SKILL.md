---
name: evaluate-fiction
description: 只读评估章节、设定、大纲、角色或多章文本的逻辑、人物、节奏、对白和阅读体验。
---

# 评估小说内容

## 完成标准

- 评估对象和上下文范围明确。
- 问题包含定位、证据、影响和可执行建议。
- 评估产物可追踪且未修改正式节点。

## 执行流程

1. 章节评估使用 `assemble_chapter_context` 和 `stage_existing_chapter_draft`，必须传入已有 `chapter_node_id`，不得使用新建章节参数；其他内容使用 `assemble_work_context`。
2. 调用 `review_fiction_quality`；涉及对白或章间衔接时复用对应 Reviewer。
3. 多章或全书任务调用 `review_novel_coherence`。
4. 汇总 Artifact 引用和核心结论。只有用户另行要求修改时，才进入对应修订 Skill。

