---
name: plan-outline
description: 创建、反推、续推或修订总纲与分卷方向。
---

# 规划总纲

本技能由 Supervisor 亲自执行。参考规则通过 `read_skill_reference` 按阶段完整加载，工具仅负责读取与保存。
参考文件中的结构化输出格式用于组织工作记录；正文使用节点工具保存，用户回复使用 `respond_to_user`。

## 完成标准

总纲具备核心承诺、主要矛盾、阶段升级及最终变化，并与既有正文一致。

## 执行流程

1. 读取结构节点、相关章节和完整用户要求，明确 create、reverse、continue 或 revise 任务。
2. 用 `read_skill_reference` 读取 `outline_plan.txt`，亲自组织因果与分卷方向；反推任务以已有正文为事实。
3. 用 `create_node` 建立新的总纲/卷，`create_edge` 建立父子关系；首次写入使用 `update_node(mode="overwrite")` 保存完整内容，已有总纲或卷的局部修订使用 `update_node(mode="replace", replacements=[...])`，整体重构才使用 `mode="overwrite"`，并始终沿用已有 UUID。
4. 回读核对因果、升级、题材承诺、顺序和正文兼容性。
