---
name: design-characters
description: 创建或修改角色卡、动机、人物声音、发展线及关系。
---

# 设计角色

本技能由 Supervisor 亲自执行。参考规则通过 `read_skill_reference` 按阶段完整加载，工具仅负责读取与保存。
参考文件中的结构化输出格式用于组织工作记录；正文使用节点工具保存，用户回复使用 `respond_to_user`。

## 完成标准

角色动机、语言和行为符合故事职责；发展线、定位、关系和节点均保存并回读。

## 执行流程

1. 读取现有角色、人物关系、相关结构与用户完整要求。
2. 用 `read_skill_reference` 加载 `character_design.txt`，亲自设计角色的身份、认知、欲望、选择和变化。
3. 用 `create_node` 或 `update_node` 写入角色；已有角色的 `content` 局部调整使用 `update_node(mode="replace", replacements=[...])`，整体重构才使用 `mode="overwrite"`。发展线写入 `storylines`，定位使用 `scope`，已有角色沿用真实 UUID。
4. 通过角色关系工具保存真实角色之间的关系并回读；涉及既有角色核心事实变化时请用户决定范围。
