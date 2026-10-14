---
name: humanize-fiction
description: Supervisor 确定自然化目标，Writer 独立调整句法、节奏、对白与修辞。
---

# 正文自然化

Supervisor 负责确定调整范围，Writer 子 Agent 负责正文表达。参考规则通过 `read_skill_reference` 按阶段完整加载。
正文通过 `run_writing_agent` 独立修改并保存，用户回复使用 `respond_to_user`。

## 完成标准

自然化规则及全文已读取；剧情事实、人物认知和专名保持一致；最终正文、状态已保存并回读。

## 执行流程

1. 用 `read_node_content` 读取已有章节、相关设定和笔记。
2. 完整读取本技能 `fiction_humanizer.txt` 和 `humanizer_agent.txt`，亲自定位句式、节奏、对白和修辞问题。
3. 将当前有效事实、人物认知来源、叙述视角、完整文风要求与修改范围交接为 brief，提供相关 source_node_ids，调用 `run_writing_agent(operation="humanize")` 精确修改片段；写作运行时自行读取最新正文并建立并发写入基线，随后回读最新正文。整章重构使用 operation="rewrite" 并保留完整自然化要求。
4. 写章流程调用本技能时，返回写章流程统一处理评审报告与进度。独立自然化任务按评审强度加载 `evaluate-fiction`，通过 `run_review_agent(perspectives=["ai_taste"])` 评审最终正文的表达自然度，中档每个视角一次，高档按实际修改复检。
5. 独立任务执行 `maintain-story-memory` 收尾；嵌入写章任务时由写章流程统一更新完整章节笔记。
