---
name: write-chapter
description: Supervisor 规划与协调修订，独立 Writer 写作，Reviewer 评审阅读体验。
---

# 写作章节工作流

Supervisor 负责规划、评审决策和记忆，阅读评审通过 `run_review_agent`，正文由 `run_writing_agent` 委派给独立 Writer。参考规则通过 `read_skill_reference` 按阶段完整加载。
参考文件中的结构化输出格式用于组织工作记录；Writer 提交正文后由运行时校验并保存，用户回复使用 `respond_to_user`。

## 完成标准

完整上下文和笔记已读取；场景因果明确；正文和角色信息已保存；按评审强度完成检查；完整章节笔记与状态已保存和回读。

## 执行流程

1. 用 `get_canvas_index` 与 `read_node_content` 读取用户笔记、世界观、角色、所属结构、前文和已有目标章节的正文与笔记。新章使用 `create_node` 建 chapter，用 `create_edge` 建立 plot→chapter 父子关系。
2. 场景规划前用 `list_chapters` 读取目录与 catalog_revision，按章节号分批调用 `read_chapter_context` 读取相关前章及目标章节完整正文，用 `read_chapter_notes` 读取完整笔记；每个 session 从作品持久数据重建事实。为缺少笔记的前章补齐有正文依据的事实，保留已有作者要求与设计。核对数量收支、人物能力与认知、伤势、时间地点、物品归属和未决线索，逐项记录来源章节 UUID 和正文证据。冲突需要作者决定时先确认。
3. 用 `load_workflow_skill` 加载 `plan-chapter-scenes`，按该技能完整读取 `scene_plan.txt`。Supervisor 先完成章节“大方向”：确定叙事功能、目标体验、节奏强度、参与人物、开篇状态、目标章末状态并核对相邻章节节奏。当工具集中存在 `run_reference_agent`，且作者、既有大纲和章节笔记尚未给出完整具体事件链时，在展开场景事件前调用它；提交上述大方向、当前故事事实和小说 ID，由它从上传小说提供带来源的具体事件候选、叙事机制与适配方向。Supervisor 比较并选择、组合、本作化候选，最终落实为事件因果、情绪曲线、有效阻力、参与者目的、关键选择及局势变化。用 `save_chapter_notes(chapter_node_id, notes=完整章节笔记, expected_content_sha256=回读值)` 保存笔记；笔记包含章节摘要、作者要求、完整创作设计和连续性数据，待写事件明确标记为计划。完整计划交接到 brief.scene_plan，具体文学表达由 Writer 完成。
4. 创建确有必要的新角色，用 `update_node` 把场景标题和目的写入 `chapter_elements`、真实角色 id/name 写入 `characters`。
5. 完整加载 `chapter_writer.txt`，把当前版本的场景计划、世界事实、逐人已知信息及来源、叙述视角、完整作者要求和写作范围整理为 brief，相关前章/角色/世界观 UUID 放入 source_node_ids。编辑历史保留在 Supervisor，brief 表达当前目标状态。用 `run_writing_agent(operation="write", chapter_node_id, source_node_ids, brief)` 写空章；已有正文整体重构使用 operation="rewrite"。工具启动时自行读取目标章节最新正文并建立并发写入基线，独立生成并保存后，用 `read_node_content` 回读实际正文。
6. 低档进入第 10 步。中、高档加载 `evaluate-fiction`，调用 `run_review_agent`，提供目标章节、完整作者要求与相关来源，使用 perspectives=["tired_reader", "ai_taste"] 并行评审阅读体验与表达自然度。保留报告对应的正文哈希、阅读感受、所需元素与具体问题。中档每个视角一次，高档针对实际修改后的最新正文复检。
7. 根据报告与作者要求判断值得采纳的建议，区分表达问题与场景设计问题。自然化适用于作者明确提出或报告定位到的具体表达问题，此时加载 `humanize-fiction` 并交给 Writer 执行。
8. 汇总本章全部检查结果，读取 `chapter_revision_decision.txt`，自行选择局部修改、整章重写或场景重规划，并按该决定执行。
9. 局部修改完整读取 `chapter_local_edit.txt`，用 `run_writing_agent(operation="revise")`；整章重写读取 `chapter_rewrite.txt` 后使用 operation="rewrite"；场景重规划加载 `plan-chapter-scenes` 并读取 `chapter_replan.txt`，保存新计划及后续承接，再交给 Writer 生成正文。每次交接使用完整当前 brief，目标正文和并发写入基线由写作运行时读取建立，保存后回读。高档调用评审子 Agent 复检最新正文，直到具体问题解决或剩余建议无需采纳；中档汇总修改后进入收尾。
10. 加载 `maintain-story-memory`，基于回读的最终正文更新完整章节笔记和章末状态，使用其保存步骤同步笔记、角色变化及未决线索，再回读确认。
11. 篇幅按用户要求安排，可用 `count_chapter_words` 报告实际字数。用户明确要求调整时读取 `chapter_length_advice.txt`，每次任务最多进行两次篇幅修改，随后说明剩余差距。
