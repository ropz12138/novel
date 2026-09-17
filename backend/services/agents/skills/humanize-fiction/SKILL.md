---
name: humanize-fiction
description: 对章节正文进行自然化编辑，改善句法、节奏、对白和修辞，同时保持故事事实与系统标记。
---

# 正文自然化

## 完成标准

- 完整自然化规则和目标正文均已加载。
- 新草稿保持人物认知、剧情事实、专名、伏笔和系统标记。
- 自然化结果直接写入真实章节节点，并完成自然度与事实保真审查。

## 执行流程

1. `assemble_chapter_context` 与 `stage_existing_chapter_draft` 建立完整输入。必须传入已有 `chapter_node_id`，不得使用新建章节参数。
2. 调用 `humanize_chapter_draft`，工具完整加载自然化规则、更新真实章节节点并记录新版本。
3. 调用 `review_fiction_quality`；对白改动明显时同时调用 `review_chapter_dialogue`。
4. 根据质量门修订并复检最新版本。
5. 生成摘要，固化状态并回读核对。
