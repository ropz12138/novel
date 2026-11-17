---
name: write-chapter
description: Supervisor 规划并交接，独立 Writer 创作正文，Reviewer 评审阅读体验。
---

# 写作章节工作流

Supervisor 负责规划、Writer 交接、评审决策和记忆，正文创作通过 `compose_chapter`，阅读评审通过 `run_review_agent`。参考规则通过 `read_skill_reference` 按阶段完整加载。
参考文件中的结构化输出格式用于组织工作记录；Writer 通过现有 `update_node` 协议保存章节正文，用户回复使用 `respond_to_user`。

## 创作参考前置

新内容设计与创作的必经环节是参考研究。Supervisor 先确定范围、目标体验及作者约束，工具集中有 `run_reference_agent` 时，本轮实际调用它。取回章节原文后完成本作化，再形成具体方案并交接给 Writer。作者已有完整方案时，检索围绕其已确认内容取回相关章节原文。本轮未取回章节原文时，按当前作品已有事实、作者已确认的事件与设定完成本轮方案与正文。同一轮同一范围沿用本轮已取得的完整结果，扩大范围或改变核心方向时重新研究。取回原文时，将真实作品与章节来源、选择理由和适配方式写入当前任务记录及需要持久保存的完整设计。

## 完成标准

完整上下文和笔记已读取；场景因果明确；正文和角色信息已保存；按评审强度完成检查；完整章节笔记与状态已保存和回读。

## 执行流程

1. 用 `get_canvas_index` 与 `read_node_content` 读取用户笔记、世界观、角色、作品规划笔记、前文和已有目标章节的正文与笔记。新章使用 `create_node` 建 content 为空的 chapter，并设置作品内 sort_order。
2. 场景规划前用 `list_chapters` 读取目录与 catalog_revision，按章节号分批调用 `read_chapter_context` 读取相关前章及目标章节完整正文，用 `read_chapter_notes` 读取完整笔记；每个 session 从作品持久数据重建事实。为缺少笔记的前章补齐有正文依据的事实，保留已有作者要求与设计。核对数量收支、人物能力与认知、伤势、时间地点、物品归属和未决线索，逐项记录来源章节 UUID 和正文证据；笔记简明保存续写所需结论，核对过程留在当前任务记录中。冲突需要作者决定时先确认。
3. 用 `load_workflow_skill` 加载 `plan-chapter-scenes`，按该技能完整读取 `scene_plan.txt`。Supervisor 先完成章节“大方向”：确定叙事功能、目标体验、节奏强度、参与人物、开篇状态、目标章末状态并核对相邻章节节奏。工具集中有 `run_reference_agent` 时，在展开场景事件前调用它；提交上述大方向、当前故事事实和小说 ID，由它从上传小说取回带来源的章节原文。取回原文后，Supervisor 阅读、选择、组合并本作化。本轮未取回章节原文时，按作者、既有大纲和章节笔记中的事件链落实。最终落实为事件因果、情绪曲线、有效阻力、参与者目的、关键选择及局势变化。用 `save_chapter_notes(chapter_node_id, notes=完整章节笔记, expected_content_sha256=回读值)` 保存笔记；笔记以紧凑条目保留关键事实、完整有效作者要求、可续写的事件骨架和有用状态，待写事件明确标记为计划。完整计划留在当前任务说明中，具体文学表达在写正文时完成。
4. 创建确有必要的新角色，用 `update_node` 把真实角色 id/name 写入 `characters`；场景标题和目的写入章节笔记。
5. 完整加载 `chapter_writer.txt`，由 Supervisor 用于任务设计与回读验收。读取目标章节最新编号全文，取得 `content_sha256`。空章或作者明确授权的整章重写使用 `compose_chapter(mode="overwrite")`；已有章节续写使用 replace 选定末段，在任务说明中要求逐字保留原末段并在其后追加新内容，范围外原文由程序保留。完整交接作者原话、已确认计划、章节目标与重要事件、当前阶段和较早故事记忆、叙述视角、写作偏好及目标篇幅，使用 source_node_ids 选择相关人物、世界观和需回查的章节，并传入目标章节 ID 和本次 expected_content_sha256。程序完整装配作品普通笔记、所选节点、最近三章和目标章的正文与笔记，Writer 在独立上下文成文并通过既有保存管线提交。成功后用 `read_node_content` 回读实际正文。
6. 低档进入第 10 步。中、高档加载 `evaluate-fiction`，调用 `run_review_agent`，提供目标章节、完整作者要求与相关来源，使用 perspectives=["tired_reader", "ai_taste"] 并行评审阅读体验与表达自然度。保留报告对应的正文哈希、阅读结论与具体问题。中、高档评审与修订次数不限，针对实际修改后的最新正文复检。
7. 根据报告与作者要求判断值得采纳的建议，区分表达问题与场景设计问题。自然化适用于作者明确提出或报告定位到的具体表达问题，此时加载 `humanize-fiction`，由 Writer 修改正文。
8. 汇总本章全部检查结果，读取 `chapter_revision_decision.txt`，自行选择局部修改、整章重写或场景重规划，并按该决定执行。
9. 局部修改完整读取 `chapter_local_edit.txt`，用 `compose_chapter(mode="replace")` 指定最新正文的单个连续段落范围；整章重写完整读取 `chapter_rewrite.txt` 与 `chapter_writer.txt`，使用 compose_chapter 的 overwrite。场景重规划加载 `plan-chapter-scenes` 并读取 `chapter_replan.txt`，保存新计划及后续承接，再完整交接给 Writer。每次提交包含完整作者要求、采纳的修订意见、需保留的事实和本次正文哈希，保存后回读。纯删除或已确定措辞的替换使用 `update_node(mode="replace")`。高档复检实际最新正文，中档按已确认评审流程处理重要问题。
10. 新写和整章重写默认 2000 字左右，作者指定其他篇幅时采用作者要求。保存后调用 `count_chapter_words`，expected_word_count 使用本次采用的篇幅。明显偏离时完整读取 `chapter_length_advice.txt`，每次任务最多进行两次篇幅修改，随后说明剩余差距。局部修改保持本章既有篇幅。
11. 加载 `maintain-story-memory`，基于全部修改与篇幅调整后的最终正文更新完整章节笔记和章末状态，使用其保存步骤同步笔记、角色变化及未决线索，再回读确认。


异步执行协议：run_review_agent 和 run_reference_agent 派发后返回 task_id。可先处理独立工作，需要等待时单独调用 wait_for_subagents；收到子任务完成通知后，再使用其结果、回读正文和核验任务。运行期间的新要求由 Supervisor 整理，通过 steer_subagent 投递给相关任务。compose_chapter 同步完成 Writer 创作与保存，返回实际结果；Writer 使用本次调用提供的完整材料。
