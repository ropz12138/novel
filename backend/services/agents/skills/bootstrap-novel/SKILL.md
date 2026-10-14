---
name: bootstrap-novel
description: 从灵感搭建作品定位、世界观、人物、总纲与初始结构。
---

# 初始化小说

本技能由 Supervisor 亲自执行。参考规则通过 `read_skill_reference` 按阶段完整加载，工具仅负责读取与保存。
参考文件中的结构化输出格式用于组织工作记录；设定使用节点工具保存，章节正文交给 `run_writing_agent`，用户回复使用 `respond_to_user`。

## 完成标准

真实节点覆盖作品定位、核心角色、世界规则、总纲与用户需求笔记（`note`）；层级、顺序和内容已回读。

## 执行流程

1. 用 `get_canvas_index` 找出既有节点，`read_node_content` 读取全部笔记及相关作品资料，整理用户完整要求。
2. 用 `read_skill_reference` 加载本技能的 `premise_architect.txt`，亲自完成架构构思，将用户提出的需求完整保存到同主题笔记。
3. 用 `create_node` 建立真实节点，记录 UUID；沿用已有节点时，局部调整 `content` 使用 `update_node(mode="replace", replacements=[...])`，整体重构才使用 `mode="overwrite"`。使用真实 UUID 和 `create_edge` 建立 outline→volume→plot→chapter 父子连线。
4. 由你把构思写入节点 `content`，将角色发展线写入 `storylines`，角色定位写入 `scope`。
5. 回读节点和笔记，检查层级、因果、用户约束与内容一致性，修订更新原 UUID。
