---
name: design-worldbuilding
description: 创建或修改世界规则、地点、势力、资源和力量体系。
---

# 设计世界观

本技能由 Supervisor 亲自执行。参考规则通过 `read_skill_reference` 按阶段完整加载，工具仅负责读取与保存。
参考文件中的结构化输出格式用于组织工作记录；正文使用节点工具保存，用户回复使用 `respond_to_user`。

## 完成标准

世界规则服务主线且与既有事实兼容，目标节点已保存和回读。

## 执行流程

1. 读取相关世界观、结构、既有正文和用户笔记，明确修改目标。
2. 用 `read_skill_reference` 读取 `worldbuilding.txt`，亲自设计规则、代价、边界和冲突来源。
3. 新设定用 `create_node`；已有设定写回原 UUID，局部调整 `content` 使用 `update_node(mode="replace", replacements=[...])`，整体重构才使用 `mode="overwrite"`。影响既有正文事实的变更先明确范围并取得用户决定。
4. 回读目标节点，核对规则可执行性和既有事实。
