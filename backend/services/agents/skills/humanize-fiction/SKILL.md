---
name: humanize-fiction
description: Supervisor 确定自然化目标，并直接调整句法、节奏、对白与修辞。
---

# 正文自然化

Supervisor 确定调整范围并直接修改正文表达。参考规则通过 `read_skill_reference` 按阶段完整加载。
正文通过 `update_node` 保存，用户回复使用 `respond_to_user`。

## 完成标准

自然化规则及全文已读取；剧情事实、人物认知和专名保持一致；最终正文、状态已保存并回读。

## 执行流程

1. 用 `read_node_content` 读取已有章节、相关设定和笔记，取得本次 `content_sha256`。
2. 完整读取 `chapter_writer.txt`、`fiction_humanizer.txt` 和 `humanizer_agent.txt`，亲自定位句式、节奏、对白和修辞问题。
3. 按最新编号正文，用 `update_node(mode="replace")` 精确修改片段，提交本次读取的 `content_sha256`，保留作者原话中的条件与程度。整章重构读取规则后使用 `update_node(mode="overwrite")`。保存后回读最新正文。
4. 写章流程调用本技能时，返回写章流程统一处理评审报告与进度。独立自然化任务按评审强度加载 `evaluate-fiction`，通过 `run_review_agent(perspectives=["ai_taste"])` 评审最终正文的表达自然度，中、高档评审与修订次数不限，按实际修改复检。
5. 独立任务执行 `maintain-story-memory` 收尾；嵌入写章任务时由写章流程统一更新完整章节笔记。


异步执行协议：run_review_agent 和 run_reference_agent 派发后返回 task_id。可先处理独立工作，需要等待时单独调用 wait_for_subagents；收到子任务完成通知后，再使用其结果、回读正文和核验任务。运行期间的新要求由 Supervisor 整理，通过 steer_subagent 投递给相关任务。章节正文在当前上下文编写，并用 update_node 保存。
