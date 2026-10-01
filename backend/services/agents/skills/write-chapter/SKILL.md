---
name: write-chapter
description: 创作或续写完整小说章节时，统筹结构化场景规划、正文生成、连续性审查、对白审查、定向修订、摘要与最终保存。
---

# 写作章节工作流

本技能由 Supervisor 加载并统筹执行。专职 Agent 负责文学任务，普通代码工具负责上下文、结构校验、版本与保存。

## 完成标准

- 已装配目标章节所需的完整作品上下文。
- 已遵守 `global_context` 中的全部 `note` 条目。
- 场景规划包含明确的场景次序、人物、客观事件、人物目标、已知信息、行为选择、后果与对白目标；具体小说措辞由正文阶段完成。
- 正文覆盖场景计划并形成完整开场、发展和结尾。
- 按本次评审强度完成相应评审和修订。
- 最终正文、章节摘要和必要的角色信息已保存，并完成回读确认。

## 执行流程

1. 调用 `assemble_chapter_context`，获得 `chapter_context` 产物。已有章节只传 `chapter_node_id`。尚无章节节点时传 `parent_node_id`（必须是 plot）、`chapter_title`、`sort_order`；工具会创建空章节并建立 plot→chapter 的 contains 连线，再装配上下文。两组参数互斥，禁止先用 `create_node` 建章。
2. 调用 `plan_chapter_scenes`，获得 `scene_plan` 产物。场景计划只承担事实与因果规划，不承担小说化成句、解释性心理、内心独白或修辞表达。
3. 根据场景计划创建确有必要的新角色，再调用 `prepare_chapter_from_scene_plan`，传入场景计划产物 ID 和全部出场角色节点 ID，由工具将情节单元与出场角色确定性同步到章节的 `chapter_elements`、`characters`；该步骤保持章节 `content` 不变。
4. `scene_plan_ready` 后调用 `write_chapter_draft`；生成正文直接写入已存在的章节节点，草稿产物记录完整版本供评审。
5. 按本次评审强度执行：低档不调用任何评审工具，进入摘要和提交；中档每个评审工具最多调用一次，汇总自然语言建议；高档评审次数不限，按值得采纳的建议修订并复检最新草稿，直到建议无需采纳或评审 Agent 明确认为文本已经优秀。针对同一版 `chapter_draft` 且相互独立的多个只读评审，在同一次响应中并行调用对应评审工具，全部返回后统一进入修订决策。可用 `count_chapter_words` 查看篇幅，不要把字数区间当作完成条件，不要自动循环压缩篇幅。
6. Supervisor 阅读评审建议和证据，自行判断哪些建议值得采纳。决定修改时调用 `decide_chapter_revision`，传入当前场景计划、最新草稿和相关评审产物 ID；由决策 Agent 选择 `replan`、`rewrite` 或 `local_edit`，并说明原因与执行要求。若仅因篇幅返回 `needs_revision`，向用户说明工具给出的字数与建议，等待用户是否要求调整篇幅。
7. `replan`：调用 `replan_chapter_scenes` 重新划定本章范围；使用新计划同步章节结构，再调用 `write_chapter_draft` 生成新稿。保留 `deferred_scenes` 与 `next_chapter_handoff` 供下一章承接。`rewrite`：调用 `rewrite_chapter_draft` 生成完整新稿。`local_edit`：调用 `edit_chapter_draft_locally`，通过唯一原文片段替换得到新草稿，正文其他部分保持原样。
8. 高档对本轮涉及的评审项复检最新草稿，再由 Supervisor 判断新建议是否值得采纳；值得采纳时回到第 6 步。中档不再次调用已使用的评审工具。
9. 评审强度为中或高时，对已有 `chapter_context` 和最新 `chapter_draft` 执行去 AI 味：调用 `humanize_chapter_draft`，取得自然化后的最新草稿，再在同一次响应中并行调用 `review_fiction_quality` 和 `review_chapter_ai_taste`。Supervisor 汇总两项自然语言建议后决定是否修订；中档遵守每个评审工具最多一次，高档可对最新草稿继续并行复检。低强度写章流程跳过本步。
10. 调用 `summarize_chapter_draft` 生成摘要及章末状态。
11. 调用 `commit_chapter_workflow_result`，携带上下文产物返回的 `source_content_sha256` 固化通过验收版本的摘要与状态；随后使用 `read_node_content` 重新读取真实章节核对结果。内容质量仍需修订时，对最新版本重新执行第 6 步并重新生成摘要。

## 状态处理

- `completed`：读取 `gate.code` 并继续技能规定的下一步。
- `needs_revision`：用于非评审工具的流程失败或篇幅提示；评审工具自身不判定是否需要修订。
- `needs_user`：保留现有产物，向用户说明需要决定的冲突及其影响，当前任务保持未完成。
- `failed`：报告失败阶段和结构化错误；已有中间产物保持可恢复。

专业 Reviewer 提供自然语言建议与证据；Supervisor 决定采纳项；Revision Agent 生成新版本。
