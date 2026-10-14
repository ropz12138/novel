---
name: apply-research
description: Supervisor 将研究全文转化为当前作品可用技法。
---

# 应用研究成果

本技能由 Supervisor 亲自执行。参考规则通过 `read_skill_reference` 按阶段完整加载，工具仅负责读取与保存。
参考文件中的结构化输出格式用于组织工作记录；章节正文创作交给 `run_writing_agent`，其他节点使用节点工具保存，用户回复使用 `respond_to_user`。

## 完成标准

来源可追踪，应用建议明确，迁移写作方法并保持本作品事实。

## 执行流程

1. 用 `list_research_artifacts` 找出相关成果，`read_research_artifacts` 读取完整正文及来源 ID。
2. 读取当前作品相关节点和用户笔记，完整加载 `research_application.txt`。
3. 亲自分析适用环节、可借鉴方法及本作品中的具体实现；核对角色与设定均来自当前作品。
4. 在回复中给出完整建议与来源 ID。只要求分析时报告结论；要求实际创作时加载对应技能并执行节点编辑。
