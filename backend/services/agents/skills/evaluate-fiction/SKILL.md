---
name: evaluate-fiction
description: 通过独立评审子 Agent 阅读章节，返回有原文依据的体验判断与修改建议。
---

# 评估小说内容

Supervisor 确定范围与完整作者要求，通过 `run_review_agent` 委派独立只读评审。评审运行时完整加载对应视角规则，并沿用项目统一模型适配层。正文修订交给 `run_writing_agent`，用户回复使用 `respond_to_user`。

## 完成标准

范围与正文版本明确；报告包含阅读感受、所需体验元素、继续阅读意愿，以及有原文定位、影响和可执行建议的问题。Supervisor 根据作者要求判断采纳范围。

## 执行流程

1. 读取目标全文、用户笔记、相关设定及前文，确定章节范围与本次阅读问题。当前评审对象是章节正文，其他节点作为背景参考。
2. 调用 `run_review_agent(chapter_node_ids, source_node_ids, author_requirements, review_goal, perspectives)`。常规创作使用 perspectives=["tired_reader", "ai_taste"] 并行评审；作者单独要求 AI 味评审时使用 ["ai_taste"]，单独要求劳累读者体验时使用 ["tired_reader"]。目标章节按阅读顺序提供，相关前章、角色、设定与适用笔记通过真实 UUID 完整加载；完整有效作者要求放入 author_requirements。运行时从数据库建立完整正文快照，返回正文哈希与独立报告。
3. tired_reader 代表上了一天班的劳累读者，关注阅读负担、投入感、情绪回报与继续阅读意愿。ai_taste 评审表达自然度、重复模板、冗余解释、动作和修辞、人物对白，给出原文依据与保留事实的局部修改建议。Supervisor 汇总 reports 中的问题，核对作者意图与修改价值；errors 中的失败明确报告，完成情况以实际返回为依据。
4. 中档创作每章每个评审视角检查一次，再统一修订；高档针对实际修改后的最新正文复检。低档在作者明确要求评估时调用本技能。报告引用的正文哈希与当前版本一致时，建议适用于该版本；正文变化时先核对受影响片段，高档复检使用新快照。
5. 单独的只读评估返回报告结论。创作流程按授权范围将采纳建议交给 Writer，涉及场景设计时加载 `plan-chapter-scenes`；作者要求或需要跨会话保留的决定合并进章节笔记。
