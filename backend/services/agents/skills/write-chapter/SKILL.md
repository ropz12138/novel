---
name: write-chapter
description: Supervisor 规划、直接编写章节正文，Reviewer 评审阅读体验。
---

# 写作章节工作流

Supervisor 负责规划、正文创作、评审决策和记忆，阅读评审通过 `run_review_agent`。参考规则通过 `read_skill_reference` 按阶段完整加载。
参考文件中的结构化输出格式用于组织工作记录；章节正文通过 `update_node` 保存，用户回复使用 `respond_to_user`。

## 创作参考前置

新内容设计与创作的必经环节是参考研究。Supervisor 先确定范围、目标体验及作者约束，工具集中有 `run_reference_agent` 时，本轮实际调用它。取回章节原文后完成本作化，再形成具体方案并直接编写正文。作者已有完整方案时，检索围绕其已确认内容取回相关章节原文。本轮未取回章节原文时，按当前作品已有事实、作者已确认的事件与设定完成本轮方案与正文。同一轮同一范围沿用本轮已取得的完整结果，扩大范围或改变核心方向时重新研究。取回原文时，将真实作品与章节来源、选择理由和适配方式写入当前任务记录及需要持久保存的完整设计。

## 完成标准

完整上下文和笔记已读取；场景因果明确；正文和角色信息已保存；按评审强度完成检查；完整章节笔记与状态已保存和回读。

## 执行流程

1. 用 `get_canvas_index` 与 `read_node_content` 读取用户笔记、世界观、角色、所属结构、前文和已有目标章节的正文与笔记。新章使用 `create_node` 建 content 为空的 chapter，用 `create_edge` 建立 plot→chapter 父子关系。
2. 场景规划前用 `list_chapters` 读取目录与 catalog_revision，按章节号分批调用 `read_chapter_context` 读取相关前章及目标章节完整正文，用 `read_chapter_notes` 读取完整笔记；每个 session 从作品持久数据重建事实。为缺少笔记的前章补齐有正文依据的事实，保留已有作者要求与设计。核对数量收支、人物能力与认知、伤势、时间地点、物品归属和未决线索，逐项记录来源章节 UUID 和正文证据；笔记简明保存续写所需结论，核对过程留在当前任务记录中。冲突需要作者决定时先确认。
3. 用 `load_workflow_skill` 加载 `plan-chapter-scenes`，按该技能完整读取 `scene_plan.txt`。Supervisor 先完成章节“大方向”：确定叙事功能、目标体验、节奏强度、参与人物、开篇状态、目标章末状态并核对相邻章节节奏。工具集中有 `run_reference_agent` 时，在展开场景事件前调用它；提交上述大方向、当前故事事实和小说 ID，由它从上传小说取回带来源的章节原文。取回原文后，Supervisor 阅读、选择、组合并本作化。本轮未取回章节原文时，按作者、既有大纲和章节笔记中的事件链落实。最终落实为事件因果、情绪曲线、有效阻力、参与者目的、关键选择及局势变化。用 `save_chapter_notes(chapter_node_id, notes=完整章节笔记, expected_content_sha256=回读值)` 保存笔记；笔记以紧凑条目保留关键事实、完整有效作者要求、可续写的事件骨架和有用状态，待写事件明确标记为计划。完整计划留在当前任务说明中，具体文学表达在写正文时完成。
4. 创建确有必要的新角色，用 `update_node` 把场景标题和目的写入 `chapter_elements`、真实角色 id/name 写入 `characters`。
5. 完整加载 `chapter_writer.txt`。读取目标章节最新编号全文，取得 `content_sha256`。核对已注入的作者写作要求、文风和手法笔记，按内容与适用范围使用。空章或明确的整章重写使用 `update_node(mode="overwrite")`，提交完整正文和本次读取的哈希。保存后用 `read_node_content` 回读实际正文。
6. 低档进入第 10 步。中、高档加载 `evaluate-fiction`，调用 `run_review_agent`，提供目标章节、完整作者要求与相关来源，使用 perspectives=["tired_reader", "ai_taste"] 并行评审阅读体验与表达自然度。保留报告对应的正文哈希、阅读结论与具体问题。中、高档评审与修订次数不限，针对实际修改后的最新正文复检。
7. 根据报告与作者要求判断值得采纳的建议，区分表达问题与场景设计问题。自然化适用于作者明确提出或报告定位到的具体表达问题，此时加载 `humanize-fiction` 并直接修改正文。
8. 汇总本章全部检查结果，读取 `chapter_revision_decision.txt`，自行选择局部修改、整章重写或场景重规划，并按该决定执行。
9. 局部修改完整读取 `chapter_local_edit.txt`，用 `update_node(mode="replace")` 按最新编号修改对应段落；整章重写读取 `chapter_rewrite.txt` 与 `chapter_writer.txt` 后使用 overwrite；场景重规划加载 `plan-chapter-scenes` 并读取 `chapter_replan.txt`，保存新计划及后续承接，再读取最新正文并写入。每次保存携带本次读取的 `content_sha256`，保存后回读。高档调用评审子 Agent 复检最新正文，直到具体问题解决或剩余建议无需采纳；中档汇总修改后进入收尾。
10. 加载 `maintain-story-memory`，基于回读的最终正文更新完整章节笔记和章末状态，使用其保存步骤同步笔记、角色变化及未决线索，再回读确认。
11. 新写和整章重写默认 2000 字左右，作者指定其他篇幅时采用作者要求。保存后调用 `count_chapter_words`，expected_word_count 使用本次采用的篇幅。明显偏离时读取 `chapter_length_advice.txt`，每次任务最多进行两次篇幅修改，随后说明剩余差距。局部修改保持本章既有篇幅。


异步执行协议：run_review_agent 和 run_reference_agent 派发后返回 task_id。可先处理独立工作，需要等待时单独调用 wait_for_subagents；收到子任务完成通知后，再使用其结果、回读正文和核验任务。运行期间的新要求由 Supervisor 整理，通过 steer_subagent 投递给相关任务。章节正文在当前上下文编写，并用 update_node 保存。
