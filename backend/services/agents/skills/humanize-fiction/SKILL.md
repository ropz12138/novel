---
name: humanize-fiction
description: Supervisor 确定自然化目标，独立 Writer 调整句法、节奏、对白与修辞。
---

# 正文自然化

Supervisor 确定调整范围、具体问题和需保留的表达，完整交接给 Writer。参考规则通过 `read_skill_reference` 按阶段完整加载。
正文通过 `compose_chapter` 创作，由现有 `update_node` 协议保存，用户回复使用 `respond_to_user`。

## 完成标准

自然化规则及全文已读取；剧情事实、人物认知和专名保持一致；最终正文、状态已保存并回读。

## 执行流程

1. 用 `read_node_content` 读取已有章节、相关设定和笔记，取得本次 `content_sha256`。
2. 完整读取 `chapter_writer.txt`、`fiction_humanizer.txt` 和 `humanizer_agent.txt`，由 Supervisor 定位句式、节奏、对白和修辞问题。
3. 按最新编号正文，用 `compose_chapter(mode="replace")` 指定单个连续段落范围，完整交接作者原话、修改目标、具体修订意见、需保留事实和表达、相关真实 source_node_ids 与本次 expected_content_sha256。明确的整章重构使用 `compose_chapter(mode="overwrite")`。纯删除和已确定措辞的替换使用 `update_node(mode="replace")`。多处修改依次回读并使用新哈希与编号，保存后核对实际正文和范围外原文。
4. 写章流程调用本技能时，返回写章流程统一处理评审报告与进度。独立自然化任务按评审强度加载 `evaluate-fiction`，通过 `run_review_agent(perspectives=["ai_taste"])` 评审最终正文的表达自然度，中、高档评审与修订次数不限，按实际修改复检。
5. 独立任务执行 `maintain-story-memory` 收尾；嵌入写章任务时由写章流程统一更新完整章节笔记。


异步执行协议：run_review_agent 和 run_reference_agent 派发后返回 task_id。可先处理独立工作，需要等待时单独调用 wait_for_subagents；收到子任务完成通知后，再使用其结果、回读正文和核验任务。运行期间的新要求由 Supervisor 整理，通过 steer_subagent 投递给相关任务。compose_chapter 同步完成 Writer 修订与保存，返回实际结果；Writer 使用本次调用提供的完整材料。
