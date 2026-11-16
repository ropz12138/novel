---
name: revise-chapter
description: Supervisor 确定当前目标版本，并直接修订章节正文。
---

# 修改章节

Supervisor 整理作者要求、事实和修改范围，并直接修订正文。参考规则通过 `read_skill_reference` 按阶段完整加载。
参考文件中的结构化输出格式用于组织工作记录；正文通过 `update_node` 保存，用户回复使用 `respond_to_user`。

## 新增内容的参考前置

修订涉及新增场景、事件、人物、设定或重新设计情节时，Supervisor 先确定修改范围与目标。工具集中有 `run_reference_agent` 时完成本轮调用。取回章节原文后完成选择和本作化，再直接修订正文。本轮未取回章节原文时，沿用作者已确认的事件与设定直接修订正文。将来源和适配结论放入完整修订任务。纯事实纠错、术语统一和既有表达的整理按原修订流程执行。

## 完成标准

修改范围符合作者要求，最终正文与完整章节笔记已保存并回读，相关检查按评审强度完成。

## 执行流程

1. 用 `list_chapters` 获取目录与 catalog_revision，按章节号分批调用 `read_chapter_context` 读取目标和相关前章完整正文，用 `read_chapter_notes` 分别读取笔记，读取相关设定与用户笔记。核对数值收支、能力、伤势、时间地点和人物认知，以来源章节 UUID 和正文证据简明更新续写所需状态，核对过程留在当前任务记录中。将持续适用于本章的作者要求与设计写入 notes，本轮一次性修改范围写在任务清单中。保留全部有效条件、关键因果和待执行计划，同义条目合并，以当前有效决定表达纠错，用 `save_chapter_notes` 保存。
2. 用 `read_skill_reference` 读取 `chapter_writer.txt`、`existing_chapter_revision.txt` 与 `chapter_revision_decision.txt`，自行确定修改范围、原因和方式，并按该决定执行。
   需要调整人物目标、有效阻力、场景顺序或回报设计时，加载 `plan-chapter-scenes`，在作者授权的修改范围内更新完整计划，将其写入当前任务说明；局部措辞修订沿用已有场景设计。
3. 局部修改读取 `chapter_local_edit.txt` 后使用 `update_node(mode="replace")`；整章重写读取 `chapter_rewrite.txt` 后使用 `update_node(mode="overwrite")`。按审查意见综合修订时读取 `revision.txt`。动笔前读取目标章节最新编号全文，提交本次读取的 `content_sha256`。任务说明按需要写入当前版本场景目标、世界事实、角色已知信息及来源、叙述视角、完整作者要求与修改范围。核对已注入笔记的最新原文，按条目内容和适用范围使用。把“改成、后推”等编辑意图转为当前版本的目标事实；版本差异保留在当前工作记录。每次保存后回读。
4. 中、高档加载 `evaluate-fiction`，调用 `run_review_agent`，使用 perspectives=["tired_reader", "ai_taste"] 并行评审修改后的完整正文，汇总有证据的建议后在作者授权范围内统一修订。中、高档评审与修订次数不限，对有实际修改的最新版本复检；低档完成保存核对。
5. 加载 `maintain-story-memory`，基于最终正文更新完整章节笔记及章末状态，回读核对。
6. 整章重写默认 2000 字左右，作者指定其他篇幅时采用作者要求。保存后调用 `count_chapter_words`，expected_word_count 使用本次采用的篇幅。每次任务最多两次篇幅修改，之后报告实际字数和差距。局部修改保持本章既有篇幅。


异步执行协议：run_review_agent 和 run_reference_agent 派发后返回 task_id。可先处理独立工作，需要等待时单独调用 wait_for_subagents；收到子任务完成通知后，再使用其结果、回读正文和核验任务。运行期间的新要求由 Supervisor 整理，通过 steer_subagent 投递给相关任务。章节正文在当前上下文编写，并用 update_node 保存。
