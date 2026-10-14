---
name: revise-chapter
description: Supervisor 确定当前目标版本，Writer 子 Agent 独立修订正文。
---

# 修改章节

Supervisor 整理作者要求、事实和修改范围，正文由 `run_writing_agent` 委派给独立 Writer。参考规则通过 `read_skill_reference` 按阶段完整加载。
参考文件中的结构化输出格式用于组织工作记录；Writer 提交结果后由运行时校验并保存，用户回复使用 `respond_to_user`。

## 完成标准

修改范围符合作者要求，最终正文与完整章节笔记已保存并回读，相关检查按评审强度完成。

## 执行流程

1. 用 `list_chapters` 获取目录与 catalog_revision，按章节号分批调用 `read_chapter_context` 读取目标和相关前章完整正文，用 `read_chapter_notes` 分别读取笔记，读取相关设定与用户笔记。核对数值收支、能力、伤势、时间地点和人物认知，以来源章节 UUID 和正文证据更新笔记。将本轮作者要求与设计合并进 notes，保留已有有效条目，用 `save_chapter_notes` 保存。
2. 用 `read_skill_reference` 读取 `existing_chapter_revision.txt` 与 `chapter_revision_decision.txt`，自行确定修改范围、原因和方式，并按该决定执行。
   需要调整人物目标、有效阻力、场景顺序或回报设计时，加载 `plan-chapter-scenes`，在作者授权的修改范围内更新完整计划，将其放入 brief.scene_plan；局部措辞修订沿用已有场景设计。
3. 局部修改读取 `chapter_local_edit.txt` 后使用 `run_writing_agent(operation="revise")`；整章重写读取 `chapter_rewrite.txt` 后使用 operation="rewrite"。按审查意见综合修订时读取 `revision.txt`。每次提供相关 source_node_ids 和完整 brief：当前版本场景目标、世界事实、角色已知信息及来源、叙述视角、完整作者要求与 revision_scope。写作运行时自行读取目标章节最新正文并建立并发写入基线。把“改成、后推”等编辑意图转为当前版本的目标事实；版本差异保留在 Supervisor 的工作记录。Writer 独立生成并保存，每次保存后回读。
4. 中、高档加载 `evaluate-fiction`，调用 `run_review_agent`，使用 perspectives=["tired_reader", "ai_taste"] 并行评审修改后的完整正文，汇总有证据的建议后在作者授权范围内统一修订。中档每个视角一次，高档对有实际修改的版本复检；低档完成保存核对。
5. 加载 `maintain-story-memory`，基于最终正文更新完整章节笔记及章末状态，回读核对。
6. 用户要求调整篇幅时调用 `count_chapter_words`，每次任务最多两次篇幅修改，之后报告实际字数和差距。
