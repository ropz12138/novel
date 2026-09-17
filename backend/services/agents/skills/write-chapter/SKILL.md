---
name: write-chapter
description: 创作或续写完整小说章节时，统筹结构化场景规划、正文生成、连续性审查、对白审查、定向修订、摘要与最终保存。
---

# 写作章节工作流

本技能由 Supervisor 加载并统筹执行。专职 Agent 负责文学任务，普通代码工具负责上下文、结构校验、版本与保存。

## 完成标准

- 已装配目标章节所需的完整作品上下文。
- 场景规划包含明确的场景次序、人物、动作与对白目的，预计篇幅与目标相符。
- 正文覆盖场景计划并形成完整开场、发展和结尾。
- 按本次评审强度完成相应评审和修订。
- 最终正文、章节摘要和必要的角色信息已保存，并完成回读确认。

## 执行流程

1. 调用 `assemble_chapter_context`，获得 `chapter_context` 产物。已有章节只传 `chapter_node_id`。尚无章节节点时传 `parent_node_id`（必须是 plot）、`chapter_title`、`sort_order`；工具会创建空章节并建立 plot→chapter 的 contains 连线，再装配上下文。两组参数互斥，禁止先用 `create_node` 建章。
2. 调用 `plan_chapter_scenes`，获得 `scene_plan` 产物。
3. 根据场景计划创建确有必要的新角色，再调用 `prepare_chapter_from_scene_plan`，传入场景计划产物 ID 和全部出场角色节点 ID，由工具将情节单元与出场角色确定性同步到章节的 `chapter_elements`、`characters`；该步骤保持章节 `content` 不变。
4. `scene_plan_ready` 后调用 `write_chapter_draft`；生成正文直接写入已存在的章节节点，草稿产物记录完整版本供评审。
5. 先处理初稿字数质量门。允许范围为目标字数的 85%—115%；超出范围时，写作工具会在内部调用一次篇幅顾问并返回 `revision_advice`。字数合格后按本次评审强度执行：低档进入摘要和提交；中档对同一草稿版本各调用一次 `review_chapter_continuity` 与 `review_chapter_dialogue`，汇总反馈；高档对同一草稿版本调用两项评审，并按结果修订和复检。
6. 初稿字数质量门、审查或提交返回 `needs_revision` 时，调用 `decide_chapter_revision`。传入当前场景计划、最新草稿、字数反馈、工具返回的 `revision_advice` 和相关审查产物 ID；工具会读取完整审查内容，由决策 Agent 选择 `replan`、`rewrite` 或 `local_edit`，并说明原因与执行要求。高档每出现新一轮修改需求，都对最新草稿重新决策；中档汇总两项评审的问题后决策一次、修订一次。
7. `replan`：调用 `replan_chapter_scenes` 重新划定本章范围；使用新计划同步章节结构，再调用 `write_chapter_draft` 生成新稿。保留 `deferred_scenes` 与 `next_chapter_handoff` 供下一章承接。`rewrite`：调用 `rewrite_chapter_draft` 生成完整新稿。`local_edit`：调用 `edit_chapter_draft_locally`，通过唯一原文片段替换得到新草稿，正文其他部分保持原样。
8. 修订后检查最新草稿字数。高档复检本轮涉及的审查项，若仍需修改，回到第 6 步；每次复检必须引用最新草稿版本。中档在一次合并修订后直接进入摘要与提交。
9. 调用 `summarize_chapter_draft` 生成摘要及章末状态。
10. 调用 `commit_chapter_workflow_result`，携带上下文产物返回的 `source_content_sha256` 固化通过验收版本的摘要与状态；随后使用 `read_node_content` 重新读取真实章节核对结果。返回修改需求时，对最新版本重新执行第 6 步，并重新生成摘要。

## 状态处理

- `completed`：读取 `gate.code` 并继续技能规定的下一步。
- `needs_revision`：按审查产物执行定向修订和复检。
- `needs_user`：保留现有产物，向用户说明需要决定的冲突及其影响，当前任务保持未完成。
- `failed`：报告失败阶段和结构化错误；已有中间产物保持可恢复。

专业 Reviewer 提供判断、证据和修改目标；Revision Agent 生成新版本。高档以复检结果判断评审通过与否，中档在一次合并修订后完成流程。
